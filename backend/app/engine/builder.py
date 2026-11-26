"""Constructor de SQL: arma, sin IA, el SQL de una métrica del catálogo a partir de su plan.

Misma entrada, mismo SQL. El plan ya pasó por `Catalog.verify`; aquí se resuelven los joins por
la ruta más corta de `relationships` (solo de muchos a uno, `from` → `to`), se aplican los
`filters` de la métrica y el rango `[inicio, fin)` de su `time_column`, y los valores del usuario
se insertan como literales escapados por sqlglot. El resultado pasa después por el guardián.
"""

from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

from app.engine.catalog import PlanFilter, VerifiedPlan
from app.engine.dialects import (
    GRANULARITIES,
    SQLGLOT_DIALECT,
    ColumnType,
    Dialect,
    Granularity,
    WeekStart,
    date_literal,
    date_trunc,
)
from app.engine.periods import PeriodRange
from app.semantic.schema import Column, Metric, SemanticModel, Table

VALUE_ALIAS: Final = "valor"
PERIOD_ALIAS: Final = "periodo"

_COMPARISONS: Final = {"=": "=", "!=": "<>", ">": ">", ">=": ">=", "<": "<", "<=": "<="}
_LIKE_ESCAPE: Final = "!"


class BuilderError(Exception):
    """El plan no se puede convertir en SQL. `message` está listo para mostrarse."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class PeriodRequiredError(BuilderError):
    def __init__(self, metric: str) -> None:
        self.metric = metric
        super().__init__(f"La métrica «{metric}» necesita un período")


class NoJoinPathError(BuilderError):
    def __init__(self, metric: str, table: str) -> None:
        self.metric = metric
        self.table = table
        super().__init__(
            f"No hay una ruta de muchos a uno desde la tabla de «{metric}» hasta «{table}»"
        )


@dataclass(frozen=True, slots=True)
class OrderTerm:
    """Criterio de orden: `valor` (la métrica), `periodo` (con `time_grain`) o una dimensión."""

    key: str
    descending: bool = False


@dataclass(frozen=True, slots=True)
class BuiltQuery:
    sql: str
    tables: tuple[str, ...]  # la tabla de la métrica primero y luego las unidas, en orden de join


@dataclass(frozen=True, slots=True)
class _Edge:
    origin: str
    origin_column: str
    target: str
    target_column: str


@dataclass(frozen=True, slots=True)
class _Ref:
    table: Table
    column: Column

    @property
    def sql(self) -> str:
        return f"{self.table.name}.{self.column.name}"


def build_sql(
    model: SemanticModel,
    plan: VerifiedPlan,
    dialect: Dialect,
    *,
    period: PeriodRange | None = None,
    time_grain: Granularity | None = None,
    order_by: Sequence[OrderTerm] = (),
    limit: int | None = None,
) -> BuiltQuery:
    """SQL de `plan.metric` en el dialecto de la fuente.

    Sin `limit`, las consultas agrupadas usan `settings.default_row_limit`; las de un solo valor
    no llevan límite. Los filtros por rol se agregan en el guardián (#33), no aquí.
    """
    return _Builder(model, plan, dialect, period, time_grain, order_by, limit).build()


class _Builder:
    def __init__(
        self,
        model: SemanticModel,
        plan: VerifiedPlan,
        dialect: Dialect,
        period: PeriodRange | None,
        time_grain: Granularity | None,
        order_by: Sequence[OrderTerm],
        limit: int | None,
    ) -> None:
        self.model = model
        self.metric: Metric = plan.metric
        self.plan = plan
        self.dialect = dialect
        self.sqlglot_dialect = SQLGLOT_DIALECT[dialect]
        self.period = period
        self.time_grain = time_grain
        self.order_by = tuple(order_by)
        self.limit = limit
        self.tables = {t.name: t for t in model.tables}
        self.edges = self._edges()

    # ------------------------------------------------------------------ armado

    def build(self) -> BuiltQuery:
        metric = self.metric
        if metric.requires_period and self.period is None:
            raise PeriodRequiredError(metric.name)
        if self.time_grain is not None and self.time_grain not in GRANULARITIES:
            raise BuilderError(f"Granularidad no válida: «{self.time_grain}»")
        if self.limit is not None and self.limit <= 0:
            raise BuilderError("El límite debe ser mayor que cero")

        time_ref = self._ref(metric.time_column)
        dimensions = [self._ref(d) for d in self.plan.dimensions]
        value = self._parse(metric.expression)
        conditions = [self._parse(f) for f in metric.filters]

        needed = {time_ref.table.name, *(d.table.name for d in dimensions)}
        user_conditions = [self._filter_sql(f, needed) for f in self.plan.filters]
        for tree in (value, *conditions):
            needed.update(col.table for col in tree.find_all(exp.Column))
        joins = self._joins(needed)

        period_expr = None
        if self.time_grain is not None:
            period_expr = self._trunc(time_ref)

        select = self._select_items(period_expr, dimensions, value)
        where = [self._condition_sql(c) for c in conditions] + user_conditions
        if self.period is not None:
            where.extend(self._range_sql(time_ref))

        group = ([period_expr] if period_expr else []) + [d.sql for d in dimensions]
        order = self._order_sql(dimensions, period_expr is not None)
        limit = self.limit
        if limit is None and group:
            limit = self.model.settings.default_row_limit

        base = metric.table
        top = f"TOP {limit} " if limit is not None and self.dialect == "tsql" else ""
        lines = [f"SELECT {top}{', '.join(select)}", f"FROM {base}"]
        lines.extend(
            f"LEFT JOIN {e.target} ON {e.origin}.{e.origin_column} = {e.target}.{e.target_column}"
            for e in joins
        )
        if where:
            lines.append("WHERE " + " AND ".join(where))
        if group:
            lines.append("GROUP BY " + ", ".join(group))
        if order:
            lines.append("ORDER BY " + ", ".join(order))
        if limit is not None and self.dialect == "oracle":
            lines.append(f"FETCH FIRST {limit} ROWS ONLY")
        elif limit is not None and self.dialect != "tsql":
            lines.append(f"LIMIT {limit}")
        return BuiltQuery("\n".join(lines), (base, *(e.target for e in joins)))

    def _select_items(
        self, period_expr: str | None, dimensions: list[_Ref], value: exp.Expression
    ) -> list[str]:
        items = [f"{period_expr} AS {PERIOD_ALIAS}"] if period_expr else []
        names = [d.column.name for d in dimensions]
        for ref in dimensions:
            repeated = names.count(ref.column.name) > 1
            alias = f"{ref.table.name}_{ref.column.name}" if repeated else ref.column.name
            items.append(f"{ref.sql} AS {alias}")
        items.append(f"{self._expression_sql(value)} AS {VALUE_ALIAS}")
        return items

    # ------------------------------------------------------------------ período

    def _range_sql(self, time_ref: _Ref) -> list[str]:
        assert self.period is not None
        column_type = _column_type(time_ref.column)
        start = date_literal(self.dialect, self.period.start, column_type)
        end = date_literal(self.dialect, self.period.end_exclusive, column_type)
        return [f"{time_ref.sql} >= {start}", f"{time_ref.sql} < {end}"]

    def _trunc(self, time_ref: _Ref) -> str:
        assert self.time_grain is not None
        week_start: WeekStart = self.model.settings.week_starts_on
        return date_trunc(
            self.dialect, time_ref.sql, self.time_grain, week_start, _column_type(time_ref.column)
        )

    # ------------------------------------------------------------------ orden

    def _order_sql(self, dimensions: list[_Ref], has_period: bool) -> list[str]:
        by_dimension = {d.sql: d for d in dimensions}
        terms: list[tuple[str, bool]] = []
        for term in self.order_by:
            terms.append((self._order_key(term.key, by_dimension, has_period), term.descending))
        if not terms and dimensions and not has_period:
            terms.append((VALUE_ALIAS, True))
        # Desempates fijos: el resultado no depende del orden en que el motor devuelva los grupos.
        tail = ([PERIOD_ALIAS] if has_period else []) + list(by_dimension)
        seen = {key for key, _ in terms}
        terms.extend((key, False) for key in tail if key not in seen)
        return [f"{key} {'DESC' if desc else 'ASC'}" for key, desc in terms]

    def _order_key(self, key: str, dimensions: dict[str, _Ref], has_period: bool) -> str:
        if key == VALUE_ALIAS:
            return VALUE_ALIAS
        if key == PERIOD_ALIAS:
            if not has_period:
                raise BuilderError("No se puede ordenar por período sin granularidad de tiempo")
            return PERIOD_ALIAS
        sql = self._ref(key).sql
        if sql not in dimensions:
            raise BuilderError(f"«{key}» no es la métrica ni una dimensión del plan")
        return sql

    # ------------------------------------------------------------------ filtros

    def _filter_sql(self, item: PlanFilter, needed: set[str]) -> str:
        ref = self._ref(item.field)
        needed.add(ref.table.name)
        column = ref.sql
        if item.op in _COMPARISONS:
            return f"{column} {_COMPARISONS[item.op]} {self._literal(item.value)}"
        if item.op == "in":
            if not isinstance(item.value, list | tuple) or not item.value:
                raise BuilderError(f"«{item.field}» in necesita una lista no vacía")
            return f"{column} IN ({', '.join(self._literal(v) for v in item.value)})"
        if item.op == "contains":
            if not isinstance(item.value, str):
                raise BuilderError(f"«{item.field}» contains necesita texto")
            escaped = (
                item.value.lower()
                .replace(_LIKE_ESCAPE, _LIKE_ESCAPE * 2)
                .replace("%", f"{_LIKE_ESCAPE}%")
                .replace("_", f"{_LIKE_ESCAPE}_")
            )
            pattern = self._literal(f"%{escaped}%")
            return f"LOWER({column}) LIKE {pattern} ESCAPE '{_LIKE_ESCAPE}'"
        raise BuilderError(f"Operador no válido para «{item.field}»: «{item.op}»")

    def _literal(self, value: Any) -> str:
        if isinstance(value, bool) or not isinstance(value, str | int | float):
            raise BuilderError("Los valores de los filtros deben ser texto o número")
        return str(exp.convert(value).sql(dialect=self.sqlglot_dialect))

    # ------------------------------------------------------------------ expresiones

    def _parse(self, sql: str) -> exp.Expression:
        """Parsea en el dialecto del modelo y califica las columnas sueltas con la tabla base."""
        try:
            tree = sqlglot.parse_one(sql, read=self.model.dialect)
        except SqlglotError as exc:
            raise BuilderError(f"SQL de la métrica no válido: {sql}") from exc
        for col in list(tree.find_all(exp.Column)):
            if not col.table:
                col.set("table", exp.to_identifier(self.metric.table))
            elif col.table not in self.tables:
                raise BuilderError(f"La tabla «{col.table}» no existe en el modelo")
        if self.dialect == "sqlite":
            _decimal_division(tree)
        return tree

    def _expression_sql(self, tree: exp.Expression) -> str:
        return str(tree.sql(dialect=self.sqlglot_dialect))

    def _condition_sql(self, tree: exp.Expression) -> str:
        if isinstance(tree, exp.Or):
            tree = exp.Paren(this=tree)
        return self._expression_sql(tree)

    # ------------------------------------------------------------------ joins

    def _edges(self) -> dict[str, list[_Edge]]:
        """Relaciones solo de muchos a uno, en el orden del modelo (desempate determinista)."""
        edges: dict[str, list[_Edge]] = {}
        for rel in self.model.relationships:
            origin, _, origin_column = rel.from_.rpartition(".")
            target, _, target_column = rel.to.rpartition(".")
            edges.setdefault(origin, []).append(_Edge(origin, origin_column, target, target_column))
        return edges

    def _joins(self, needed: set[str]) -> list[_Edge]:
        """Joins mínimos hacia `needed` por la ruta más corta, padres antes que hijos."""
        base = self.metric.table
        parent: dict[str, _Edge] = {}
        order = [base]
        queue = deque([base])
        while queue:
            node = queue.popleft()
            for edge in self.edges.get(node, ()):
                if edge.target != base and edge.target not in parent:
                    parent[edge.target] = edge
                    order.append(edge.target)
                    queue.append(edge.target)
        wanted: set[str] = set()
        for table in sorted(needed - {base}):
            if table not in parent:
                raise NoJoinPathError(self.metric.name, table)
            while table != base and table not in wanted:
                wanted.add(table)
                table = parent[table].origin
        return [parent[t] for t in order if t in wanted]

    # ------------------------------------------------------------------ referencias

    def _ref(self, ref: str) -> _Ref:
        """`tabla.columna` (o solo `columna` de la tabla de la métrica) del modelo."""
        table_name, _, column_name = ref.rpartition(".")
        table = self.tables.get(table_name or self.metric.table)
        column = next((c for c in table.columns if c.name == column_name), None) if table else None
        if table is None or column is None:
            raise BuilderError(f"El campo «{ref}» no existe en el modelo")
        return _Ref(table, column)


def _column_type(column: Column) -> ColumnType:
    declared = (column.type or "").lower()
    return "timestamp" if declared.startswith(("timestamp", "datetime")) else "date"


def _decimal_division(tree: exp.Expression) -> None:
    """SQLite divide enteros con resultado entero: `a / b` pasa a `a * 1.0 / b`."""
    for div in list(tree.find_all(exp.Div)):
        numerator = div.this
        operand = exp.Paren(this=numerator) if isinstance(numerator, exp.Binary) else numerator
        div.set("this", exp.Mul(this=operand, expression=exp.Literal.number("1.0")))
        div.set("typed", None)
        div.set("safe", None)
