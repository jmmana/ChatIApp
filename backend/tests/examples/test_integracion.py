"""E2E de `examples/integracion/`: la app anfitriona contra ChatIApp con la demo (en memoria).

El navegador de cada usuario es un `TestClient` de la app anfitriona; su servidor habla con
ChatIApp por un transporte que reenvía las peticiones a la aplicación en proceso.
"""

import importlib.util
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ApiKey
from app.integrations.api_keys import parse_api_key, revoke_api_key
from app.main import API_PREFIX

from ..api.test_chat_stream import Sse
from ..integrations.test_embed_sessions import (  # noqa: F401 (fixtures de pytest)
    ORIGIN,
    _auth,
    _entorno,
    _key,
    client,
    datasources,
    demo_url,
    factory,
    session,
)

EXAMPLE = Path(__file__).parents[3] / "examples" / "integracion" / "app.py"
CHATIAPP = "http://chatiapp.test"
HostApp = tuple[Callable[[str], TestClient], str]


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("integracion_app", EXAMPLE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _bridge(chatiapp: TestClient) -> httpx.MockTransport:
    """Transporte que entrega las llamadas servidor a servidor a ChatIApp en proceso."""

    def handler(request: httpx.Request) -> httpx.Response:
        headers = {k: v for k, v in request.headers.items() if k not in ("host", "content-length")}
        r = chatiapp.request(
            request.method, request.url.path, content=request.content, headers=headers
        )
        return httpx.Response(
            r.status_code, content=r.content, headers={"content-type": r.headers["content-type"]}
        )

    return httpx.MockTransport(handler)


@pytest.fixture
def host_app(
    client: TestClient,  # noqa: F811
    session: Session,  # noqa: F811
) -> HostApp:
    """Devuelve (navegador de un usuario con sesión iniciada, API key de servidor)."""
    module = _load()
    _, secret = _key(session, allowed_roles=["gerente_sucursal"])
    settings = module.Settings(
        chatiapp_url=CHATIAPP,
        public_url=CHATIAPP,
        api_key=secret,
        datasource="ventas",
        origin=ORIGIN,
    )
    application = module.create_app(settings, transport=_bridge(client))

    def browser(username: str) -> TestClient:
        navegador = TestClient(application)
        entrada = navegador.post(
            "/login",
            content=f"username={username}&password=clave-{username}-1234",
            headers={"content-type": "application/x-www-form-urlencoded"},
            follow_redirects=False,
        )
        assert entrada.status_code == 303
        return navegador

    return browser, secret


def _preguntar(chatiapp: TestClient, token: str) -> Any:
    response = chatiapp.post(
        f"{API_PREFIX}/chat/stream",
        json={"datasource_id": "ventas", "message": "ventas por sucursal"},
        headers=_auth(token),
    )
    assert response.status_code == 200, response.text
    return response


def test_la_pagina_embebe_el_widget_y_pide_el_token_a_su_backend(host_app: HostApp) -> None:
    browser, _ = host_app
    pagina = browser("ana").get("/").text
    assert f"{CHATIAPP}/embed/v1/chatiapp.js" in pagina
    assert "<chatiapp-chat" in pagina and "/chatiapp-token" in pagina


def test_sin_sesion_no_hay_token_ni_chat(host_app: HostApp) -> None:
    browser, _ = host_app
    anonimo = browser("ana")
    anonimo.post("/logout")
    anonimo.cookies.clear()
    assert anonimo.post("/chatiapp-token").status_code == 401
    assert "<chatiapp-chat" not in anonimo.get("/").text


def test_dos_usuarios_de_sucursales_distintas_ven_resultados_distintos(
    host_app: HostApp,
    client: TestClient,  # noqa: F811
) -> None:
    browser, _ = host_app
    vistos: dict[str, Sse] = {}
    for usuario in ("ana", "bruno"):
        token = browser(usuario).post("/chatiapp-token").json()["token"]
        vistos[usuario] = Sse(_preguntar(client, token).text)

    filas = {u: sse.first("result")["rows"] for u, sse in vistos.items()}
    assert len(filas["ana"]) == 1 and len(filas["bruno"]) == 1
    assert filas["ana"] != filas["bruno"]
    filtros = {u: sse.first("sql")["filters_applied"] for u, sse in vistos.items()}
    for aplicados in filtros.values():
        assert any("sucursal_id IN" in f for f in aplicados)


def test_la_api_key_no_aparece_en_ningun_recurso_que_recibe_el_navegador(
    host_app: HostApp,
    client: TestClient,  # noqa: F811
) -> None:
    browser, secret = host_app
    ana = browser("ana")
    pagina = ana.get("/")
    emision = ana.post("/chatiapp-token")
    stream = _preguntar(client, emision.json()["token"])
    respuestas = [(r.text, dict(r.headers)) for r in (pagina, emision, stream)]
    recibido = str([*respuestas, dict(ana.cookies)])

    parsed = parse_api_key(secret)
    assert parsed is not None
    assert secret not in recibido
    assert parsed[1] not in recibido


def test_un_rechazo_de_chatiapp_no_se_reenvia_al_navegador(
    host_app: HostApp,
    session: Session,  # noqa: F811
) -> None:
    browser, secret = host_app
    revoke_api_key(session, session.scalars(select(ApiKey)).one().id)
    respuesta = browser("ana").post("/chatiapp-token")
    assert respuesta.status_code == 502
    assert secret not in respuesta.text
