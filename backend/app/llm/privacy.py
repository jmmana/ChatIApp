"""Niveles de privacidad hacia el proveedor de IA (docs/SEGURIDAD.md#qué-ve-el-modelo-de-ia).

El nivel de la fuente (`datasource.privacy`) es el máximo que fija el administrador. El
interceptor `PrivacyGateway` envuelve la pasarela de una tarea y, antes de cada llamada:

1. clasifica en categorías lo que el prompt lleva (`schema`, `result_rows`, `sample_values`);
2. rechaza la llamada con `PrivacyViolation` si alguna categoría excede el nivel, sin que el
   proveedor reciba nada;
3. registra en `PrivacyLog` las categorías y el contenido exacto de cada llamada permitida.

Es la última barrera: los constructores de prompt ya filtran por nivel, y esto garantiza que un
error en ellos no filtre datos. La clasificación se apoya en las marcas que esos constructores
escriben (`{valores: …}` y las líneas `Fila:` dentro de `<resultado>`).
"""

import logging
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, Literal, cast, get_args

from pydantic import BaseModel

from app.llm.gateway import Completion, GatewayError, JsonCompletion, StreamEvent
from app.llm.routing import LlmClient, Task
from app.semantic.context import Privacy

logger = logging.getLogger(__name__)

LEVELS: tuple[Privacy, ...] = get_args(Privacy)
DEFAULT_LEVEL: Privacy = "schema"

Category = Literal["question", "schema", "result_rows", "sample_values"]

# Categorías que cada nivel permite (acumulativas, como en la tabla de SEGURIDAD.md).
ALLOWED: dict[Privacy, frozenset[Category]] = {
    "schema": frozenset({"question", "schema"}),
    "aggregates": frozenset({"question", "schema", "result_rows"}),
    "samples": frozenset({"question", "schema", "result_rows", "sample_values"}),
}

_SCHEMA_MARKERS = ("<modelo_semantico>", "<modelo>")
_SAMPLES = re.compile(r"\{valores: ")
_ROWS = re.compile(r"<resultado>.*?^Fila: ", re.DOTALL | re.MULTILINE)


class PrivacyViolation(GatewayError):
    """La llamada llevaba datos que el nivel de la fuente no permite; no salió nada.

    Es un `GatewayError`: el agente ya sabe degradar (plantilla, aviso) ante esos errores.
    """

    def __init__(self, task: str, level: Privacy, categories: frozenset[Category]) -> None:
        names = ", ".join(sorted(categories))
        super().__init__(
            "provider_error",
            f"La tarea «{task}» intentó enviar al proveedor de IA datos no permitidos "
            f"con la privacidad «{level}»: {names}.",
        )
        self.task = task
        self.level = level
        self.categories = categories


def parse_level(value: object) -> Privacy:
    """Nivel válido; cualquier otro valor cae en el más restrictivo (`schema`)."""
    return value if value in LEVELS else DEFAULT_LEVEL


def effective_level(requested: Privacy, maximum: Privacy) -> Privacy:
    """El nivel pedido, recortado al máximo del administrador."""
    return LEVELS[min(LEVELS.index(requested), LEVELS.index(maximum))]


def classify(messages: list[dict[str, str]]) -> frozenset[Category]:
    """Categorías de datos que lleva un prompt. La pregunta va siempre."""
    text = "\n".join(m.get("content", "") for m in messages)
    found: set[Category] = {"question"}
    if any(marker in text for marker in _SCHEMA_MARKERS):
        found.add("schema")
    if _ROWS.search(text):
        found.add("result_rows")
    if _SAMPLES.search(text):
        found.add("sample_values")
    return frozenset(found)


@dataclass(frozen=True)
class Disclosure:
    """Una llamada al proveedor: tarea, nivel, categorías y el contenido exacto enviado."""

    task: str
    level: Privacy
    categories: frozenset[Category]
    messages: tuple[tuple[str, str], ...]


@dataclass
class PrivacyLog:
    """Registro de lo que salió hacia el proveedor en un turno."""

    entries: list[Disclosure] = field(default_factory=list)

    def categories(self) -> frozenset[Category]:
        return frozenset(c for e in self.entries for c in e.categories)


class PrivacyGateway:
    """Cumple `LlmClient`: verifica y registra cada llamada antes de delegar en `inner`."""

    def __init__(
        self, inner: LlmClient, task: Task | str, level: Privacy, log: PrivacyLog | None = None
    ) -> None:
        self.inner = inner
        self.task = task
        self.level = level
        self.log = log if log is not None else PrivacyLog()

    def take_notices(self) -> list[str]:
        """Avisos de respaldo de la pasarela envuelta (vacío si no los tiene)."""
        take = getattr(self.inner, "take_notices", None)
        return cast(list[str], take()) if callable(take) else []

    def complete(self, messages: list[dict[str, str]], **params: Any) -> Completion:
        self._intercept(messages)
        return self.inner.complete(messages, **params)

    def complete_json[T: BaseModel](
        self, messages: list[dict[str, str]], schema: type[T], **params: Any
    ) -> JsonCompletion[T]:
        self._intercept(messages)
        return self.inner.complete_json(messages, schema, **params)

    def stream(self, messages: list[dict[str, str]], **params: Any) -> Iterator[StreamEvent]:
        self._intercept(messages)
        return self.inner.stream(messages, **params)

    def _intercept(self, messages: list[dict[str, str]]) -> None:
        categories = classify(messages)
        excess = categories - ALLOWED[self.level]
        if excess:
            logger.warning(
                "Llamada a IA bloqueada por privacidad: tarea=%s nivel=%s categorías=%s",
                self.task,
                self.level,
                ",".join(sorted(excess)),
            )
            raise PrivacyViolation(str(self.task), self.level, frozenset(excess))
        sent = tuple((m.get("role", ""), m.get("content", "")) for m in messages)
        self.log.entries.append(Disclosure(str(self.task), self.level, categories, sent))
        logger.info(
            "Llamada a IA: tarea=%s nivel=%s categorías=%s",
            self.task,
            self.level,
            ",".join(sorted(categories)),
        )
