"""`POST /chat/stream` con una API key de alcance `chat` (integraciones de servidor)."""

import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.api import chat
from app.db.models import Conversation
from app.integrations.api_keys import create_api_key
from app.main import app

from .test_chat_stream import (  # noqa: F401 (fixtures de pytest)
    Sse,
    _provider,
    client,
    datasource_id,
    factory,
    fixed_now,
    user_id,
)

POR_SUCURSAL = {
    "intent": "metric",
    "reasoning": "Ventas por sucursal.",
    "metric": "ventas_netas",
    "dimensions": ["sucursales.nombre"],
    "period_text": "este año",
}


@pytest.fixture(autouse=True)
def _autenticacion_real(client: TestClient) -> Iterator[None]:  # noqa: F811
    """Estas pruebas usan la API key de verdad: sin el override de sesión del fixture."""
    app.dependency_overrides.pop(chat.get_stream_caller, None)
    yield


def _key(sessions: sessionmaker[Session], **extra: Any) -> tuple[uuid.UUID, str]:
    options: dict[str, Any] = {"name": "app", "scopes": ["chat"], **extra}
    with sessions() as session:
        api_key, secret = create_api_key(session, **options)
        return api_key.id, secret


def _stream(http: TestClient, secret: str, ds_id: str, end_user: dict[str, Any]) -> Any:
    return http.post(
        "/api/v1/chat/stream",
        json={"datasource_id": ds_id, "message": "ventas por sucursal", "user": end_user},
        headers={"Authorization": f"Bearer {secret}"},
    )


def _gerente(external_id: str, sucursales: list[int]) -> dict[str, Any]:
    return {"id": external_id, "role": "gerente_sucursal", "attributes": {"sucursales": sucursales}}


def test_dos_usuarios_finales_con_sucursales_distintas_ven_resultados_distintos(
    client: TestClient,  # noqa: F811
    factory: sessionmaker[Session],  # noqa: F811
    datasource_id: str,  # noqa: F811
) -> None:
    _provider(factory, "por-sucursal", POR_SUCURSAL, default=True)
    key_id, secret = _key(factory, datasources=[datasource_id])

    primero = _stream(client, secret, datasource_id, _gerente("u-1", [1, 2]))
    segundo = _stream(client, secret, datasource_id, _gerente("u-2", [3]))

    assert primero.status_code == 200, primero.text
    assert segundo.status_code == 200, segundo.text
    a, b = Sse(primero.text), Sse(segundo.text)
    assert "error" not in a.types and "error" not in b.types
    filas_a, filas_b = a.first("result")["rows"], b.first("result")["rows"]
    assert len(filas_a) == 2
    assert len(filas_b) == 1
    assert {fila[0] for fila in filas_a}.isdisjoint({fila[0] for fila in filas_b})
    # La API key nunca viaja en los eventos.
    assert secret not in primero.text and secret not in segundo.text
    # Las conversaciones quedan ligadas a la key y al `user.id`, no a un usuario de sesión.
    with factory() as session:
        conversaciones = session.scalars(select(Conversation)).all()
    assert {(c.api_key_id, c.external_user_id, c.user_id) for c in conversaciones} == {
        (key_id, "u-1", None),
        (key_id, "u-2", None),
    }


def test_la_fuente_fuera_de_la_key_responde_403(
    client: TestClient,  # noqa: F811
    factory: sessionmaker[Session],  # noqa: F811
    datasource_id: str,  # noqa: F811
) -> None:
    _provider(factory, "por-sucursal", POR_SUCURSAL, default=True)
    _, secret = _key(factory, datasources=[str(uuid.uuid4())])

    response = _stream(client, secret, datasource_id, _gerente("u-1", [1]))

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "datasource_not_allowed"


def test_un_rol_fuera_de_los_permitidos_responde_403(
    client: TestClient,  # noqa: F811
    factory: sessionmaker[Session],  # noqa: F811
    datasource_id: str,  # noqa: F811
) -> None:
    _provider(factory, "por-sucursal", POR_SUCURSAL, default=True)
    _, secret = _key(factory, datasources=[datasource_id], allowed_roles=["gerente_sucursal"])

    response = _stream(client, secret, datasource_id, {"id": "u-1", "role": "gerencia_general"})

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "role_not_allowed"


def test_sin_rol_y_con_varios_roles_responde_422(
    client: TestClient,  # noqa: F811
    factory: sessionmaker[Session],  # noqa: F811
    datasource_id: str,  # noqa: F811
) -> None:
    _provider(factory, "por-sucursal", POR_SUCURSAL, default=True)
    _, secret = _key(factory, datasources=[datasource_id])

    response = _stream(client, secret, datasource_id, {"id": "u-1"})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "role_required"


def test_faltan_atributos_del_rol_responde_422(
    client: TestClient,  # noqa: F811
    factory: sessionmaker[Session],  # noqa: F811
    datasource_id: str,  # noqa: F811
) -> None:
    _provider(factory, "por-sucursal", POR_SUCURSAL, default=True)
    _, secret = _key(factory, datasources=[datasource_id])

    response = _stream(
        client, secret, datasource_id, {"id": "u-1", "role": "gerente_sucursal", "attributes": {}}
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "missing_attributes"


def test_una_key_sin_alcance_chat_responde_403(
    client: TestClient,  # noqa: F811
    factory: sessionmaker[Session],  # noqa: F811
    datasource_id: str,  # noqa: F811
) -> None:
    _, secret = _key(factory, scopes=["embed"], datasources=[datasource_id])

    response = _stream(client, secret, datasource_id, _gerente("u-1", [1]))

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "insufficient_scope"
