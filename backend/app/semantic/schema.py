"""Esquema Pydantic del modelo semántico (docs/MODELO_SEMANTICO.md).

`parse_semantic_model` es la puerta de entrada: valida la estructura y las reglas cruzadas y
devuelve todos los errores juntos, cada uno con la ruta del campo (`metrics[2].dimensions[0]`).
Un `SemanticModel` que existe ya pasó todas las validaciones.
"""

import json
import re
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Self

import sqlglot
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from pydantic_core import PydanticCustomError
from sqlglot import exp
from sqlglot.dialects.dialect import Dialect
from sqlglot.errors import SqlglotError

ColumnRole = Literal["time", "measure", "dimension", "id", "other"]
Grain = Literal["day", "week", "month", "quarter", "year"]
MetricFormat = Literal["currency", "integer", "number", "percent"]
Weekday = Literal["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

# Marcador de atributo del usuario en las condiciones de rol: {user.sucursales}
_MARKER = re.compile(r"\{user\.[A-Za-z_]\w*\}")


@dataclass(frozen=True)
class Issue:
    """Un error o advertencia del modelo, con la ruta del campo afectado."""

    path: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}: {self.message}" if self.path else self.message


class SemanticModelError(ValueError):
    """El modelo no es válido. `issues` trae todos los errores, cada uno con su ruta."""

    def __init__(self, issues: list[Issue]) -> None:
        self.issues = issues
        super().__init__("\n".join(str(issue) for issue in issues))


class _Base(BaseModel):
    # Un campo mal escrito debe fallar en voz alta, no ignorarse.
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class Settings(_Base):
    timezone: str = "UTC"
    currency: str | None = None
    locale: str | None = None
    fiscal_year_start_month: int = Field(default=1, ge=1, le=12)
    week_starts_on: Weekday = "monday"
    default_row_limit: int = Field(default=1000, gt=0)


class Column(_Base):
    name: str = Field(min_length=1)
    type: str | None = None
    description: str | None = None
    synonyms: list[str] = []
    role: ColumnRole = "other"
    hidden: bool = False
    sample_values: list[str | int | float] = []


class Table(_Base):
    name: str = Field(min_length=1)
    description: str | None = None
    synonyms: list[str] = []
    primary_key: list[str] = []
    time_column: str | None = None
    columns: list[Column] = []


class Relationship(_Base):
    from_: str = Field(alias="from")
    to: str


class Metric(_Base):
    name: str = Field(min_length=1)
    label: str = Field(min_length=1)
    description: str | None = None
    synonyms: list[str] = []
    table: str
    expression: str = Field(min_length=1)
    time_column: str
    filters: list[str] = []
    dimensions: list[str] = []
    format: MetricFormat | None = None
    requires_period: bool = True
    default_period: str | None = None
    additive: bool = True


class SummaryTable(_Base):
    table: str
    grain: Grain
    time_column: str
    includes_current_period: bool = True
    metrics: dict[str, str] = {}
    dimensions: dict[str, str] = {}


class RoleFilter(_Base):
    table: str
    condition: str = Field(min_length=1)


class Role(_Base):
    name: str = Field(min_length=1)
    description: str | None = None
    filters: list[RoleFilter] = []
    hidden_tables: list[str] = []


class Security(_Base):
    default_role: str | None = None
    roles: list[Role] = []


class SemanticModel(_Base):
    version: Literal[1]
    name: str = Field(min_length=1)
    dialect: str | None = None
    business_context: str = ""
    settings: Settings = Settings()
    tables: list[Table] = []
    relationships: list[Relationship] = []
    metrics: list[Metric] = []
    summary_tables: list[SummaryTable] = []
    security: Security = Security()

    @field_validator("dialect")
    @classmethod
    def _known_dialect(cls, value: str | None) -> str | None:
        try:
            Dialect.get_or_raise(value)
        except ValueError as exc:
            raise PydanticCustomError(
                "dialecto_desconocido", "Dialecto SQL desconocido: «{dialect}»", {"dialect": value}
            ) from exc
        return value

    @model_validator(mode="after")
    def _cross_validate(self) -> Self:
        issues = _check(self)
        if issues:
            raise SemanticModelError(issues)
        return self

    def warnings(self) -> list[Issue]:
        """Advertencias (no errores): el modelo es válido pero probablemente filtra de menos."""
        base_tables = {m.name: m.table for m in self.metrics}
        found: list[Issue] = []
        for i, role in enumerate(self.security.roles):
            covered = {f.table for f in role.filters} | set(role.hidden_tables)
            for j, rule in enumerate(role.filters):
                for summary in self.summary_tables:
                    uses_table = any(base_tables.get(m) == rule.table for m in summary.metrics)
                    if uses_table and summary.table not in covered:
                        found.append(
                            Issue(
                                f"security.roles[{i}].filters[{j}]",
                                f"«{rule.table}» está filtrada para el rol «{role.name}», pero su "
                                f"tabla resumida «{summary.table}» no tiene filtro para ese rol",
                            )
                        )
        return found


def parse_semantic_model(data: object) -> SemanticModel:
    """Valida un modelo (dict leído de YAML o JSON). Lanza `SemanticModelError` con todo."""
    try:
        return SemanticModel.model_validate(data)
    except ValidationError as exc:
        raise SemanticModelError(collect_issues(exc)) from exc


_MESSAGES = {
    "missing": "Campo obligatorio",
    "extra_forbidden": "Campo no permitido",
}


def format_path(loc: tuple[int | str, ...]) -> str:
    """`("metrics", 2, "dimensions", 0)` → `metrics[2].dimensions[0]`."""
    path = ""
    for part in loc:
        if isinstance(part, int):
            path += f"[{part}]"
        else:
            path += f".{part}" if path else part
    return path


def collect_issues(error: ValidationError) -> list[Issue]:
    """Convierte un `ValidationError` de Pydantic en una lista plana de `Issue`."""
    issues: list[Issue] = []
    for item in error.errors():
        inner = (item.get("ctx") or {}).get("error")
        if isinstance(inner, SemanticModelError):
            issues.extend(inner.issues)
            continue
        message = _MESSAGES.get(item["type"], item["msg"])
        issues.append(Issue(format_path(item["loc"]), message))
    return issues


# --------------------------------------------------------------------------- reglas cruzadas

_Add = Callable[[str, str], None]


def _find_column(table: Table, name: str) -> Column | None:
    return next((c for c in table.columns if c.name == name), None)


def _split_ref(ref: str) -> tuple[str, str] | None:
    table, _, column = ref.rpartition(".")
    return (table, column) if table and column else None


def _resolve(
    ref: str,
    base: Table | None,
    tables: dict[str, Table],
    path: str,
    add: _Add,
) -> tuple[Table, Column] | None:
    """Resuelve `tabla.columna` (o `columna`, si hay tabla base) a su tabla y columna."""
    split = _split_ref(ref)
    if split is None:
        if base is None:
            add(path, f"«{ref}» debe tener la forma tabla.columna")
            return None
        table, column_name = base, ref
    else:
        found = tables.get(split[0])
        if found is None:
            add(path, f"La tabla «{split[0]}» no existe")
            return None
        table, column_name = found, split[1]
    column = _find_column(table, column_name)
    if column is None:
        add(path, f"La columna «{column_name}» no existe en la tabla «{table.name}»")
        return None
    return table, column


def _check_time_column(
    ref: str, base: Table | None, tables: dict[str, Table], path: str, add: _Add
) -> None:
    resolved = _resolve(ref, base, tables, path, add)
    if resolved is None:
        return
    table, column = resolved
    if column.role != "time":
        add(path, f"«{table.name}.{column.name}» debe tener rol time (tiene «{column.role}»)")
    if column.hidden:
        add(path, f"Usa la columna oculta «{table.name}.{column.name}»")


def _first_line(exc: Exception) -> str:
    return next(iter(str(exc).splitlines()), "error de sintaxis")


def _check_sql(
    sql: str,
    dialect: str | None,
    base: Table | None,
    tables: dict[str, Table],
    path: str,
    add: _Add,
) -> None:
    """Parsea `sql` con sqlglot y rechaza el uso de columnas ocultas."""
    try:
        tree = sqlglot.parse_one(sql, read=dialect)
    except SqlglotError as exc:
        add(path, f"SQL no válido en el dialecto del modelo: {_first_line(exc)}")
        return
    for col in tree.find_all(exp.Column):
        qualifier = ".".join(part for part in (col.db, col.table) if part)
        table = tables.get(qualifier) if qualifier else base
        column = _find_column(table, col.name) if table else None
        if table and column and column.hidden:
            add(path, f"Usa la columna oculta «{table.name}.{column.name}»")


def _check_condition(condition: str, dialect: str | None, path: str, add: _Add) -> None:
    """Condición de rol: solo marcadores {user.nombre} bien formados y SQL válido."""
    rest = _MARKER.sub("NULL", condition)
    if "{" in rest or "}" in rest:
        add(path, "Marcador mal formado: usa {user.nombre} con letras, números o guion bajo")
        return
    try:
        sqlglot.parse_one(rest, read=dialect)
    except SqlglotError as exc:
        add(path, f"Condición no válida en el dialecto del modelo: {_first_line(exc)}")


def _shortest_path_count(adjacency: dict[str, list[str]], source: str, target: str) -> int:
    """Número de caminos de largo mínimo entre dos tablas (0 si no hay camino)."""
    dist = {source: 0}
    count = {source: 1}
    queue = deque([source])
    while queue:
        node = queue.popleft()
        for nxt in adjacency.get(node, []):
            if nxt not in dist:
                dist[nxt] = dist[node] + 1
                count[nxt] = count[node]
                queue.append(nxt)
            elif dist[nxt] == dist[node] + 1:
                count[nxt] += count[node]
    return count.get(target, 0)


def _check(model: SemanticModel) -> list[Issue]:
    issues: list[Issue] = []

    def add(path: str, message: str) -> None:
        issues.append(Issue(path, message))

    dialect = model.dialect
    tables: dict[str, Table] = {}

    # Tablas y columnas
    for i, table in enumerate(model.tables):
        if table.name in tables:
            add(f"tables[{i}].name", f"La tabla «{table.name}» está repetida")
        else:
            tables[table.name] = table
        seen: set[str] = set()
        for j, column in enumerate(table.columns):
            if column.name in seen:
                add(
                    f"tables[{i}].columns[{j}].name",
                    f"La columna «{column.name}» está repetida en «{table.name}»",
                )
            seen.add(column.name)
    for i, table in enumerate(model.tables):
        for j, name in enumerate(table.primary_key):
            if _find_column(table, name) is None:
                add(
                    f"tables[{i}].primary_key[{j}]",
                    f"La columna «{name}» no existe en la tabla «{table.name}»",
                )
        if table.time_column is not None:
            _check_time_column(table.time_column, table, tables, f"tables[{i}].time_column", add)

    # Relaciones
    adjacency: dict[str, list[str]] = {}
    for i, rel in enumerate(model.relationships):
        origin = _resolve(rel.from_, None, tables, f"relationships[{i}].from", add)
        target = _resolve(rel.to, None, tables, f"relationships[{i}].to", add)
        if origin and target and origin[0] is not target[0]:
            adjacency.setdefault(origin[0].name, []).append(target[0].name)
            adjacency.setdefault(target[0].name, []).append(origin[0].name)

    # Métricas
    metric_names: set[str] = set()
    for i, metric in enumerate(model.metrics):
        at = f"metrics[{i}]"
        if metric.name in metric_names:
            add(f"{at}.name", f"La métrica «{metric.name}» está repetida")
        metric_names.add(metric.name)
        base = tables.get(metric.table)
        if base is None:
            add(f"{at}.table", f"La tabla «{metric.table}» no existe")
        _check_sql(metric.expression, dialect, base, tables, f"{at}.expression", add)
        for j, condition in enumerate(metric.filters):
            _check_sql(condition, dialect, base, tables, f"{at}.filters[{j}]", add)
        _check_time_column(metric.time_column, base, tables, f"{at}.time_column", add)
        for j, ref in enumerate(metric.dimensions):
            path = f"{at}.dimensions[{j}]"
            dim = _resolve(ref, None, tables, path, add)
            if dim is None:
                continue
            if dim[1].hidden:
                add(path, f"Usa la columna oculta «{dim[0].name}.{dim[1].name}»")
            if base is None:
                continue
            paths = _shortest_path_count(adjacency, base.name, dim[0].name)
            if paths == 0:
                add(path, f"No hay relaciones entre «{base.name}» y «{dim[0].name}»")
            elif paths > 1:
                add(
                    path,
                    f"Hay {paths} caminos igual de cortos entre «{base.name}» y "
                    f"«{dim[0].name}»: desambigua las relaciones",
                )

    # Tablas resumidas
    for i, summary in enumerate(model.summary_tables):
        at = f"summary_tables[{i}]"
        table = tables.get(summary.table)
        if table is None:
            add(f"{at}.table", f"La tabla «{summary.table}» no existe")
        else:
            _check_time_column(summary.time_column, table, tables, f"{at}.time_column", add)
        for metric_name, expression in summary.metrics.items():
            path = f"{at}.metrics[{metric_name}]"
            if metric_name not in metric_names:
                add(path, f"La métrica «{metric_name}» no existe en metrics")
            _check_sql(expression, dialect, table, tables, path, add)
        for dim_ref, column_name in summary.dimensions.items():
            path = f"{at}.dimensions[{dim_ref}]"
            _resolve(dim_ref, None, tables, path, add)
            if table is None:
                continue
            target = _find_column(table, column_name)
            if target is None:
                add(path, f"La columna «{column_name}» no existe en la tabla «{table.name}»")
            elif target.hidden:
                add(path, f"Usa la columna oculta «{table.name}.{target.name}»")

    # Seguridad
    role_names: set[str] = set()
    for i, role in enumerate(model.security.roles):
        at = f"security.roles[{i}]"
        if role.name in role_names:
            add(f"{at}.name", f"El rol «{role.name}» está repetido")
        role_names.add(role.name)
        for j, rule in enumerate(role.filters):
            if rule.table not in tables:
                add(f"{at}.filters[{j}].table", f"La tabla «{rule.table}» no existe")
            _check_condition(rule.condition, dialect, f"{at}.filters[{j}].condition", add)
        for j, name in enumerate(role.hidden_tables):
            if name not in tables:
                add(f"{at}.hidden_tables[{j}]", f"La tabla «{name}» no existe")
    default_role = model.security.default_role
    if default_role is not None and default_role not in role_names:
        add("security.default_role", f"El rol «{default_role}» no existe en security.roles")

    return issues


# --------------------------------------------------------------------------- JSON Schema

SCHEMA_PATH = Path(__file__).parents[3] / "docs" / "schema" / "semantic-model.schema.json"


def json_schema() -> dict[str, Any]:
    """JSON Schema para autocompletado en editores (solo estructura, no las reglas cruzadas)."""
    schema = SemanticModel.model_json_schema()
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", **schema}


def write_json_schema(path: Path = SCHEMA_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(json_schema(), indent=2, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    write_json_schema()
