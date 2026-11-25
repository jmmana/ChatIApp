"""Guardián SQL: integra sqlguardllm con el modelo semántico (ADR 0003).

Aquí no hay reglas de seguridad propias: `build_policy` traduce el modelo semántico, la fuente y
el rol a una `Policy` de sqlguardllm y `check_sql` devuelve lo que decide su `Guard`. Si falta una
regla, se pide en https://github.com/jmmana/sqlguardllm.

Los filtros por rol (`role.filters`) se conectan en una tarea aparte (#33).
"""

from dataclasses import dataclass
from threading import Lock
from uuid import UUID

from sqlguardllm import Guard, Policy

from app.db.models import Datasource
from app.engine.dialects import SQLGLOT_DIALECT, Dialect
from app.semantic.schema import SemanticModel

LANGUAGE = "es"


class UnknownRoleError(ValueError):
    """El rol no existe en `security.roles` del modelo."""


@dataclass(frozen=True)
class Violation:
    code: str  # código de sqlguardllm: write_operation, hidden_column...
    message: str  # en el idioma del usuario


@dataclass(frozen=True)
class GuardResult:
    allowed: bool
    sql: str | None  # SQL final (regenerado, con límite); None si se rechazó
    tables: tuple[str, ...]
    violations: tuple[Violation, ...]


def build_policy(
    model: SemanticModel,
    datasource: Datasource,
    role: str | None = None,
    default_schema: str | None = None,
) -> Policy:
    """Arma la `Policy` de sqlguardllm desde el modelo semántico.

    `role` vacío usa `security.default_role`. `default_schema` es opcional porque el modelo
    semántico aún no lo define.
    """
    role_name = role or model.security.default_role
    hidden_tables: set[str] = set()
    if role_name is not None:
        found = next((r for r in model.security.roles if r.name == role_name), None)
        if found is None:
            raise UnknownRoleError(f"El rol «{role_name}» no existe en el modelo")
        hidden_tables = set(found.hidden_tables)
    dialect: Dialect = datasource.dialect  # type: ignore[assignment]
    return Policy(
        dialect=SQLGLOT_DIALECT[dialect],
        allowed_tables=[t.name for t in model.tables if t.name not in hidden_tables],
        hidden_columns={
            t.name: [c.name for c in t.columns if c.hidden]
            for t in model.tables
            if any(c.hidden for c in t.columns)
        },
        max_rows=datasource.max_rows,
        default_schema=default_schema,
    )


class GuardCache:
    """Un `Guard` por (fuente, versión del modelo, rol). Una versión nueva descarta las viejas."""

    def __init__(self) -> None:
        self._guards: dict[tuple[UUID, int, str | None], Guard] = {}
        self._lock = Lock()

    def get(
        self,
        model: SemanticModel,
        datasource: Datasource,
        version: int,
        role: str | None = None,
    ) -> Guard:
        key = (datasource.id, version, role)
        with self._lock:
            guard = self._guards.get(key)
            if guard is None:
                guard = Guard(build_policy(model, datasource, role))
                # Publicar una versión nueva invalida las anteriores de la misma fuente.
                self._guards = {
                    k: g for k, g in self._guards.items() if k[0] != datasource.id or k[1] >= version
                }
                self._guards[key] = guard
            return guard

    def clear(self) -> None:
        with self._lock:
            self._guards.clear()


guards = GuardCache()


def check_sql(
    sql: str,
    model: SemanticModel,
    datasource: Datasource,
    version: int,
    role: str | None = None,
    cache: GuardCache = guards,
) -> GuardResult:
    """Valida `sql` con el guardián de la fuente, versión y rol."""
    result = cache.get(model, datasource, version, role).check(sql, language=LANGUAGE)
    violations = tuple(Violation(v.code, v.message) for v in result.violations)
    return GuardResult(
        allowed=not violations,
        sql=None if violations else result.sql,
        tables=tuple(result.tables),
        violations=violations,
    )


__all__ = [
    "GuardCache",
    "GuardResult",
    "UnknownRoleError",
    "Violation",
    "build_policy",
    "check_sql",
    "guards",
]
