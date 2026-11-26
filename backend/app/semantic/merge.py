"""Fusión de lo importado con el modelo existente (docs/MODELO_SEMANTICO.md, «Fusión»).

Importar nunca destruye trabajo hecho a mano: lo nuevo se agrega, los tipos se actualizan, las
descripciones vacías se completan, las escritas a mano se conservan (la de la fuente queda como
sugerencia) y lo que ya no está en la fuente se marca «no encontrado» sin borrarse. La fusión no
guarda nada: devuelve el modelo resultante y las diferencias para la vista previa.
"""

from dataclasses import dataclass, field

from app.semantic.schema import (
    Column,
    Issue,
    Relationship,
    SemanticModel,
    Table,
    parse_semantic_model,
)
from app.semantic.store import dump_model


@dataclass(frozen=True)
class Added:
    """`+ nueva`: tabla (`path` = `tabla`), columna (`tabla.columna`) o relación."""

    path: str
    kind: str  # table | column | relationship


@dataclass(frozen=True)
class Changed:
    """`~ cambiada`: un campo que la fusión actualizó o completó."""

    path: str
    field: str
    before: str | None
    after: str | None


@dataclass(frozen=True)
class Missing:
    """`− no encontrada`: está en el modelo pero ya no en la fuente. No se borra."""

    path: str
    kind: str  # table | column


@dataclass(frozen=True)
class Suggestion:
    """Descripción de la fuente distinta de la escrita a mano, que se conservó."""

    path: str
    field: str
    current: str
    suggested: str


@dataclass
class Diff:
    added: list[Added] = field(default_factory=list)
    changed: list[Changed] = field(default_factory=list)
    missing: list[Missing] = field(default_factory=list)
    suggestions: list[Suggestion] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not (self.added or self.changed or self.missing or self.suggestions)


@dataclass
class Imported:
    """Lo que trae una fuente de importación: estructura, sin métricas ni seguridad."""

    tables: list[Table] = field(default_factory=list)
    relationships: list[Relationship] = field(default_factory=list)
    warnings: list[Issue] = field(default_factory=list)


@dataclass
class MergeResult:
    model: SemanticModel
    diff: Diff
    warnings: list[Issue] = field(default_factory=list)


def _same(a: str, b: str) -> bool:
    return a.casefold() == b.casefold()


def _blank(text: str | None) -> bool:
    return text is None or not text.strip()


def _fill_description(
    target: Table | Column, source: Table | Column, path: str, diff: Diff
) -> None:
    if _blank(source.description):
        return
    assert source.description is not None
    if _blank(target.description):
        diff.changed.append(Changed(path, "description", target.description, source.description))
        target.description = source.description
    elif target.description != source.description:
        assert target.description is not None
        diff.suggestions.append(
            Suggestion(path, "description", target.description, source.description)
        )


def _merge_column(target: Column, source: Column, path: str, diff: Diff) -> None:
    if source.type is not None and (target.type is None or not _same(target.type, source.type)):
        diff.changed.append(Changed(path, "type", target.type, source.type))
        target.type = source.type
    _fill_description(target, source, path, diff)
    # Lo escrito a mano manda: la fuente solo llena lo que está vacío.
    if not target.synonyms and source.synonyms:
        diff.changed.append(Changed(path, "synonyms", None, ", ".join(source.synonyms)))
        target.synonyms = list(source.synonyms)
    if target.role == "other" and source.role != "other":
        diff.changed.append(Changed(path, "role", target.role, source.role))
        target.role = source.role
    if not target.sample_values and source.sample_values:
        diff.changed.append(
            Changed(path, "sample_values", None, ", ".join(str(v) for v in source.sample_values))
        )
        target.sample_values = list(source.sample_values)


def _merge_table(target: Table, source: Table, diff: Diff) -> None:
    _fill_description(target, source, target.name, diff)
    if not target.synonyms and source.synonyms:
        diff.changed.append(Changed(target.name, "synonyms", None, ", ".join(source.synonyms)))
        target.synonyms = list(source.synonyms)
    by_name = {c.name.casefold(): c for c in target.columns}
    found: set[str] = set()
    for column in source.columns:
        path = f"{target.name}.{column.name}"
        existing = by_name.get(column.name.casefold())
        found.add(column.name.casefold())
        if existing is None:
            diff.added.append(Added(path, "column"))
            target.columns.append(column.model_copy(deep=True))
        else:
            _merge_column(existing, column, path, diff)
    for column in target.columns:
        if column.name.casefold() not in found:
            diff.missing.append(Missing(f"{target.name}.{column.name}", "column"))
    # La llave primaria se completa al final, cuando ya están las columnas nuevas.
    if not target.primary_key and source.primary_key:
        names = {c.name for c in target.columns}
        if all(name in names for name in source.primary_key):
            diff.changed.append(
                Changed(target.name, "primary_key", None, ", ".join(source.primary_key))
            )
            target.primary_key = list(source.primary_key)


def _relation_key(rel: Relationship) -> frozenset[str]:
    return frozenset((rel.from_.casefold(), rel.to.casefold()))


def merge_import(existing: SemanticModel | None, imported: Imported, name: str) -> MergeResult:
    """Fusiona `imported` en una copia de `existing` (o crea un modelo `name` si no hay).

    Lanza `SemanticModelError` si el resultado no es válido.
    """
    base = existing.model_copy(deep=True) if existing else SemanticModel(version=1, name=name)
    diff = Diff()
    warnings = list(imported.warnings)

    tables = {t.name.casefold(): t for t in base.tables}
    found: set[str] = set()
    for source in imported.tables:
        key = source.name.casefold()
        found.add(key)
        target = tables.get(key)
        if target is None:
            diff.added.append(Added(source.name, "table"))
            for column in source.columns:
                diff.added.append(Added(f"{source.name}.{column.name}", "column"))
            copy = source.model_copy(deep=True)
            base.tables.append(copy)
            tables[key] = copy
        else:
            _merge_table(target, source, diff)
    for table in base.tables:
        if table.name.casefold() not in found:
            diff.missing.append(Missing(table.name, "table"))

    known = {_relation_key(r) for r in base.relationships}
    for rel in imported.relationships:
        if _relation_key(rel) not in known:
            known.add(_relation_key(rel))
            base.relationships.append(rel.model_copy(deep=True))
            diff.added.append(Added(f"{rel.from_} -> {rel.to}", "relationship"))

    # Revalida el resultado completo: un modelo fusionado inválido no debe llegar a la vista previa.
    model = parse_semantic_model(dump_model(base))
    return MergeResult(model=model, diff=diff, warnings=warnings)
