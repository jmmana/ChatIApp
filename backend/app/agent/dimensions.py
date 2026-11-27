"""Dimensiones que la pregunta no pide (docs/FLUJO_CONVERSACIONAL.md#el-plan).

Una IA pequeña tiende a agregar dimensiones («sucursal», «canal») a preguntas de total. Aquí se
decide de forma determinista, con los nombres y sinónimos del modelo semántico, cuáles de las
dimensiones del plan nombra realmente el texto de la pregunta.
"""

import re
from collections.abc import Sequence

from app.engine.catalog import Catalog, CatalogError, normalize
from app.semantic.schema import Metric

_WORD = re.compile(r"\w+")


def _forms(word: str) -> frozenset[str]:
    """Singular y plural plausibles de una palabra: «sucursales» ~ «sucursal»."""
    forms = {word}
    if word.endswith("es") and len(word) > 4:
        forms.add(word[:-2])
    if word.endswith("s") and len(word) > 3:
        forms.add(word[:-1])
    return frozenset(forms)


def _tokens(text: str) -> list[frozenset[str]]:
    return [_forms(word) for word in _WORD.findall(normalize(text))]


def _mentions(question: list[frozenset[str]], term: str) -> bool:
    wanted = _tokens(term)
    if not wanted:
        return False
    for start in range(len(question) - len(wanted) + 1):
        window = question[start : start + len(wanted)]
        if all(a & b for a, b in zip(window, wanted, strict=True)):
            return True
    return False


def _metric_terms(metric: Metric) -> set[str]:
    return {normalize(t) for t in [metric.name, metric.label, *metric.synonyms]}


def unrequested_dimensions(
    catalog: Catalog,
    metric_name: str,
    dimensions: Sequence[str],
    question: str,
    keep: Sequence[str] = (),
) -> list[str]:
    """Dimensiones del plan cuyo nombre o sinónimo no aparece en la pregunta.

    Cuenta el nombre y los sinónimos de la columna y, si la columna es de otra tabla que la
    métrica, los de su tabla («por tienda» → `sucursales.nombre`); nunca los términos de la propia
    métrica («ventas»). `keep` son dimensiones heredadas del último plan (preguntas de
    seguimiento): no se descartan. Lo que no se pueda resolver se deja para `Catalog.verify`.
    """
    try:
        metric = catalog.find_metric(metric_name)
    except CatalogError:
        return []
    words = _tokens(question)
    own_terms = _metric_terms(metric)
    removed: list[str] = []
    for dimension in dimensions:
        found = catalog.find_column(metric, dimension)
        if found is None or dimension in keep:
            continue
        table, column = found
        terms = [column.name, *column.synonyms]
        if table.name != metric.table:
            terms += [table.name, *table.synonyms]
        if not any(normalize(term) not in own_terms and _mentions(words, term) for term in terms):
            removed.append(dimension)
    return removed
