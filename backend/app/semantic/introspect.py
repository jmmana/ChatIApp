"""Introspección de la base conectada con el inspector de SQLAlchemy.

Lee esquemas, tablas, columnas, tipos, llaves y comentarios y los devuelve como piezas del
modelo semántico (`Table`, `Relationship`). No guarda nada: es la vista previa del endpoint
`POST /datasources/{id}/semantic/introspect`.

Los valores de muestra se piden solo si la fuente tiene privacidad `samples`, y cada consulta
pasa por el guardián (`app.engine.guard`) antes de ejecutarse.
"""

import re
import time
from dataclasses import dataclass, field
from fnmatch import translate

from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.engine.reflection import Inspector
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.types import String, TypeEngine
from sqlglot import exp

from app.db.models import Datasource
from app.engine.connections import connect_args
from app.engine.dialects import SQLGLOT_DIALECT, Dialect
from app.engine.guard import GuardCache, check_sql
from app.semantic.schema import Column, Issue, Relationship, SemanticModel, Table

MAX_TABLES = 500  # más que esto se pide filtrar: reflejar miles de tablas no cabe en el tiempo
MAX_SAMPLES = 20
BUDGET_SECONDS = 25.0  # margen bajo los 30 s de respuesta para el muestreo

# Esquemas internos del motor: nunca son parte del modelo de negocio.
SYSTEM_SCHEMAS = frozenset(
    {
        "information_schema",
        "pg_catalog",
        "pg_toast",
        "sys",
        "mysql",
        "performance_schema",
        "guest",
        "db_owner",
        "db_accessadmin",
        "db_securityadmin",
        "db_ddladmin",
        "db_backupoperator",
        "db_datareader",
        "db_datawriter",
        "db_denydatareader",
        "db_denydatawriter",
    }
)


class TooManyTablesError(ValueError):
    """Hay más de `MAX_TABLES` tablas: hay que filtrar por esquema o por patrón de nombre."""

    def __init__(self, found: int) -> None:
        self.found = found
        super().__init__(
            f"La base tiene {found} tablas (máximo {MAX_TABLES}): filtra por esquema o por "
            "patrón de nombre de tabla"
        )


@dataclass
class Introspection:
    """Estructura leída de la base. `schemas` son los esquemas que se leyeron."""

    schemas: list[str] = field(default_factory=list)
    tables: list[Table] = field(default_factory=list)
    relationships: list[Relationship] = field(default_factory=list)
    warnings: list[Issue] = field(default_factory=list)
    # Tipos reflejados (tabla -> columna -> tipo), para elegir las columnas de texto al muestrear.
    column_types: dict[str, dict[str, TypeEngine[object]]] = field(default_factory=dict, repr=False)


def introspect(
    url: str,
    datasource: Datasource,
    schemas: list[str] | None = None,
    table_pattern: str | None = None,
    sample_values: bool = False,
) -> Introspection:
    """Lee la estructura de la base en `url`.

    `schemas` (nombres exactos) y `table_pattern` (comodines `*` y `?`, sin distinguir
    mayúsculas) son filtros opcionales. Lanza `TooManyTablesError` si quedan más de
    `MAX_TABLES` tablas. Los errores de conexión suben tal cual a quien llama.
    """
    started = time.monotonic()
    dialect: Dialect = datasource.dialect  # type: ignore[assignment]
    engine = create_engine(url, connect_args=connect_args(dialect, datasource.timeout_seconds))
    try:
        inspector = inspect(engine)
        result = _read_structure(inspector, schemas, table_pattern)
        if sample_values:
            _add_samples(engine, datasource, result, started)
        return result
    finally:
        engine.dispose()


def _qualified(schema: str | None, name: str, default: str | None) -> str:
    return name if schema is None or schema == default else f"{schema}.{name}"


def _type_name(column_type: TypeEngine[object]) -> str | None:
    try:
        return str(column_type)
    except Exception:  # tipos que el dialecto no sabe imprimir
        return None


def _pattern(table_pattern: str | None) -> re.Pattern[str] | None:
    return re.compile(translate(table_pattern), re.IGNORECASE) if table_pattern else None


def _read_structure(
    inspector: Inspector, schemas: list[str] | None, table_pattern: str | None
) -> Introspection:
    default = inspector.default_schema_name
    available = inspector.get_schema_names()
    if schemas:
        wanted = list(dict.fromkeys(schemas))
    else:
        wanted = [s for s in available if s.casefold() not in SYSTEM_SCHEMAS]
    result = Introspection()
    pattern = _pattern(table_pattern)

    selected: list[tuple[str | None, list[str]]] = []  # (esquema para SQLAlchemy, tablas)
    for schema in wanted:
        if schema not in available:
            result.warnings.append(Issue("", f"El esquema «{schema}» no existe"))
            continue
        names = inspector.get_table_names(schema=None if schema == default else schema)
        names = [n for n in names if pattern is None or pattern.match(n)]
        if names:
            selected.append((None if schema == default else schema, sorted(names)))
        result.schemas.append(schema)
    total = sum(len(names) for _, names in selected)
    if total > MAX_TABLES:
        raise TooManyTablesError(total)

    pending_fks: list[tuple[str, list[str], str | None, str, list[str]]] = []
    for schema, names in selected:
        columns = inspector.get_multi_columns(schema=schema, filter_names=names)
        pks = inspector.get_multi_pk_constraint(schema=schema, filter_names=names)
        fks = inspector.get_multi_foreign_keys(schema=schema, filter_names=names)
        try:
            comments = inspector.get_multi_table_comment(schema=schema, filter_names=names)
        except NotImplementedError:  # SQLite y otros motores sin comentarios
            comments = {}
        for name in names:
            key = (schema, name)
            qualified = _qualified(schema, name, default)
            cols = columns.get(key, [])
            result.column_types[qualified] = {c["name"]: c["type"] for c in cols}
            result.tables.append(
                Table(
                    name=qualified,
                    description=(comments.get(key) or {}).get("text") or None,
                    primary_key=list((pks.get(key) or {}).get("constrained_columns") or []),
                    columns=[
                        Column(
                            name=c["name"],
                            type=_type_name(c["type"]),
                            description=c.get("comment") or None,
                        )
                        for c in cols
                    ],
                )
            )
            for fk in fks.get(key, []):
                pending_fks.append(
                    (
                        qualified,
                        list(fk["constrained_columns"]),
                        fk.get("referred_schema"),
                        fk["referred_table"],
                        list(fk["referred_columns"]),
                    )
                )

    known = {t.name for t in result.tables}
    for table, own, ref_schema, ref_table, ref_columns in pending_fks:
        target = _qualified(ref_schema, ref_table, default)
        if target not in known:
            result.warnings.append(
                Issue(table, f"La llave foránea apunta a «{target}», que no está en la vista")
            )
            continue
        for own_column, ref_column in zip(own, ref_columns, strict=False):
            result.relationships.append(
                Relationship(**{"from": f"{table}.{own_column}", "to": f"{target}.{ref_column}"})
            )
    return result


def _sample_query(dialect: Dialect, qualified: str, column: str) -> str:
    schema, _, name = qualified.rpartition(".")
    table = exp.Table(
        this=exp.to_identifier(name, quoted=True),
        db=exp.to_identifier(schema, quoted=True) if schema else None,
    )
    col = exp.column(column, quoted=True)
    query = (
        exp.select(col)
        .distinct()
        .from_(table)
        .where(exp.Not(this=exp.Is(this=col.copy(), expression=exp.Null())))
        .limit(MAX_SAMPLES + 1)
    )
    return query.sql(dialect=SQLGLOT_DIALECT[dialect])


def _add_samples(
    engine: Engine, datasource: Datasource, result: Introspection, started: float
) -> None:
    """Llena `sample_values` de las columnas de texto con hasta 20 valores distintos."""
    if datasource.privacy != "samples":
        result.warnings.append(
            Issue(
                "",
                "Se omiten los valores de muestra: la privacidad de la fuente es "
                f"«{datasource.privacy}», no «samples»",
            )
        )
        return
    if datasource.max_rows <= MAX_SAMPLES:
        result.warnings.append(
            Issue("", f"Se omiten las muestras: el límite de filas es {datasource.max_rows}")
        )
        return
    dialect: Dialect = datasource.dialect  # type: ignore[assignment]
    # El guardián ve las tablas tal como se leyeron; una caché propia evita ensuciar la global.
    model = SemanticModel(version=1, name="introspeccion", tables=result.tables)
    cache = GuardCache()
    with engine.connect() as conn:
        for table in result.tables:
            for column in table.columns:
                column_type = result.column_types.get(table.name, {}).get(column.name)
                if not isinstance(column_type, String):
                    continue
                if time.monotonic() - started > BUDGET_SECONDS:
                    result.warnings.append(
                        Issue("", "Se agotó el tiempo: algunas columnas quedaron sin muestras")
                    )
                    return
                path = f"{table.name}.{column.name}"
                sql = _sample_query(dialect, table.name, column.name)
                verdict = check_sql(sql, model, datasource, 0, cache=cache)
                if not verdict.allowed or verdict.sql is None:
                    reason = "; ".join(v.message for v in verdict.violations)
                    result.warnings.append(Issue(path, f"El guardián rechazó la muestra: {reason}"))
                    continue
                try:
                    rows = conn.execute(text(verdict.sql)).scalars().all()
                except SQLAlchemyError:
                    conn.rollback()
                    result.warnings.append(Issue(path, "No se pudieron leer valores de muestra"))
                    continue
                values = [str(v) for v in rows]
                if 0 < len(values) <= MAX_SAMPLES:  # con más, no es de baja cardinalidad
                    column.sample_values = sorted(values)
