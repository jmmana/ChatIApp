"""Cliente síncrono de ChatIApp: chat, streaming y tokens de sesión del chat embebido."""

from collections.abc import Iterator, Mapping
from types import TracebackType
from typing import Any

import httpx

from ._generated import CancelOut, EmbedSessionOut, EndUser
from .errors import error_from_response
from .events import StreamEvent, TurnStartedEvent, parse_sse
from .models import Turn

API_PREFIX = "/api/v1"
DEFAULT_TIMEOUT = 120.0  # un turno sin streaming puede tardar; el servidor corta con 504


class ChatIApp:
    """Cliente de la API de ChatIApp con una API key de servidor.

    La API key es una credencial de servidor: nunca la uses en un navegador ni en una app móvil.
    Para el chat embebido, emite tokens con `create_embed_session`.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        datasource: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._datasource = datasource
        self._owns_client = http_client is None
        self._http = http_client or httpx.Client(timeout=timeout)
        self._base_url = base_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {api_key}"}
        # Las respuestas siguientes de una conversación no repiten la fuente.
        self._conversations: dict[str, str] = {}

    # ------------------------------------------------------------------ ciclo de vida

    def close(self) -> None:
        if self._owns_client:
            self._http.close()

    def __enter__(self) -> "ChatIApp":  # noqa: PYI034 (typing.Self exige Python 3.11; se admite 3.10)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    # ------------------------------------------------------------------ chat

    def chat(
        self,
        message: str,
        *,
        datasource: str | None = None,
        user: EndUser | Mapping[str, Any],
        conversation_id: str | None = None,
    ) -> Turn:
        """Un turno sin streaming. Si falta un dato, `turn.needs_clarification` es verdadero."""
        body = self._chat_body(message, datasource, user, conversation_id)
        response = self._http.post(self._url("/chat"), json=body, headers=self._headers)
        data = self._json(response)
        turn = Turn.model_validate(data)
        self._conversations[turn.conversation_id] = body["datasource_id"]
        return turn

    def chat_stream(
        self,
        message: str,
        *,
        datasource: str | None = None,
        user: EndUser | Mapping[str, Any],
        conversation_id: str | None = None,
    ) -> Iterator[StreamEvent]:
        """Un turno por SSE: emite los eventos tipados a medida que llegan."""
        body = self._chat_body(message, datasource, user, conversation_id)
        with self._http.stream(
            "POST",
            self._url("/chat/stream"),
            json=body,
            headers={**self._headers, "Accept": "text/event-stream"},
        ) as response:
            if response.status_code >= 400:
                response.read()
                raise error_from_response(response.status_code, _try_json(response))
            for event in parse_sse(response.iter_lines()):
                if isinstance(event, TurnStartedEvent):
                    self._conversations[event.data.conversation_id] = body["datasource_id"]
                yield event

    def cancel(self, turn_id: str) -> CancelOut:
        """Cancela un turno en curso (el de `turn.started`)."""
        response = self._http.post(self._url(f"/chat/{turn_id}/cancel"), headers=self._headers)
        return CancelOut.model_validate(self._json(response))

    # ------------------------------------------------------------------ chat embebido

    def create_embed_session(
        self,
        *,
        datasource: str | None = None,
        origin: str,
        user: EndUser | Mapping[str, Any],
        ttl_seconds: int | None = None,
    ) -> EmbedSessionOut:
        """Cambia la API key por un token de sesión de corta vida para el widget del navegador.

        Llámalo desde tu backend y devuelve solo `session.token` al frontend.
        """
        body: dict[str, Any] = {
            "datasource": self._resolve_datasource(datasource, None),
            "origin": origin,
            "user": _user_json(user),
        }
        if ttl_seconds is not None:
            body["ttl_seconds"] = ttl_seconds
        response = self._http.post(self._url("/embed/sessions"), json=body, headers=self._headers)
        return EmbedSessionOut.model_validate(self._json(response))

    # ------------------------------------------------------------------ interno

    def _url(self, path: str) -> str:
        return f"{self._base_url}{API_PREFIX}{path}"

    def _resolve_datasource(self, datasource: str | None, conversation_id: str | None) -> str:
        resolved = datasource
        if resolved is None and conversation_id is not None:
            resolved = self._conversations.get(conversation_id)
        resolved = resolved or self._datasource
        if resolved is None:
            raise ValueError("Indica `datasource` (o configúralo en el constructor).")
        return resolved

    def _chat_body(
        self,
        message: str,
        datasource: str | None,
        user: EndUser | Mapping[str, Any],
        conversation_id: str | None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "datasource_id": self._resolve_datasource(datasource, conversation_id),
            "message": message,
            "user": _user_json(user),
        }
        if conversation_id is not None:
            body["conversation_id"] = conversation_id
        return body

    def _json(self, response: httpx.Response) -> Any:
        data = _try_json(response)
        if response.status_code >= 400:
            raise error_from_response(response.status_code, data)
        return data


def _try_json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return None


def _user_json(user: EndUser | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(user, EndUser):
        return user.model_dump(mode="json", exclude_none=True)
    return dict(user)
