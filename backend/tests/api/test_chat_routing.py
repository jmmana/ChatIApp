"""El chat usa el enrutamiento por tarea y el respaldo entre proveedores (`load_router`)."""

import json
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Provider

from .test_chat_stream import (  # noqa: F401 (fixtures de pytest)
    ESTE_MES,
    GENERAL,
    Sse,
    client,
    datasource_id,
    factory,
    fixed_now,
    user_id,
)


def _proveedor(
    factory: sessionmaker[Session],  # noqa: F811
    name: str,
    *,
    default: bool,
    params: dict[str, Any] | None = None,
    **config: Any,
) -> str:
    with factory() as session:
        provider = Provider(
            name=name,
            kind="fake",
            model="fake-1",
            config=config,
            params=params or {},
            is_default=default,
        )
        session.add(provider)
        session.commit()
        return str(provider.id)


def _chat(client: TestClient, ds_id: str, **extra: Any) -> Sse:  # noqa: F811
    body = {"datasource_id": ds_id, "message": "¿Cuánto vendí este mes?", "view_as": GENERAL}
    return Sse(client.post("/api/v1/chat/stream", json={**body, **extra}).text)


def test_si_el_predeterminado_falla_responde_el_respaldo_con_aviso(
    client: TestClient,  # noqa: F811
    factory: sessionmaker[Session],  # noqa: F811
    datasource_id: str,  # noqa: F811
) -> None:
    _proveedor(factory, "principal", default=True, error="quota")
    _proveedor(
        factory,
        "respaldo",
        default=False,
        params={"fallback": 0},
        responses=[json.dumps(ESTE_MES)],
    )

    flujo = _chat(client, datasource_id)

    assert "error" not in flujo.types
    assert "answer" in flujo.types and flujo.types[-1] == "turn.completed"
    avisos = [d for name, d in flujo.events if name == "step" and d["status"] == "warning"]
    assert any("principal no respondió; usé respaldo" in (d.get("detail") or "") for d in avisos)


def test_sin_respaldo_el_error_llega_como_evento_error(
    client: TestClient,  # noqa: F811
    factory: sessionmaker[Session],  # noqa: F811
    datasource_id: str,  # noqa: F811
) -> None:
    _proveedor(factory, "principal", default=True, error="quota")

    flujo = _chat(client, datasource_id)

    assert "error" in flujo.types
    assert "answer" not in flujo.types


def test_el_proveedor_elegido_por_el_administrador_manda_sobre_las_tareas(
    client: TestClient,  # noqa: F811
    factory: sessionmaker[Session],  # noqa: F811
    datasource_id: str,  # noqa: F811
) -> None:
    _proveedor(factory, "asignado", default=True, params={"tasks": ["planner"]}, error="auth")
    elegido = _proveedor(factory, "elegido", default=False, responses=[json.dumps(ESTE_MES)])

    flujo = _chat(client, datasource_id, provider_override=elegido)

    assert "error" not in flujo.types
    assert "answer" in flujo.types
