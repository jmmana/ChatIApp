"""Resolución de entidades contra la base («Bogotá» → las tiendas que coinciden).

Traduce el texto que dijo el usuario en un filtro de dimensión a valores reales de la base. La
búsqueda es un `SELECT DISTINCT ... LIKE` con tope de 20 filas; quien llama la ejecuta pasando
por el guardián y el filtro de rol (`Runner`), así este módulo no ve más de lo que ve el usuario.
Es código puro: sin IA ni red.

- Una coincidencia: el filtro usa el valor real.
- Varias: aclaración con las opciones más «Todas».
- Ninguna: mensaje con valores parecidos.

Ignora tildes y mayúsculas: el patrón `LIKE` cambia las vocales y la «n» por `_` y el resultado
se vuelve a filtrar aquí con `normalize`.
"""

import difflib
from collections.abc import Callable, Sequence

from app.agent.clarify import ALL_OPTION, ENTITY_SLOT_PREFIX, Question
from app.engine.catalog import PlanFilter, normalize
from app.semantic.schema import Column, SemanticModel

SEARCH_LIMIT = 20
_PREFIX_LENGTH = 3
_TEXT_TYPES = ("varchar", "char", "text", "nvarchar", "nchar", "string", "citext")
_ACCENTABLE = set("aeiounc")

# Ejecuta un SELECT ya construido (guardián + ejecutor) y devuelve la primera columna.
Runner = Callable[[str], list[str]]


class EntityQuestion(Exception):
    """Hay que preguntar: varios valores coinciden o ninguno."""

    def __init__(self, question: Question) -> None:
        super().__init__(question.question)
        self.question = question


def _text_column(model: SemanticModel, field: str) -> Column | None:
    table_name, _, column_name = field.rpartition(".")
    table = next((t for t in model.tables if t.name == table_name), None)
    column = next((c for c in table.columns if c.name == column_name), None) if table else None
    if column is None or column.role != "dimension":
        return None
    if column.type is not None and not column.type.lower().startswith(_TEXT_TYPES):
        return None
    return column


def like_pattern(term: str) -> str:
    """Patrón `LIKE` sin tildes ni mayúsculas, listo para ir entre comillas simples."""
    chars = []
    for ch in normalize(term):
        if ch in _ACCENTABLE or ch in "%_\\" or not ch.isascii():
            chars.append("_")
        elif ch == "'":
            chars.append("''")
        else:
            chars.append(ch)
    return f"%{''.join(chars)}%"


def search_sql(field: str, term: str, limit: int = SEARCH_LIMIT) -> str:
    return (
        f"SELECT DISTINCT {field} FROM {field.rpartition('.')[0]} "
        f"WHERE LOWER({field}) LIKE '{like_pattern(term)}' ORDER BY {field} LIMIT {limit}"
    )


def sample_sql(field: str, limit: int = SEARCH_LIMIT) -> str:
    return (
        f"SELECT DISTINCT {field} FROM {field.rpartition('.')[0]} "
        f"WHERE {field} IS NOT NULL ORDER BY {field} LIMIT {limit}"
    )


def find_matches(field: str, term: str, run: Runner) -> list[str]:
    """Valores reales de `field` que contienen `term` (sin tildes ni mayúsculas), máx. 20."""
    wanted = normalize(term)
    seen: dict[str, str] = {}
    for value in run(search_sql(field, term)):
        if isinstance(value, str) and wanted in normalize(value):
            seen.setdefault(value, value)
    return list(seen)


def similar_values(field: str, term: str, run: Runner) -> list[str]:
    """Valores parecidos a `term`: primero por prefijo y, si no hay, entre una muestra."""
    wanted = normalize(term)
    prefix = wanted[:_PREFIX_LENGTH]
    pool = run(search_sql(field, prefix)) if len(prefix) == _PREFIX_LENGTH else []
    if not pool:
        pool = run(sample_sql(field))
    by_norm = {normalize(v): v for v in pool if isinstance(v, str)}
    close = difflib.get_close_matches(wanted, list(by_norm), n=5, cutoff=0.5)
    return [by_norm[c] for c in close]


def _no_match(label: str, term: str, similar: Sequence[str], field: str) -> Question:
    slot = f"{ENTITY_SLOT_PREFIX}{field}"
    if similar:
        shown = ", ".join(f"«{v}»" for v in similar)
        text = f"No encontré «{term}» en {label}. Valores parecidos: {shown}. ¿Cuál quieres?"
        return Question(text, list(similar), slot)
    return Question(f"No encontré «{term}» en {label}. ¿Con qué valor quieres filtrar?", [], slot)


def resolve_filters(
    model: SemanticModel, filters: Sequence[PlanFilter], run: Runner
) -> tuple[PlanFilter, ...]:
    """Reemplaza el texto de los filtros `=` y `contains` sobre dimensiones por valores reales.

    Espera filtros ya verificados (`field` es `tabla.columna`). Lanza `EntityQuestion` si hay que
    preguntar. Los demás filtros pasan sin cambios.
    """
    resolved: list[PlanFilter] = []
    for item in filters:
        term = item.value.strip() if isinstance(item.value, str) else ""
        column = _text_column(model, item.field)
        if item.op not in ("=", "contains") or not term or column is None:
            resolved.append(item)
            continue
        label = (column.synonyms[0] if column.synonyms else column.name).lower()
        matches = find_matches(item.field, term, run)
        if item.op == "=":
            exact = [m for m in matches if normalize(m) == normalize(term)]
            matches = exact if len(exact) == 1 else matches
        if len(matches) == 1:
            resolved.append(PlanFilter(item.field, "=", matches[0]))
        elif matches:
            text = f"«{term}» coincide con {len(matches)} valores de {label}. ¿Cuál quieres?"
            slot = f"{ENTITY_SLOT_PREFIX}{item.field}"
            raise EntityQuestion(Question(text, [*matches, ALL_OPTION], slot))
        else:
            similar = similar_values(item.field, term, run)
            raise EntityQuestion(_no_match(label, term, similar, item.field))
    return tuple(resolved)
