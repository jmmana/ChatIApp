"""Proveedor simulado (`kind: fake`): determinista y sin red, para las pruebas del agente.

Se configura con `config`:

- `responses`: lista de textos que se devuelven en orden (cíclica). Sin ella, responde
  `"respuesta simulada"`.
- `error`: nombre de un tipo de error de la pasarela; toda llamada falla con él.
- `fail_first`: cantidad de llamadas que fallan con `error` antes de empezar a responder.

Los tokens se cuentan por palabras y el costo es cero, así que el uso también es reproducible.
"""

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

FAKE_KIND = "fake"
DEFAULT_RESPONSE = "respuesta simulada"


@dataclass
class FakeReply:
    text: str
    input_tokens: int
    output_tokens: int


@dataclass
class FakeProvider:
    """Estado de una instancia simulada; la pasarela crea una por llamada a `Gateway`."""

    responses: list[str] = field(default_factory=lambda: [DEFAULT_RESPONSE])
    error: str | None = None
    fail_first: int | None = None
    calls: int = 0

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "FakeProvider":
        responses = [str(r) for r in config.get("responses") or []] or [DEFAULT_RESPONSE]
        fail_first = config.get("fail_first")
        return cls(
            responses=responses,
            error=config.get("error"),
            fail_first=int(fail_first) if fail_first is not None else None,
        )

    def reply(self, messages: list[dict[str, str]]) -> FakeReply:
        """Siguiente respuesta; lanza `GatewayError` si está configurado para fallar."""
        from app.llm.gateway import ERROR_KINDS, ErrorKind, GatewayError

        index = self.calls
        self.calls += 1
        if self.error is not None and (self.fail_first is None or index < self.fail_first):
            kind: ErrorKind = next((k for k in ERROR_KINDS if k == self.error), "provider_error")
            raise GatewayError(kind, "Error simulado.")
        text = self.responses[index % len(self.responses)]
        prompt = " ".join(m.get("content", "") for m in messages)
        return FakeReply(text, len(prompt.split()), len(text.split()))

    def stream(self, messages: list[dict[str, str]]) -> tuple[Iterator[str], FakeReply]:
        """Trozos de la respuesta (una palabra por trozo) y la respuesta completa."""
        reply = self.reply(messages)
        words = reply.text.split(" ")
        chunks = (w if i == len(words) - 1 else w + " " for i, w in enumerate(words))
        return chunks, reply
