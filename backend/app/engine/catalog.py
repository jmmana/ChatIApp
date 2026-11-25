"""Catálogo de métricas: resuelve y verifica el plan que propone la IA, sin construir SQL.

Es el paso «Verificar» de docs/FLUJO_CONVERSACIONAL.md: comprueba con código que la métrica,
las dimensiones y los filtros existen y están permitidos para el rol. Cada rechazo es un
`CatalogError` tipado, con los datos que el orquestador necesita para armar una aclaración.
"""

import unicodedata
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final

from app.semantic.schema import Column, Metric, SemanticModel, Table

OPERATORS: Final = ("=", "!=", ">", ">=", "<", "<=", "in", "contains")


def normalize(text: str) -> str:
    """Minúsculas, sin tildes y con espacios colapsados: «Cuánto  Vendí» → «cuanto vendi»."""
    decomposed = unicodedata.normalize("NFD", text.casefold())
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return " ".join(stripped.split())


@dataclass(frozen=True, slots=True)
class PlanFilter:
    """Filtro propuesto por la IA: `{field, op, value}` con `field` como `tabla.columna`."""

    field: str
    op: str
    value: Any


@dataclass(frozen=True, slots=True)
class VerifiedPlan:
    """Resultado de verificar un plan: la métrica resuelta y las dimensiones y filtros válidos."""

    metric: Metric
    dimensions: tuple[str, ...]
    filters: tuple[PlanFilter, ...]


class CatalogError(Exception):
    """Base de los rechazos de verificación. `message` está listo para mostrarse al usuario."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class UnknownMetricError(CatalogError):
    def __init__(self, name: str, available: Sequence[str]) -> None:
        self.name = name
        self.available = tuple(available)
        super().__init__(
            f"No existe la métrica «{name}». Las disponibles son: {', '.join(self.available)}"
        )


class AmbiguousMetricError(CatalogError):
    def __init__(self, name: str, candidates: Sequence[str]) -> None:
        self.name = name
        self.candidates = tuple(candidates)
        listado = ", ".join(self.candidates)
        super().__init__(f"«{name}» puede referirse a varias métricas: {listado}")


class MetricNotAllowedError(CatalogError):
    def __init__(self, metric: str, role: str) -> None:
        self.metric = metric
        self.role = role
        super().__init__(f"El rol «{role}» no tiene acceso a la métrica «{metric}»")


class DimensionNotAllowedError(CatalogError):
    def __init__(self, metric: str, dimension: str, allowed: Sequence[str]) -> None:
        self.metric = metric
        self.dimension = dimension
        self.allowed = tuple(allowed)
        listed = ", ".join(self.allowed) if self.allowed else "ninguna"
        super().__init__(
            f"La métrica «{metric}» no se puede desglosar por «{dimension}». "
            f"Dimensiones permitidas: {listed}"
        )


class UnknownFilterFieldError(CatalogError):
    def __init__(self, metric: str, field: str) -> None:
        self.metric = metric
        self.field = field
        super().__init__(
            f"El campo «{field}» no existe o no se puede usar con la métrica «{metric}»"
        )


class HiddenFieldError(CatalogError):
    def __init__(self, field: str, role: str | None) -> None:
        self.field = field
        self.role = role
        who = f"para el rol «{role}»" if role else "en este modelo"
        super().__init__(f"El campo «{field}» no está disponible {who}")


class InvalidOperatorError(CatalogError):
    def __init__(self, field: str, op: str) -> None:
        self.field = field
        self.op = op
        super().__init__(
            f"El operador «{op}» no es válido para «{field}». Operadores permitidos: "
            f"{', '.join(OPERATORS)}"
        )


class InvalidFilterValueError(CatalogError):
    def __init__(self, field: str, op: str, reason: str) -> None:
        self.field = field
        self.op = op
        super().__init__(f"Valor no válido para «{field}» {op}: {reason}")


class Catalog:
    """Vista de solo lectura de las métricas de un modelo semántico."""

    def __init__(self, model: SemanticModel) -> None:
        self._model = model
        self._tables = {t.name: t for t in model.tables}
        self._by_name = {m.name: m for m in model.metrics}
        self._adjacency: dict[str, set[str]] = {}
        for rel in model.relationships:
            origin, target = rel.from_.rpartition(".")[0], rel.to.rpartition(".")[0]
            self._adjacency.setdefault(origin, set()).add(target)
            self._adjacency.setdefault(target, set()).add(origin)

    @property
    def metrics(self) -> list[Metric]:
        return list(self._model.metrics)

    def find_metric(self, name: str) -> Metric:
        """Busca por nombre exacto y luego por etiqueta o sinónimo, sin tildes ni mayúsculas."""
        if name in self._by_name:
            return self._by_name[name]
        wanted = normalize(name)
        by_name = [m for m in self._model.metrics if normalize(m.name) == wanted]
        if len(by_name) == 1:
            return by_name[0]
        matches = by_name or [
            m
            for m in self._model.metrics
            if wanted == normalize(m.label) or wanted in {normalize(s) for s in m.synonyms}
        ]
        if len(matches) == 1:
            return matches[0]
        if matches:
            raise AmbiguousMetricError(name, [m.name for m in matches])
        raise UnknownMetricError(name, [m.name for m in self._model.metrics])

    def verify(
        self,
        metric: str,
        dimensions: Sequence[str] = (),
        filters: Sequence[PlanFilter] = (),
        role: str | None = None,
    ) -> VerifiedPlan:
        """Verifica métrica, dimensiones y filtros; lanza el primer `CatalogError` que halle."""
        found = self.find_metric(metric)
        role_name = role or self._model.security.default_role
        hidden_tables = self._hidden_tables(role_name)
        if found.table in hidden_tables:
            raise MetricNotAllowedError(found.name, role_name or "")
        for dimension in dimensions:
            self._check_dimension(found, dimension, hidden_tables, role_name)
        for item in filters:
            self._check_filter(found, item, hidden_tables, role_name)
        return VerifiedPlan(found, tuple(dimensions), tuple(filters))

    # ------------------------------------------------------------------ dimensiones

    def _check_dimension(
        self, metric: Metric, dimension: str, hidden_tables: set[str], role: str | None
    ) -> None:
        wanted = normalize(dimension)
        match = next((d for d in metric.dimensions if normalize(d) == wanted), None)
        if match is None:
            allowed = [d for d in metric.dimensions if not self._is_hidden(d, hidden_tables)]
            raise DimensionNotAllowedError(metric.name, dimension, allowed)
        if self._is_hidden(match, hidden_tables):
            raise HiddenFieldError(match, role)

    # ------------------------------------------------------------------ filtros

    def _check_filter(
        self, metric: Metric, item: PlanFilter, hidden_tables: set[str], role: str | None
    ) -> None:
        resolved = self._resolve_field(metric, item.field)
        if resolved is None:
            raise UnknownFilterFieldError(metric.name, item.field)
        table, column = resolved
        qualified = f"{table.name}.{column.name}"
        if column.hidden or table.name in hidden_tables:
            raise HiddenFieldError(qualified, role)
        if item.op not in OPERATORS:
            raise InvalidOperatorError(qualified, item.op)
        self._check_value(qualified, item.op, item.value)

    def _resolve_field(self, metric: Metric, field: str) -> tuple[Table, Column] | None:
        """`tabla.columna` (o solo `columna` de la tabla base) alcanzable desde la métrica."""
        table_name, _, column_name = field.rpartition(".")
        table = self._tables.get(table_name or metric.table)
        if table is None:
            return None
        column = next((c for c in table.columns if c.name == column_name), None)
        if column is None or not self._reachable(metric.table, table.name):
            return None
        return table, column

    def _reachable(self, source: str, target: str) -> bool:
        seen = {source}
        queue = deque([source])
        while queue:
            node = queue.popleft()
            if node == target:
                return True
            for nxt in self._adjacency.get(node, ()):
                if nxt not in seen:
                    seen.add(nxt)
                    queue.append(nxt)
        return False

    @staticmethod
    def _check_value(field: str, op: str, value: Any) -> None:
        if op == "in":
            if not isinstance(value, list | tuple) or not value:
                raise InvalidFilterValueError(field, op, "se espera una lista no vacía")
            items: Sequence[Any] = value
        else:
            items = [value]
        for entry in items:
            if isinstance(entry, bool) or not isinstance(entry, str | int | float):
                raise InvalidFilterValueError(field, op, "se espera texto o número")
            if op == "contains" and not isinstance(entry, str):
                raise InvalidFilterValueError(field, op, "se espera texto")

    # ------------------------------------------------------------------ seguridad

    def _hidden_tables(self, role: str | None) -> set[str]:
        for candidate in self._model.security.roles:
            if candidate.name == role:
                return set(candidate.hidden_tables)
        return set()

    def _is_hidden(self, ref: str, hidden_tables: set[str]) -> bool:
        table_name, _, column_name = ref.rpartition(".")
        if table_name in hidden_tables:
            return True
        table = self._tables.get(table_name)
        column = next((c for c in table.columns if c.name == column_name), None) if table else None
        return bool(column and column.hidden)
