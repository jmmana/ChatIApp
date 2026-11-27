import importlib
import json
import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.api.datasources import get_request_cipher
from app.db.models import ApiKey, Base, Conversation, Datasource, Provider, SemanticModelVersion
from app.db.session import get_session, make_engine
from app.demo.seed import generar
from app.engine.guard import guards
from app.integrations.api_keys import create_api_key, revoke_api_key
from app.integrations.embed_sessions import (
    MAX_TTL_SECONDS,
    create_embed_token,
    normalize_origin,
)
from app.main import API_PREFIX, create_app
from app.security.auth import ALGORITHM, get_secret_key
from app.security.crypto import encrypt, make_cipher
from app.semantic.schema import parse_semantic_model
from app.settings.registry import datasource_uuid

EXAMPLE = Path(__file__).parents[3] / "examples" / "ventas" / "semantic-model.yaml"
CIPHER = make_cipher("clave-de-prueba")
ORIGIN = "https://portal.example.com"
OTRO_ORIGEN = "https://sitio-ajeno.example.org"
PLAN = {
    "intent": "metric",
    "reasoning": "Ventas netas por sucursal.",
    "metric": "ventas_netas",
    "dimensions": ["sucursales.nombre"],
    "period_text": "2026",
}
GERENTE = {"id": "u-1", "role": "gerente_sucursal", "attributes": {"sucursales": [1]}}


@pytest.fixture(autouse=True)
def _entorno(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHATIAPP_SECRET_KEY", "llave-de-prueba-" + "x" * 32)


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


@pytest.fixture(autouse=True)
def datasources(session: Session, demo_url: str) -> None:
    """Dos fuentes con el mismo modelo y un proveedor simulado."""
    yaml = importlib.import_module("yaml")
    model = parse_semantic_model(yaml.safe_load(EXAMPLE.read_text())).model_dump(mode="json")
    for name in ("ventas", "otra"):
        ds = Datasource(
            id=datasource_uuid(name),
            name=name,
            dialect="sqlite",
            url_encrypted=encrypt(demo_url, CIPHER),
            execute=True,
            privacy="schema",
        )
        session.add(ds)
        session.flush()
        session.add(SemanticModelVersion(datasource_id=ds.id, version=1, model=model))
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
        "name": "portal",
        "scopes": ["embed"],
        "datasources": ["ventas"],
        "allowed_roles": ["gerente_sucursal", "gerencia_general"],
        "allowed_origins": [ORIGIN],
    }
    return create_api_key(session, **{**options, **kwargs})


def _auth(token: str, origin: str | None = ORIGIN) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if origin is not None:
        headers["Origin"] = origin
    return headers


def _emitir(client: TestClient, secret: str, **extra: Any) -> Any:
    body: dict[str, Any] = {"datasource": "ventas", "origin": ORIGIN, "user": GERENTE}
    return client.post(
        f"{API_PREFIX}/embed/sessions", json={**body, **extra}, headers=_auth(secret, None)
    )


def _token(client: TestClient, secret: str, **extra: Any) -> str:
    response = _emitir(client, secret, **extra)
    assert response.status_code == 200, response.text
    return str(response.json()["token"])


def _stream(client: TestClient, token: str, **extra: Any) -> Any:
    body = {"datasource_id": "ventas", "message": "ventas por sucursal", **extra}
    return client.post(f"{API_PREFIX}/chat/stream", json=body, headers=_auth(token))


# --- POST /embed/sessions -------------------------------------------------------------------


def test_emite_un_jwt_con_la_identidad_y_solo_alcance_de_chat(
    client: TestClient, session: Session
) -> None:
    api_key, secret = _key(session)
    antes = datetime.now(UTC).replace(microsecond=0)
    response = _emitir(client, secret)
    assert response.status_code == 200
    body = response.json()
    claims = jwt.decode(body["token"], get_secret_key(), algorithms=[ALGORITHM])
    assert claims["sub"] == "u-1"
    assert claims["ds"] == str(datasource_uuid("ventas"))
    assert claims["role"] == "gerente_sucursal"
    assert claims["attrs"] == {"sucursales": [1]}
    assert claims["origin"] == ORIGIN
    assert claims["kid"] == str(api_key.id)
    assert claims["scopes"] == ["chat"]
    # Por defecto 900 s; `expires_at` coincide con `exp`.
    assert claims["exp"] - claims["iat"] == 900
    expires = datetime.fromisoformat(body["expires_at"])
    assert int(expires.timestamp()) == claims["exp"]
    assert expires >= antes + timedelta(seconds=900)


def test_ttl_configurable_con_maximo_de_3600(client: TestClient, session: Session) -> None:
    _, secret = _key(session)
    token = _token(client, secret, ttl_seconds=60)
    claims = jwt.decode(token, get_secret_key(), algorithms=[ALGORITHM])
    assert claims["exp"] - claims["iat"] == 60
    token = _token(client, secret, ttl_seconds=MAX_TTL_SECONDS)
    claims = jwt.decode(token, get_secret_key(), algorithms=[ALGORITHM])
    assert claims["exp"] - claims["iat"] == 3600
    for ttl in (MAX_TTL_SECONDS + 1, 0):
        assert _emitir(client, secret, ttl_seconds=ttl).status_code == 422


def test_el_origen_debe_estar_entre_los_permitidos_de_la_key(
    client: TestClient, session: Session
) -> None:
    _, secret = _key(session)
    response = _emitir(client, secret, origin=OTRO_ORIGEN)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "origin_not_allowed"
    # Mayúsculas y barra final no cambian el origen.
    assert _emitir(client, secret, origin=ORIGIN.upper() + "/").status_code == 200
    assert _emitir(client, secret, origin="portal").status_code == 422


def test_exige_alcance_embed_y_una_api_key(client: TestClient, session: Session) -> None:
    _, solo_chat = _key(session, scopes=["chat"], name="chat")
    assert _emitir(client, solo_chat).status_code == 403
    assert _emitir(client, "chia_noexiste_secreto").status_code == 401
    assert client.post(f"{API_PREFIX}/embed/sessions", json={}).status_code == 401


def test_valida_fuente_rol_y_atributos_con_el_techo_de_la_key(
    client: TestClient, session: Session
) -> None:
    _, secret = _key(session)
    assert _emitir(client, secret, datasource="otra").status_code == 403  # fuera de la key
    assert _emitir(client, secret, datasource="inexistente").status_code == 404
    rol_ajeno = {**GERENTE, "role": "analista"}
    assert _emitir(client, secret, user=rol_ajeno).status_code == 403
    sin_atributos = {"id": "u-1", "role": "gerente_sucursal"}
    response = _emitir(client, secret, user=sin_atributos)
    assert (response.status_code, response.json()["error"]["code"]) == (422, "missing_attributes")


def test_con_rol_fijo_el_token_lleva_ese_rol(client: TestClient, session: Session) -> None:
    _, secret = _key(session, allowed_roles=["gerencia_general"])
    token = _token(client, secret, user={"id": "u-9", "role": "gerente_sucursal"})
    claims = jwt.decode(token, get_secret_key(), algorithms=[ALGORITHM])
    assert claims["role"] == "gerencia_general" and claims["attrs"] == {}


def test_normaliza_origenes() -> None:
    esperado = "https://portal.example.com:8443"
    assert normalize_origin(" HTTPS://Portal.Example.com:8443/ ") == esperado
    for malo in ("portal.example.com", "ftp://x.com", "https://x.com/ruta", "https://u@x.com"):
        with pytest.raises(ValueError):
            normalize_origin(malo)


# --- El token en el chat ----------------------------------------------------------------------


def test_el_token_sirve_para_chatear_y_guarda_la_conversacion_del_usuario_final(
    client: TestClient, session: Session
) -> None:
    api_key, secret = _key(session)
    token = _token(client, secret)
    response = _stream(client, token)
    assert response.status_code == 200
    assert "event: answer" in response.text and "event: turn.completed" in response.text
    session.expire_all()
    conversation = session.scalars(select(Conversation)).one()
    assert conversation.api_key_id == api_key.id
    assert conversation.external_user_id == "u-1" and conversation.user_id is None
    listado = client.get(f"{API_PREFIX}/conversations", headers=_auth(token))
    assert [c["id"] for c in listado.json()] == [str(conversation.id)]
    detalle = client.get(f"{API_PREFIX}/conversations/{conversation.id}", headers=_auth(token))
    assert detalle.status_code == 200 and len(detalle.json()["messages"]) == 2


# --- Garantía 1: no puede cambiar de fuente, de rol ni de atributos ---------------------------


def test_no_puede_cambiar_de_fuente(client: TestClient, session: Session) -> None:
    _, secret = _key(session, datasources=["ventas", "otra"])
    token = _token(client, secret)
    response = _stream(client, token, datasource_id="otra")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "datasource_not_allowed"


def test_no_puede_cambiar_de_rol_ni_de_atributos(client: TestClient, session: Session) -> None:
    _, secret = _key(session)
    token = _token(client, secret)
    claims = jwt.decode(token, get_secret_key(), algorithms=[ALGORITHM])
    # Reescribir el token sin la llave del servidor no sirve: la firma falla.
    forjado = jwt.encode({**claims, "role": "gerencia_general"}, "otra-llave", algorithm=ALGORITHM)
    response = _stream(client, forjado)
    assert (response.status_code, response.json()["error"]["code"]) == (401, "invalid_token")
    atributos = jwt.encode(
        {**claims, "attrs": {"sucursales": [1, 2]}}, "otra-llave", algorithm=ALGORITHM
    )
    assert _stream(client, atributos).status_code == 401
    # `user` y `view_as` en la petición no alteran la identidad: el token manda.
    extra = {"view_as": {"role": "gerencia_general"}, "provider_override": "otro"}
    assert _stream(client, token, **extra).status_code == 200


def test_si_la_key_pierde_el_rol_el_token_deja_de_servir(
    client: TestClient, session: Session
) -> None:
    api_key, secret = _key(session)
    token = _token(client, secret)
    # El techo se revalida en cada petición (con un solo rol permitido sería rol fijo).
    api_key.allowed_roles = ["gerencia_general", "analista"]
    session.commit()
    assert _stream(client, token).status_code == 403


# --- Garantía 2: solo sus conversaciones --------------------------------------------------------


def test_cada_usuario_ve_solo_sus_conversaciones(client: TestClient, session: Session) -> None:
    _, secret = _key(session)
    uno = _token(client, secret)
    dos = _token(client, secret, user={**GERENTE, "id": "u-2"})
    assert _stream(client, uno).status_code == 200
    conversation = session.scalars(select(Conversation)).one()
    url = f"{API_PREFIX}/conversations/{conversation.id}"
    assert client.get(f"{API_PREFIX}/conversations", headers=_auth(dos)).json() == []
    assert client.get(url, headers=_auth(dos)).status_code == 404
    assert client.get(url, headers=_auth(uno)).status_code == 200
    # Tampoco puede continuarla.
    response = _stream(client, dos, conversation_id=str(conversation.id))
    assert (response.status_code, response.json()["error"]["code"]) == (
        404,
        "conversation_not_found",
    )


def test_otra_key_con_el_mismo_usuario_no_ve_las_conversaciones(
    client: TestClient, session: Session
) -> None:
    _, secret = _key(session)
    _, otra = _key(session, name="otra-app")
    assert _stream(client, _token(client, secret)).status_code == 200
    listado = client.get(f"{API_PREFIX}/conversations", headers=_auth(_token(client, otra)))
    assert listado.json() == []


def test_no_puede_renombrar_ni_eliminar(client: TestClient, session: Session) -> None:
    _, secret = _key(session)
    token = _token(client, secret)
    assert _stream(client, token).status_code == 200
    conversation = session.scalars(select(Conversation)).one()
    url = f"{API_PREFIX}/conversations/{conversation.id}"
    assert client.patch(url, json={"title": "x"}, headers=_auth(token)).status_code in (401, 403)
    assert client.delete(url, headers=_auth(token)).status_code in (401, 403)


def test_solo_cancela_sus_propios_turnos(client: TestClient, session: Session) -> None:
    _, secret = _key(session)
    token = _token(client, secret)
    response = client.post(f"{API_PREFIX}/chat/{uuid.uuid4()}/cancel", headers=_auth(token))
    assert response.status_code == 404  # llega a la ruta, pero el turno no es suyo


# --- Alcance: solo chat y conversaciones --------------------------------------------------------

PERMITIDAS = {
    ("POST", f"{API_PREFIX}/chat/stream"),
    ("POST", f"{API_PREFIX}/chat/{{turn_id}}/cancel"),
    ("GET", f"{API_PREFIX}/conversations"),
    ("GET", f"{API_PREFIX}/conversations/{{conversation_id}}"),
    ("GET", f"{API_PREFIX}/health"),
    ("POST", f"{API_PREFIX}/auth/login"),
    ("POST", f"{API_PREFIX}/auth/refresh"),
    ("POST", f"{API_PREFIX}/auth/logout"),
}


def test_el_token_no_sirve_en_ningun_otro_endpoint(client: TestClient, session: Session) -> None:
    _, secret = _key(session)
    token = _token(client, secret)
    paths = client.app.openapi()["paths"]  # type: ignore[attr-defined]
    revisados = []
    for path, operations in paths.items():
        for method in operations:
            key = (method.upper(), path)
            if key in PERMITIDAS:
                continue
            url = path.replace("{", "").replace("}", "")
            response = client.request(method.upper(), url, headers=_auth(token))
            assert response.status_code in (401, 403), f"{key} → {response.status_code}"
            revisados.append(key)
    # Los endpoints sensibles están en la revisión, incluido emitir otros tokens.
    for sensible in (
        ("POST", f"{API_PREFIX}/embed/sessions"),
        ("POST", f"{API_PREFIX}/chat"),
        ("GET", f"{API_PREFIX}/api-keys"),
        ("GET", f"{API_PREFIX}/datasources"),
        ("GET", f"{API_PREFIX}/users"),
    ):
        assert sensible in revisados


# --- Garantía 3: solo desde el origen indicado ---------------------------------------------------


def test_desde_otro_origen_o_sin_origen_responde_403(client: TestClient, session: Session) -> None:
    _, secret = _key(session, allowed_origins=[ORIGIN, OTRO_ORIGEN])
    token = _token(client, secret)
    for origin in (OTRO_ORIGEN, None):
        for response in (
            _stream_with_origin(client, token, origin),
            client.get(f"{API_PREFIX}/conversations", headers=_auth(token, origin)),
        ):
            assert response.status_code == 403
            assert response.json()["error"]["code"] == "origin_not_allowed"
    assert _stream(client, token).status_code == 200


def _stream_with_origin(client: TestClient, token: str, origin: str | None) -> Any:
    body = {"datasource_id": "ventas", "message": "hola"}
    return client.post(f"{API_PREFIX}/chat/stream", json=body, headers=_auth(token, origin))


def test_si_la_key_quita_el_origen_el_token_deja_de_servir(
    client: TestClient, session: Session
) -> None:
    api_key, secret = _key(session)
    token = _token(client, secret)
    api_key.allowed_origins = [OTRO_ORIGEN]
    session.commit()
    assert _stream(client, token).status_code == 403


def test_cors_solo_para_los_origenes_permitidos(client: TestClient, session: Session) -> None:
    _key(session)
    preflight = {
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "authorization,content-type",
    }
    url = f"{API_PREFIX}/chat/stream"
    permitido = client.options(url, headers={"Origin": ORIGIN, **preflight})
    assert permitido.status_code == 204
    assert permitido.headers["access-control-allow-origin"] == ORIGIN
    assert "Authorization" in permitido.headers["access-control-allow-headers"]
    assert permitido.headers["vary"] == "Origin"
    ajeno = client.options(url, headers={"Origin": OTRO_ORIGEN, **preflight})
    assert ajeno.status_code == 403
    assert "access-control-allow-origin" not in ajeno.headers
    # Respuestas reales: cabecera solo para el origen permitido; nunca comodín.
    ok = client.get(f"{API_PREFIX}/health", headers={"Origin": ORIGIN})
    assert ok.headers["access-control-allow-origin"] == ORIGIN
    otro = client.get(f"{API_PREFIX}/health", headers={"Origin": OTRO_ORIGEN})
    assert "access-control-allow-origin" not in otro.headers
    sin_origen = client.get(f"{API_PREFIX}/health")
    assert "access-control-allow-origin" not in sin_origen.headers


def test_cors_ignora_keys_revocadas_o_sin_alcance_embed(
    client: TestClient, session: Session
) -> None:
    api_key, _ = _key(session)
    _key(session, name="solo-chat", scopes=["chat"], allowed_origins=[OTRO_ORIGEN])
    preflight = {"Access-Control-Request-Method": "POST"}
    url = f"{API_PREFIX}/chat/stream"
    assert client.options(url, headers={"Origin": ORIGIN, **preflight}).status_code == 204
    assert client.options(url, headers={"Origin": OTRO_ORIGEN, **preflight}).status_code == 403
    revoke_api_key(session, api_key.id)
    assert client.options(url, headers={"Origin": ORIGIN, **preflight}).status_code == 403


# --- Garantía 4: vida corta y sin renovarse solo --------------------------------------------------


def test_token_expirado_responde_401_con_codigo_para_pedir_otro(
    client: TestClient, session: Session
) -> None:
    api_key, _ = _key(session)
    token, _ = create_embed_token(
        api_key,
        user_id="u-1",
        datasource_id=datasource_uuid("ventas"),
        role="gerente_sucursal",
        attributes={"sucursales": [1]},
        origin=ORIGIN,
        ttl_seconds=60,
        now=datetime.now(UTC) - timedelta(hours=1),
    )
    for response in (
        _stream(client, token),
        client.get(f"{API_PREFIX}/conversations", headers=_auth(token)),
    ):
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "token_expired"
        assert response.headers["www-authenticate"] == "Bearer"


def test_un_token_no_emite_ni_renueva_tokens(client: TestClient, session: Session) -> None:
    _, secret = _key(session)
    token = _token(client, secret)
    response = client.post(
        f"{API_PREFIX}/embed/sessions",
        json={"datasource": "ventas", "origin": ORIGIN, "user": GERENTE},
        headers=_auth(token),
    )
    assert response.status_code in (401, 403)


def test_el_ttl_no_pasa_de_una_hora_ni_siquiera_directo(session: Session) -> None:
    api_key, _ = _key(session)
    with pytest.raises(ValueError):
        create_embed_token(
            api_key,
            user_id="u",
            datasource_id=datasource_uuid("ventas"),
            role="gerente_sucursal",
            attributes={},
            origin=ORIGIN,
            ttl_seconds=MAX_TTL_SECONDS + 1,
        )


# --- Revocación ---------------------------------------------------------------------------------


def test_revocar_la_key_invalida_sus_tokens_en_la_siguiente_peticion(
    client: TestClient, session: Session
) -> None:
    api_key, secret = _key(session)
    token = _token(client, secret)
    assert _stream(client, token).status_code == 200
    revoke_api_key(session, api_key.id)
    for response in (
        _stream(client, token),
        client.get(f"{API_PREFIX}/conversations", headers=_auth(token)),
    ):
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "invalid_api_key"
    assert _emitir(client, secret).status_code == 401  # y la key ya no emite


def test_una_key_vencida_invalida_sus_tokens(client: TestClient, session: Session) -> None:
    api_key, secret = _key(session)
    token = _token(client, secret)
    api_key.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    session.commit()
    response = client.get(f"{API_PREFIX}/conversations", headers=_auth(token))
    assert (response.status_code, response.json()["error"]["code"]) == (401, "invalid_api_key")


def test_si_la_key_pierde_el_alcance_embed_sus_tokens_dejan_de_servir(
    client: TestClient, session: Session
) -> None:
    api_key, secret = _key(session, scopes=["embed", "chat"])
    token = _token(client, secret)
    api_key.scopes = ["chat"]
    session.commit()
    assert client.get(f"{API_PREFIX}/conversations", headers=_auth(token)).status_code == 401
