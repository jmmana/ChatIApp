"""Los ejemplos de docs/INTEGRACION.md contra una instancia real con la demo.

Se omite si no hay instancia. Para correrla: levanta ChatIApp con la demo y el proveedor
simulado, crea una API key con alcance `chat` para la fuente `ventas` y exporta
`CHATIAPP_DEMO_URL` y `CHATIAPP_DEMO_API_KEY`.
"""

import os

import pytest

from chatiapp import ChatIApp, EndUser, TurnCompletedEvent

URL = os.environ.get("CHATIAPP_DEMO_URL")
KEY = os.environ.get("CHATIAPP_DEMO_API_KEY")

pytestmark = pytest.mark.skipif(not (URL and KEY), reason="no hay una instancia de la demo")


def test_chat_y_aclaracion() -> None:
    assert URL and KEY
    client = ChatIApp(base_url=URL, api_key=KEY)
    user = EndUser(id="u-123", role=os.environ.get("CHATIAPP_DEMO_ROLE"))
    turn = client.chat("¿Cuánto vendí?", datasource="ventas", user=user)
    if turn.needs_clarification:
        turn = client.chat("Este mes", conversation_id=turn.conversation_id, user=user)
    assert turn.status in ("answered", "rejected")


def test_streaming() -> None:
    assert URL and KEY
    client = ChatIApp(base_url=URL, api_key=KEY)
    user = EndUser(id="u-123", role=os.environ.get("CHATIAPP_DEMO_ROLE"))
    events = list(client.chat_stream("¿Cuánto vendí este mes?", datasource="ventas", user=user))
    assert isinstance(events[-1], TurnCompletedEvent) or events[-1].type == "error"
