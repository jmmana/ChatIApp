"""Comparación con el período anterior equivalente («¿cómo vamos?»).

Con `compare_previous` el motor calcula la métrica en el período pedido y en el anterior
equivalente (`periods.previous_equivalent`: «este mes al día 25» contra «mes anterior al día 25»,
«año pasado» contra el año anterior a ese) y devuelve ambos valores con su variación absoluta y
porcentual. Si el valor anterior es cero la variación porcentual es `None` y se explica.

Cada período se consulta por separado y solo se usa una tabla resumida si **ambos** califican
(reglas de docs/MODELO_SEMANTICO.md#reglas-de-enrutamiento). El SQL lo arma `builder`; quien
llama pasa `execute`, que debe validarlo con el guardián (filtros por rol incluidos) antes de
ejecutarlo.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

from app.engine.builder import build_sql
from app.engine.catalog import VerifiedPlan
from app.engine.dialects import GRANULARITIES, Dialect
from app.engine.periods import PeriodConfig, PeriodRange, previous_equivalent
from app.engine.summary import plan_for_summary, route_summary
from app.semantic.schema import Grain, SemanticModel, Weekday

Executor = Callable[[str], Sequence[Sequence[Any]]]
"""Ejecuta un SQL de un solo valor y devuelve sus filas."""

_GRAIN_RANK: Final[dict[Grain, int]] = {"day": 0, "week": 1, "month": 2, "quarter": 3, "year": 4}
_WEEKDAYS: Final[tuple[Weekday, ...]] = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)


class CompareError(Exception):
    """La comparación no se puede armar. `message` está listo para mostrarse."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class Comparison:
    """Valor del período, valor del anterior equivalente y su variación."""

    metric: str
    period: PeriodRange
    previous_period: PeriodRange
    value: float | None
    previous_value: float | None
    difference: float | None  # value - previous_value
    change_pct: float | None  # difference / |previous_value| * 100; None si no se puede calcular
    change_note: str | None  # por qué `change_pct` (o `difference`) es None
    summary_table: str | None  # tabla resumida usada en ambos períodos, si calificó
    summary_reason: str  # decisión de enrutamiento, para el razonamiento
    sql: str
    previous_sql: str


def compare_previous(
    model: SemanticModel,
    plan: VerifiedPlan,
    dialect: Dialect,
    period: PeriodRange,
    execute: Executor,
    *,
    now: datetime | None = None,
    role: str | None = None,
) -> Comparison:
    """Calcula `plan.metric` en `period` y en su período anterior equivalente.

    El plan debe ser de un solo valor (sin dimensiones): la comparación es del total. `now` fija
    el instante de referencia, como en `resolve_period`.
    """
    if plan.dimensions:
        raise CompareError("La comparación con el período anterior es del total, sin desglose")
    settings = model.settings
    config = PeriodConfig(
        timezone=settings.timezone,
        week_starts_on=settings.week_starts_on,
        fiscal_year_start_month=settings.fiscal_year_start_month,
        locale=settings.locale or "es-CO",
    )
    previous = previous_equivalent(period, config, now)

    summary, reason = _route(model, plan, period, previous, role)
    target = plan_for_summary(model, plan, summary) if summary else plan
    sql = build_sql(model, target, dialect, period=period).sql
    previous_sql = build_sql(model, target, dialect, period=previous).sql

    value = _single_value(execute(sql))
    previous_value = _single_value(execute(previous_sql))
    difference, change_pct, note = _variation(value, previous_value)
    return Comparison(
        metric=plan.metric.name,
        period=period,
        previous_period=previous,
        value=value,
        previous_value=previous_value,
        difference=difference,
        change_pct=change_pct,
        change_note=note,
        summary_table=summary,
        summary_reason=reason,
        sql=sql,
        previous_sql=previous_sql,
    )


# --------------------------------------------------------------------------- variación


def _single_value(rows: Sequence[Sequence[Any]]) -> float | None:
    if len(rows) != 1 or len(rows[0]) != 1:
        raise CompareError("La consulta de la métrica debe devolver un solo valor")
    value = rows[0][0]
    return None if value is None else float(value)


def _variation(
    value: float | None, previous: float | None
) -> tuple[float | None, float | None, str | None]:
    """(diferencia, porcentaje, explicación). La explicación solo existe si algo es `None`."""
    if value is None and previous is None:
        return None, None, "No hay datos en ninguno de los dos períodos"
    if previous is None:
        return None, None, "No hay datos en el período anterior: no hay variación que calcular"
    if value is None:
        return None, None, "No hay datos en el período actual: no hay variación que calcular"
    difference = value - previous
    if previous == 0:
        return difference, None, "El valor anterior es cero: la variación porcentual no existe"
    return difference, difference / abs(previous) * 100, None


# --------------------------------------------------------------------------- resumidas


def _route(
    model: SemanticModel,
    plan: VerifiedPlan,
    period: PeriodRange,
    previous: PeriodRange,
    role: str | None,
) -> tuple[str | None, str]:
    """La resumida que sirve para **los dos** períodos, con las reglas de `summary.route_summary`
    (incluida la regla 7 del rol). Si ninguna sirve para ambos, se usan las tablas base."""
    current = route_summary(model, plan, period=period, role=role)
    before = route_summary(model, plan, period=previous, role=role)
    declared = [s.table for s in model.summary_tables]
    fits_current = set(declared) - {table for table, _ in current.rejected}
    fits_before = set(declared) - {table for table, _ in before.rejected}
    common = [s for s in model.summary_tables if s.table in fits_current & fits_before]
    if not common:
        if current.table is None:
            return None, current.reason
        return None, (
            f"Se usan las tablas base: {current.table} sirve para «{period.label}» pero no "
            f"para «{previous.label}» ({before.reason})"
        )
    chosen = max(common, key=lambda s: GRANULARITIES.index(s.grain))
    reason = f"Se usa {chosen.table} en los dos períodos: cumple las reglas en ambos"
    discarded = dict.fromkeys(
        f"{table} {why}" for table, why in (*current.rejected, *before.rejected)
    )
    if discarded:
        reason += "; " + "; ".join(discarded)
    return chosen.table, reason
