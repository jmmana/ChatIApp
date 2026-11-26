"""Enrutamiento a tablas resumidas: decide, con reglas fijas, si una métrica se responde mejor
desde una resumida que desde las tablas base.

Reglas en docs/MODELO_SEMANTICO.md#reglas-de-enrutamiento. Una resumida se usa solo si cumple
las seis; entre las que califican gana la de granularidad más gruesa (menos filas que leer) y,
si empatan, la primera declarada en el modelo. Sin resumida que califique se usan las tablas
base. Cada decisión trae su motivo en texto para el razonamiento visible. No hay IA ni red.
"""

from collections import deque
from dataclasses import dataclass, replace
from datetime import date
from typing import Final

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

from app.engine.catalog import VerifiedPlan
from app.engine.dialects import GRANULARITIES, Granularity
from app.engine.periods import PeriodRange
from app.semantic.schema import SemanticModel, SummaryTable

_WEEKDAYS: Final = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)
_CURRENT: Final = {
    "day": "el día en curso",
    "week": "la semana en curso",
    "month": "el mes en curso",
    "quarter": "el trimestre en curso",
    "year": "el año en curso",
}
_GRAIN_ADJECTIVE: Final = {
    "day": "diaria",
    "week": "semanal",
    "month": "mensual",
    "quarter": "trimestral",
    "year": "anual",
}
_QUARTER_STARTS: Final = (1, 4, 7, 10)


@dataclass(frozen=True, slots=True)
class SummaryDecision:
    """Resultado del enrutamiento.

    `table` es la resumida elegida o `None` si se usan las tablas base. `reason` explica la
    decisión en una frase; `rejected` lista cada resumida descartada con su motivo.
    """

    table: str | None
    reason: str
    rejected: tuple[tuple[str, str], ...] = ()


def route_summary(
    model: SemanticModel,
    plan: VerifiedPlan,
    *,
    period: PeriodRange | None = None,
    time_grain: Granularity | None = None,
    role: str | None = None,
) -> SummaryDecision:
    """Elige la tabla resumida que responde `plan` igual que las tablas base, si existe.

    `role` (por defecto `security.default_role`) importa: una resumida que el rol no filtra
    no puede reemplazar a una tabla base que sí filtra, o el rol vería filas ajenas.
    """
    if not model.summary_tables:
        return SummaryDecision(None, "El modelo no declara tablas resumidas: se usan las base")

    qualifying: list[SummaryTable] = []
    rejected: list[tuple[str, str]] = []
    role_filtered = _role_filtered_tables(model, role)
    for summary in model.summary_tables:
        why_not = _why_not(model, summary, plan, period, time_grain) or _role_problem(
            model, summary, plan, role, role_filtered
        )
        if why_not is None:
            qualifying.append(summary)
        else:
            rejected.append((summary.table, why_not))

    if not qualifying:
        detail = "; ".join(f"{table} {why}" for table, why in rejected)
        return SummaryDecision(None, f"Se usan las tablas base: {detail}", tuple(rejected))

    # Orden estable: a igual granularidad gana la primera declarada en el modelo.
    chosen = max(qualifying, key=lambda s: GRANULARITIES.index(s.grain))
    reason = f"Se usa {chosen.table} (granularidad {_GRAIN_ADJECTIVE[chosen.grain]})"
    if len(qualifying) > 1:
        others = ", ".join(s.table for s in qualifying if s is not chosen)
        reason += f": cumple las reglas y es la más gruesa; también calificaba {others}"
    else:
        reason += ": cumple las reglas de enrutamiento"
    if rejected:
        reason += "; " + "; ".join(f"{table} {why}" for table, why in rejected)
    return SummaryDecision(chosen.table, reason, tuple(rejected))


def plan_for_summary(model: SemanticModel, plan: VerifiedPlan, table: str) -> VerifiedPlan:
    """Reescribe `plan` para que `build_sql` lea de la resumida `table`.

    La métrica pasa a usar la tabla, la expresión y la columna de tiempo de la resumida (que ya
    trae sus propios filtros aplicados) y las dimensiones y filtros mapeados apuntan a sus
    columnas en la resumida; los demás se alcanzan por relación desde ella.
    """
    summary = next((s for s in model.summary_tables if s.table == table), None)
    if summary is None:
        raise ValueError(f"«{table}» no es una tabla resumida del modelo")
    expression = summary.metrics.get(plan.metric.name)
    if expression is None:
        raise ValueError(f"«{table}» no declara la métrica «{plan.metric.name}»")

    def column(field: str) -> str:
        mapped = summary.dimensions.get(_qualify(plan, field))
        return f"{table}.{mapped}" if mapped else field

    if _is_count(plan.metric.expression):
        # COUNT da 0 sobre cero filas, pero SUM(conteos) da NULL: un período vacío daría NULL.
        expression = f"COALESCE({expression}, 0)"
    metric = plan.metric.model_copy(
        update={
            "table": table,
            "expression": expression,
            "time_column": summary.time_column,
            "filters": [],
        }
    )
    return VerifiedPlan(
        metric,
        tuple(column(d) for d in plan.dimensions),
        tuple(replace(f, field=column(f.field)) for f in plan.filters),
    )


# ---------------------------------------------------------------------- reglas


def _why_not(
    model: SemanticModel,
    summary: SummaryTable,
    plan: VerifiedPlan,
    period: PeriodRange | None,
    time_grain: Granularity | None,
) -> str | None:
    """Motivo por el que `summary` no sirve, o `None` si cumple las 6 reglas."""
    metric = plan.metric
    # Reglas 1 y 6: la métrica debe estar declarada, con su propia expresión.
    expression = summary.metrics.get(metric.name)
    if expression is None or not expression.strip():
        if not metric.additive:
            return (
                f"no declara una expresión correcta para «{metric.name}», "
                "que no es aditiva (regla 6)"
            )
        return f"no declara la métrica «{metric.name}» (regla 1)"

    # Regla 2: dimensiones y filtros cubiertos.
    reachable = _reachable_tables(model, summary.table)
    for field in (*plan.dimensions, *(f.field for f in plan.filters)):
        qualified = _qualify(plan, field)
        table = qualified.rpartition(".")[0]
        if qualified not in summary.dimensions and table not in reachable:
            return f"no tiene «{field}» (regla 2)"

    # Regla 3: la granularidad pedida es igual o más gruesa que la de la resumida.
    if not _coarse_enough(time_grain, summary.grain):
        return (
            f"tiene granularidad {_GRAIN_ADJECTIVE[summary.grain]} y no da el detalle "
            f"por {_unit(time_grain)} que se pidió (regla 3)"
        )

    # Regla 4: los límites del período están alineados a la granularidad.
    week_start = model.settings.week_starts_on
    if period is not None and not (
        _aligned(period.start, summary.grain, week_start)
        and _aligned(period.end_exclusive, summary.grain, week_start)
    ):
        return (
            f"tiene granularidad {_GRAIN_ADJECTIVE[summary.grain]} y el período "
            f"«{period.label}» no está alineado a sus límites (regla 4)"
        )

    # Regla 5: si toca el período en curso, la resumida debe incluirlo.
    touches_current = period is None or period.is_current
    if touches_current and not summary.includes_current_period:
        return f"no incluye {_CURRENT[summary.grain]} (regla 5)"
    return None


def _role_filtered_tables(model: SemanticModel, role: str | None) -> set[str] | None:
    """Tablas que filtra el rol, o `None` si el rol no existe (falla cerrado)."""
    name = role or model.security.default_role
    if name is None:
        return set()
    found = next((r for r in model.security.roles if r.name == name), None)
    return None if found is None else {f.table for f in found.filters}


def _role_problem(
    model: SemanticModel,
    summary: SummaryTable,
    plan: VerifiedPlan,
    role: str | None,
    filtered: set[str] | None,
) -> str | None:
    """Regla 7: la resumida no puede saltarse el filtro por rol de las tablas base."""
    name = role or model.security.default_role
    if filtered is None:
        return f"no se usa porque el rol «{name}» no existe en el modelo (regla 7)"
    base_tables = {plan.metric.table}
    base_tables |= {
        _qualify(plan, field).rpartition(".")[0]
        for field in (*plan.dimensions, *(f.field for f in plan.filters))
    }
    if "." in plan.metric.time_column:
        base_tables.add(plan.metric.time_column.rpartition(".")[0])
    filtered_base = sorted(base_tables & filtered)
    if filtered_base and summary.table not in filtered:
        return (
            f"no tiene filtro para el rol «{name}», que sí filtra "
            f"{', '.join(filtered_base)} (regla 7)"
        )
    return None


def _is_count(expression: str) -> bool:
    try:
        node = sqlglot.parse_one(expression)
    except SqlglotError:
        return False
    return isinstance(node, exp.Count)


def _coarse_enough(requested: Granularity | None, grain: Granularity) -> bool:
    if requested is None or requested == grain:
        return True
    if grain == "week":  # las semanas no encajan en meses, trimestres ni años
        return False
    return GRANULARITIES.index(requested) > GRANULARITIES.index(grain)


def _aligned(day: date, grain: Granularity, week_starts_on: str) -> bool:
    if grain == "day":
        return True
    if grain == "week":
        return day.weekday() == _WEEKDAYS.index(week_starts_on)
    if grain == "month":
        return day.day == 1
    if grain == "quarter":
        return day.day == 1 and day.month in _QUARTER_STARTS
    return day.day == 1 and day.month == 1


def _unit(requested: Granularity | None) -> str:
    names = {"day": "día", "week": "semana", "month": "mes", "quarter": "trimestre", "year": "año"}
    return names[requested] if requested else "total"


def _qualify(plan: VerifiedPlan, field: str) -> str:
    """`tabla.columna`; una columna sola es de la tabla base de la métrica."""
    return field if "." in field else f"{plan.metric.table}.{field}"


def _reachable_tables(model: SemanticModel, source: str) -> set[str]:
    """Tablas alcanzables desde `source` siguiendo las relaciones `from` → `to`."""
    edges: dict[str, list[str]] = {}
    for rel in model.relationships:
        edges.setdefault(rel.from_.rpartition(".")[0], []).append(rel.to.rpartition(".")[0])
    seen = {source}
    queue = deque([source])
    while queue:
        for nxt in edges.get(queue.popleft(), ()):
            if nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)
    return seen
