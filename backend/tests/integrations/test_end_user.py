import importlib
import json
import uuid
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.api.datasources import get_request_cipher
from app.db.models import ApiKey, Base, Conversation, Datasource, Provider, SemanticModelVersion
from app.db.session import get_session, make_engine
from app.demo.seed import generar
from app.engine.guard import guards
from app.integrations.api_keys import create_api_key
from app.integrations.end_user import EndUser, EndUserError, resolve_end_user
from app.main import create_app
from app.security.crypto import encrypt, make_cipher
from app.semantic.schema import SemanticModel, parse_semantic_model
from app.settings.registry import datasource_uuid

EXAMPLE = Path(__file__).parents[3] / "examples" / "ventas" / "semantic-model.yaml"
CIPHER = make_cipher("clave-de-prueba")
PLAN = {
    "intent": "metric",
    "reasoning": "Ventas netas por sucursal.",
    "metric": "ventas_netas",
    "dimensions": ["sucursales.nombre"],
    "period_text": "2026",
}


@pytest.fixture(autouse=True)
def _entorno(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHATIAPP_SECRET_KEY", "llave-de-prueba-" + "x" * 32)


@pytest.fixture(scope="module")
def model() -> SemanticModel:
    yaml = importlib.import_module("yaml")
    return parse_semantic_model(yaml.safe_load(EXAMPLE.read_text()))


@pytest.fixture(scope="module")
def demo_url(tmp_path_factory: pytest.TempPathFactory) -> str:
    path = tmp_path_factory.mktemp("demo") / "ventas.db"
    generar(path, seed=42, hasta=date(2026, 11, 25))
    return f"sqlite:///{path}"


@pytest.fixture
def factory(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    engine = make_engine(f"sqlite:///{tmp_path / 'app.db'}")
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, expire_on_commit=False)
    engine.dispose()


@pytest.fixture
def session(factory: sessionmaker[Session]) -> Iterator[Session]:
    with factory() as s:
        yield s


@pytest.fixture
def datasource(session: Session, model: SemanticModel, demo_url: str) -> Datasource:
    ds = Datasource(
        id=datasource_uuid("ventas"),
        name="ventas",
        dialect="sqlite",
        url_encrypted=encrypt(demo_url, CIPHER),
        execute=True,
        privacy="schema",
    )
    session.add(ds)
    session.flush()
    session.add(
        SemanticModelVersion(datasource_id=ds.id, version=1, model=model.model_dump(mode="json"))
    )
    session.add(
        Provider(
            name="simulado",
            kind="fake",
            model="fake-1",
            is_default=True,
            config={"responses": [json.dumps(PLAN), "Listo."]},
        )
    )
    session.commit()
    return ds


@pytest.fixture
def client(factory: sessionmaker[Session]) -> TestClient:
    application = create_app()

    def _session() -> Iterator[Session]:
        with factory() as s:
            yield s

    guards.clear()
    application.dependency_overrides[get_session] = _session
    application.dependency_overrides[get_request_cipher] = lambda: CIPHER
    return TestClient(application)


def _key(session: Session, **kwargs: Any) -> tuple[ApiKey, str]:
    options: dict[str, Any] = {
        "name": "app",
        "scopes": ["chat"],
        "datasources": ["ventas"],
        "allowed_roles": ["gerente_sucursal", "gerencia_general"],
    }
    return create_api_key(session, **{**options, **kwargs})


def _chat(client: TestClient, secret: str, user: dict[str, Any] | None, **extra: Any) -> Any:
    body: dict[str, Any] = {"datasource_id": "ventas", "message": "ventas por sucursal"}
    if user is not None:
        body["user"] = user
    return client.post(
        "/api/v1/chat",
        json={**body, **extra},
        headers={"Authorization": f"Bearer {secret}"},
    )


def _gerente(*sucursales: int) -> dict[str, Any]:
    return {
        "id": f"u-{sucursales[0]}",
        "role": "gerente_sucursal",
        "attributes": {"sucursales": list(sucursales)},
    }


# --- resolve_end_user ---------------------------------------------------------------------------


def test_sin_usuario_final_es_422(
    session: Session, datasource: Datasource, model: SemanticModel
) -> None:
    api_key, _ = _key(session)
    with pytest.raises(EndUserError) as exc:
        resolve_end_user(api_key, datasource, model, None)
    assert (exc.value.status_code, exc.value.code) == (422, "end_user_required")


def test_rol_fuera_de_los_permitidos_es_403(
    session: Session, datasource: Datasource, model: SemanticModel
) -> None:
    api_key, _ = _key(session, allowed_roles=["gerente_sucursal", "gerencia_general"])
    with pytest.raises(EndUserError) as exc:
        resolve_end_user(api_key, datasource, model, EndUser(id="u", role="analista"))
    assert (exc.value.status_code, exc.value.code) == (403, "role_not_allowed")


def test_con_rol_fijo_se_usa_ese_y_se_ignora_el_enviado(
    session: Session, datasource: Datasource, model: SemanticModel
) -> None:
    api_key, _ = _key(session, allowed_roles=["gerencia_general"])
    sent = EndUser(id="u-1", role="gerente_sucursal")
    for user in (EndUser(id="u-1"), sent):
        access = resolve_end_user(api_key, datasource, model, user)
        assert access.role == "gerencia_general"
        assert access.context == {"user": {}} and access.external_user_id == "u-1"


def test_sin_rol_y_sin_rol_fijo_es_422(
    session: Session, datasource: Datasource, model: SemanticModel
) -> None:
    api_key, _ = _key(session)
    with pytest.raises(EndUserError) as exc:
        resolve_end_user(api_key, datasource, model, EndUser(id="u-1"))
    assert (exc.value.status_code, exc.value.code) == (422, "role_required")


@pytest.mark.parametrize(
    ("attributes", "code"),
    [
        ({}, "missing_attributes"),
        ({"sucursales": []}, "missing_attributes"),
        ({"sucursales": 1}, "invalid_attributes"),
        ({"sucursales": "1,2"}, "invalid_attributes"),
    ],
)
def test_atributos_ausentes_o_de_tipo_incorrecto_son_422(
    session: Session,
    datasource: Datasource,
    model: SemanticModel,
    attributes: dict[str, Any],
    code: str,
) -> None:
    api_key, _ = _key(session)
    user = EndUser(id="u-1", role="gerente_sucursal", attributes=attributes)
    with pytest.raises(EndUserError) as exc:
        resolve_end_user(api_key, datasource, model, user)
    assert (exc.value.status_code, exc.value.code) == (422, code)


def test_solo_pasan_los_atributos_que_usa_el_rol(
    session: Session, datasource: Datasource, model: SemanticModel
) -> None:
    api_key, _ = _key(session)
    attributes = {"sucursales": [1, 2], "otro": "x"}
    user = EndUser(id="u-1", role="gerente_sucursal", attributes=attributes)
    access = resolve_end_user(api_key, datasource, model, user)
    assert access.context == {"user": {"sucursales": [1, 2]}}


def test_fuente_fuera_de_la_key_es_403(
    session: Session, datasource: Datasource, model: SemanticModel
) -> None:
    api_key, _ = _key(session, datasources=["otra"])
    with pytest.raises(EndUserError) as exc:
        resolve_end_user(api_key, datasource, model, EndUser(id="u", role="gerencia_general"))
    assert exc.value.status_code == 403


# --- API ----------------------------------------------------------------------------------------


def test_chat_con_key_sin_user_es_422_y_no_ejecuta(
    client: TestClient, session: Session, datasource: Datasource
) -> None:
    _, secret = _key(session)
    response = _chat(client, secret, None)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "end_user_required"
    assert session.scalars(select(Conversation)).all() == []


def test_chat_con_atributos_ausentes_es_422_sin_conversacion(
    client: TestClient, session: Session, datasource: Datasource
) -> None:
    _, secret = _key(session)
    response = _chat(client, secret, {"id": "u-1", "role": "gerente_sucursal"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "missing_attributes"
    assert session.scalars(select(Conversation)).all() == []


def test_chat_sin_credencial_es_401(client: TestClient, datasource: Datasource) -> None:
    assert client.post("/api/v1/chat", json={}).status_code == 401


def test_misma_key_usuarios_con_distintas_sucursales_ven_resultados_distintos(
    client: TestClient, session: Session, datasource: Datasource
) -> None:
    _, secret = _key(session)

    uno_dos = _chat(client, secret, _gerente(1, 2))
    tres = _chat(client, secret, _gerente(3))

    assert uno_dos.status_code == 200, uno_dos.text
    assert tres.status_code == 200, tres.text
    assert uno_dos.json()["status"] == tres.json()["status"] == "answered"
    filas_uno_dos = uno_dos.json()["result"]["rows"]
    filas_tres = tres.json()["result"]["rows"]
    assert len(filas_uno_dos) == 2 and len(filas_tres) == 1
    assert {f[0] for f in filas_uno_dos}.isdisjoint({f[0] for f in filas_tres})
    assert uno_dos.json()["sql"]["origin"] == "catalog"


def test_conversaciones_aisladas_por_key_y_usuario_final(
    client: TestClient, session: Session, datasource: Datasource
) -> None:
    _, secret = _key(session)
    _, otra_secret = _key(session, name="otra")
    user = {"id": "u-1", "role": "gerencia_general"}

    conversation_id = _chat(client, secret, user).json()["conversation_id"]
    stored = session.get(Conversation, uuid.UUID(conversation_id))
    assert stored is not None and stored.external_user_id == "u-1" and stored.api_key_id

    # El mismo usuario final la continúa; otro usuario o la otra key no la ven.
    same = _chat(client, secret, user, conversation_id=conversation_id)
    assert same.status_code == 200, same.text
    other = {"id": "u-2", "role": "gerencia_general"}
    other_user = _chat(client, secret, other, conversation_id=conversation_id)
    other_key = _chat(client, otra_secret, user, conversation_id=conversation_id)
    assert other_user.status_code == 404 and other_key.status_code == 404


# --- seguridad de las rutas de chat (POST /chat comparte módulo con el streaming) ---------------

SOLO_SESION = [
    ("/api/v1/chat/stream", {"datasource_id": "ventas", "message": "hola"}),
    ("/api/v1/chat/00000000-0000-0000-0000-000000000000/cancel", None),
]


@pytest.mark.parametrize(
    ("path", "body"),
    [("/api/v1/chat", {"datasource_id": "ventas", "message": "hola"}), *SOLO_SESION],
)
def test_toda_ruta_de_chat_sin_credencial_es_401(
    client: TestClient, datasource: Datasource, path: str, body: dict[str, Any] | None
) -> None:
    assert client.post(path, json=body).status_code == 401


@pytest.mark.parametrize(("path", "body"), SOLO_SESION)
def test_una_api_key_no_llega_al_chat_de_sesion(
    client: TestClient, session: Session, datasource: Datasource, path: str, body: Any
) -> None:
    _, secret = _key(session)  # alcance `chat`, y aun así: el streaming es solo de sesión
    response = client.post(path, json=body, headers={"Authorization": f"Bearer {secret}"})
    assert response.status_code == 401


def test_post_chat_con_key_sin_alcance_chat_es_403(
    client: TestClient, session: Session, datasource: Datasource
) -> None:
    _, secret = _key(session, scopes=["sql:preview"])
    response = _chat(client, secret, {"id": "u-1", "role": "gerencia_general"})
    assert response.status_code == 403
