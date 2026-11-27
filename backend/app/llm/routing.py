"""Enrutamiento por tarea y respaldo entre proveedores (docs/PROVEEDORES_IA.md).

Cada tarea (`planner`, `sql`, `answer`, `suggest`) usa el proveedor que se le asignó; sin
asignación, el predeterminado. Si ese proveedor falla por `auth`, `quota`, `timeout`, `network` o
`provider_error`, se prueba el siguiente de la cadena de respaldo y se deja un aviso («Claude no
respondió; usé DeepSeek») que el orquestador emite como `step` con `status: warning`. Un JSON
inválido del modelo (`InvalidJsonError`) nunca dispara el respaldo, ni un `model_not_found`:
son errores de la petición o de la configuración, no del proveedor.
"""

from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Provider
from app.llm.gateway import (
    Completion,
    ErrorKind,
    Gateway,
    GatewayError,
    InvalidJsonError,
    JsonCompletion,
    ProviderConfig,
    StreamEvent,
)

Task = Literal["planner", "sql", "answer", "suggest"]
TASKS: tuple[Task, ...] = ("planner", "sql", "answer", "suggest")

FALLBACK_KINDS: frozenset[ErrorKind] = frozenset(
    {"auth", "quota", "timeout", "network", "provider_error"}
)


class LlmClient(Protocol):
    """Lo que el agente necesita de la IA; la cumplen `Gateway` y `TaskGateway`."""

    def complete(self, messages: list[dict[str, str]], **params: Any) -> Completion: ...

    def complete_json[T: BaseModel](
        self, messages: list[dict[str, str]], schema: type[T], **params: Any
    ) -> JsonCompletion[T]: ...

    def stream(self, messages: list[dict[str, str]], **params: Any) -> Iterator[StreamEvent]: ...


@dataclass(frozen=True)
class Candidate:
    """Un proveedor de la cadena: su nombre visible y su pasarela."""

    name: str
    gateway: Gateway


def should_fallback(exc: GatewayError) -> bool:
    """`True` si el error es del proveedor y tiene sentido probar con otro."""
    return not isinstance(exc, InvalidJsonError) and exc.kind in FALLBACK_KINDS


class TaskGateway:
    """Pasarela de una tarea: recorre la cadena y acumula los avisos de respaldo."""

    def __init__(self, chain: Sequence[Candidate]) -> None:
        self.chain = list(chain)
        self.notices: list[str] = []

    def take_notices(self) -> list[str]:
        """Devuelve y vacía los avisos de respaldo acumulados."""
        notices, self.notices = self.notices, []
        return notices

    def complete(self, messages: list[dict[str, str]], **params: Any) -> Completion:
        return self._run(lambda gw: gw.complete(messages, **params))

    def complete_json[T: BaseModel](
        self, messages: list[dict[str, str]], schema: type[T], **params: Any
    ) -> JsonCompletion[T]:
        return self._run(lambda gw: gw.complete_json(messages, schema, **params))

    def stream(self, messages: list[dict[str, str]], **params: Any) -> Iterator[StreamEvent]:
        """Respalda solo si el proveedor falla antes de emitir texto: no se mezclan respuestas."""
        if not self.chain:
            raise _no_provider()
        for index, candidate in enumerate(self.chain):
            started = False
            try:
                for event in candidate.gateway.stream(messages, **params):
                    started = started or bool(event.delta)
                    yield event
                return
            except GatewayError as exc:
                if started or not self._advance(index, exc):
                    raise

    def _run[R](self, call: Callable[[Gateway], R]) -> R:
        if not self.chain:
            raise _no_provider()
        for index, candidate in enumerate(self.chain):
            try:
                return call(candidate.gateway)
            except GatewayError as exc:
                if not self._advance(index, exc):
                    raise
        raise _no_provider()  # inalcanzable: el último error se relanza arriba

    def _advance(self, index: int, exc: GatewayError) -> bool:
        """Anota el aviso y devuelve `True` si hay otro proveedor al que pasar."""
        if not should_fallback(exc) or index + 1 >= len(self.chain):
            return False
        failed, nxt = self.chain[index].name, self.chain[index + 1].name
        self.notices.append(f"{failed} no respondió; usé {nxt}")
        return True


def _no_provider() -> GatewayError:
    return GatewayError("provider_error", "No hay un proveedor de IA configurado.")


class Router:
    """Cadenas por tarea: proveedor asignado (o el predeterminado) y luego el respaldo."""

    def __init__(
        self,
        tasks: dict[Task, Candidate],
        default: Candidate | None = None,
        fallback: Sequence[Candidate] = (),
    ) -> None:
        self.tasks = dict(tasks)
        self.default = default
        self.fallback = list(fallback)

    def chain(self, task: Task) -> list[Candidate]:
        """Cadena de la tarea, sin repetir proveedores."""
        first = self.tasks.get(task) or self.default
        ordered = ([first] if first is not None else []) + self.fallback
        seen: set[str] = set()
        chain: list[Candidate] = []
        for candidate in ordered:
            if candidate.name not in seen:
                seen.add(candidate.name)
                chain.append(candidate)
        return chain

    def for_task(self, task: Task) -> TaskGateway:
        """Pasarela nueva (con sus propios avisos) para una tarea."""
        return TaskGateway(self.chain(task))


def load_router(
    session: Session, *, factory: Callable[[ProviderConfig], Gateway] = Gateway
) -> Router:
    """Arma el `Router` con la asignación guardada (API o `chatiapp.yaml`).

    Las tareas y el orden de respaldo viven en `params` de cada proveedor (`tasks` y `fallback`).
    """
    rows = list(session.scalars(select(Provider).order_by(Provider.name)).all())

    def candidate(provider: Provider) -> Candidate:
        return Candidate(provider.name, factory(ProviderConfig.from_provider(provider)))

    tasks: dict[Task, Candidate] = {}
    for provider in rows:
        for task in (provider.params or {}).get("tasks", []):
            if task in TASKS:
                tasks.setdefault(task, candidate(provider))
    default = next((candidate(p) for p in rows if p.is_default), None)
    ordered = sorted(
        (p for p in rows if "fallback" in (p.params or {})),
        key=lambda p: (p.params["fallback"], p.name),
    )
    return Router(tasks, default, [candidate(p) for p in ordered])
