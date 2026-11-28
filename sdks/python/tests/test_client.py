"""Pruebas del cliente con un servidor simulado (httpx.MockTransport), sin red."""

import json

import httpx
import pytest

from chatiapp import (
    AnswerDeltaEvent,
    ChatIApp,
    ChatIAppError,
    EndUser,
    ErrorEvent,
    SqlEvent,
    TurnCompletedEvent,
    TurnStartedEvent,
    UnknownEvent,
)
from chatiapp.events import parse_sse

BASE = "https://chatiapp.tuempresa.com"
KEY = "clave-de-prueba-1234"
USER = EndUser(id="u-123", role="gerente_sucursal", attributes={"sucursales": [1, 2]})

CLARIFICATION = {
    "conversation_id": "7d0c0000-0000-0000-0000-000000000001",
    "status": "needs_clarification",
    "reasoning": "Es la métrica ventas_netas. No mencionan período.",
    "clarification": {
        "question": "¿De qué período quieres ver las ventas?",
        "options": ["Hoy", "Esta semana", "Este mes"],
        "slot": "period",
    },
}
ANSWERED = {
    "conversation_id": "7d0c0000-0000-0000-0000-000000000001",
    "status": "answered",
    "period": {"start": "2026-11-01", "end_exclusive": "2026-12-01", "label": "Noviembre 2026"},
    "sql": {
        "sql": "SELECT SUM(total_ventas) AS ventas_netas FROM ventas_diarias",
        "dialect": "postgres",
        "origin": "catalog",
        "summary_table": "ventas_diarias",
        "filters_applied": ["ventas_diarias: sucursal_id IN (1, 2)"],
        "metric": "ventas_netas",
    },
    "result": {"columns": ["ventas_netas"], "rows": [["482315000.00"]], "truncated": False},
    "answer": "Este mes llevas $482,3 M en ventas netas.",
    "usage": {"tokens_in": 1830, "tokens_out": 142, "cost_usd": 0.0031},
}

SSE = (
    ": keep-alive\n\n"
    'event: turn.started\ndata: {"turn_id": "t1", "conversation_id": "c1"}\n\n'
    'event: answer.delta\ndata: {"text": "Este "}\n\n'
    'event: answer.delta\ndata: {"text": "mes"}\n\n'
    'event: sql\ndata: {"sql": "SELECT 1", "dialect": "sqlite", "origin": "catalog"}\n\n'
    'event: futuro\ndata: {"x": 1}\n\n'
    'event: turn.completed\ndata: {"usage": {"tokens_in": 1, "tokens_out": 2, "cost_usd": 0.0},'
    ' "elapsed_ms": 5}\n\n'
)


def make_client(
    handler: httpx.MockTransport | None = None, datasource: str | None = None
) -> tuple[ChatIApp, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        path = request.url.path
        body = json.loads(request.content) if request.content else {}
        if path == "/api/v1/chat":
            turn = ANSWERED if "conversation_id" in body else CLARIFICATION
            return httpx.Response(200, json=turn)
        if path == "/api/v1/chat/stream":
            return httpx.Response(200, text=SSE, headers={"content-type": "text/event-stream"})
        if path == "/api/v1/embed/sessions":
            return httpx.Response(200, json={"token": "tok", "expires_at": "2026-11-28T10:15:00Z"})
        if path.endswith("/cancel"):
            return httpx.Response(200, json={"turn_id": "t1", "status": "cancelled"})
        return httpx.Response(404, json={"error": {"code": "nope", "message": "no", "details": {}}})

    http = httpx.Client(transport=handler or httpx.MockTransport(respond))
    return ChatIApp(BASE, KEY, datasource=datasource, http_client=http), seen


def test_ejemplo_de_la_documentacion() -> None:
    client, seen = make_client()
    turn = client.chat("¿Cuánto vendí?", datasource="ventas", user=USER)
    assert turn.needs_clarification
    assert turn.clarification is not None and turn.clarification.slot == "period"
    turn = client.chat("Este mes", conversation_id=turn.conversation_id, user=USER)
    assert turn.answered
    assert turn.answer is not None and turn.sql is not None
    assert turn.sql.sql.startswith("SELECT") and turn.period is not None

    first, second = (json.loads(r.content) for r in seen)
    assert first["datasource_id"] == "ventas" and "conversation_id" not in first
    assert second["datasource_id"] == "ventas"  # recordada por la conversación
    assert second["conversation_id"] == CLARIFICATION["conversation_id"]
    assert first["user"] == {
        "id": "u-123",
        "role": "gerente_sucursal",
        "attributes": {"sucursales": [1, 2]},
    }
    assert seen[0].headers["authorization"] == f"Bearer {KEY}"
    assert str(seen[0].url) == f"{BASE}/api/v1/chat"


def test_sin_fuente_falla_antes_de_llamar() -> None:
    client, seen = make_client()
    with pytest.raises(ValueError):
        client.chat("hola", user=USER)
    assert seen == []


def test_fuente_por_defecto_y_usuario_como_diccionario() -> None:
    client, seen = make_client(datasource="ventas")
    client.chat("hola", user={"id": "u-1"})
    assert json.loads(seen[0].content)["datasource_id"] == "ventas"


def test_chat_stream_emite_eventos_tipados() -> None:
    client, seen = make_client()
    events = list(client.chat_stream("¿Cuánto vendí este mes?", datasource="ventas", user=USER))
    assert isinstance(events[0], TurnStartedEvent)
    deltas = [e.data.text for e in events if isinstance(e, AnswerDeltaEvent)]
    assert "".join(deltas) == "Este mes"
    assert any(isinstance(e, SqlEvent) and e.data.dialect == "sqlite" for e in events)
    assert any(isinstance(e, UnknownEvent) and e.type == "futuro" for e in events)
    assert isinstance(events[-1], TurnCompletedEvent)
    assert seen[0].headers["accept"] == "text/event-stream"


def test_chat_stream_recuerda_la_fuente_de_la_conversacion() -> None:
    client, seen = make_client()
    list(client.chat_stream("hola", datasource="ventas", user=USER))
    list(client.chat_stream("más", conversation_id="c1", user=USER))
    assert json.loads(seen[1].content)["datasource_id"] == "ventas"


def test_errores_http() -> None:
    def deny(_: httpx.Request) -> httpx.Response:
        error = {"code": "role_not_allowed", "message": "Rol no permitido", "details": {}}
        return httpx.Response(403, json={"error": error})

    client, _ = make_client(httpx.MockTransport(deny))
    with pytest.raises(ChatIAppError) as info:
        client.chat("hola", datasource="ventas", user=USER)
    assert info.value.status_code == 403 and info.value.code == "role_not_allowed"
    with pytest.raises(ChatIAppError) as info:
        list(client.chat_stream("hola", datasource="ventas", user=USER))
    assert info.value.code == "role_not_allowed"


def test_token_de_sesion_para_el_chat_embebido() -> None:
    client, seen = make_client()
    session = client.create_embed_session(
        datasource="ventas", origin="https://portal.tuempresa.com", user=USER, ttl_seconds=600
    )
    assert session.token == "tok"
    body = json.loads(seen[0].content)
    assert body["origin"] == "https://portal.tuempresa.com" and body["ttl_seconds"] == 600
    assert body["datasource"] == "ventas" and body["user"]["id"] == "u-123"
    assert str(seen[0].url) == f"{BASE}/api/v1/embed/sessions"


def test_cancelar() -> None:
    client, seen = make_client()
    assert client.cancel("t1").status == "cancelled"
    assert seen[0].url.path == "/api/v1/chat/t1/cancel"


def test_parse_sse_tolera_crlf_y_evento_incompleto() -> None:
    lines = ["event: error", 'data: {"code": "x", "message": "m", "recoverable": true}', ""]
    events = list(parse_sse(line + "\r" for line in lines))
    assert isinstance(events[0], ErrorEvent) and events[0].data.recoverable
    final = list(parse_sse(["event: answer", 'data: {"text": "hola"}']))  # sin línea en blanco
    assert final[0].type == "answer"
    malformed = list(parse_sse(["event: answer", 'data: {"nada": 1}', ""]))
    assert isinstance(malformed[0], UnknownEvent)
