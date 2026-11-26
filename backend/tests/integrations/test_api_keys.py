import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated

import pytest
from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app import cli
from app.db.models import ApiKey, Base, User
from app.db.session import get_session, make_engine
from app.integrations.api_keys import (
    SCOPES,
    Principal,
    authenticate_api_key,
    create_api_key,
    get_principal,
    hash_secret,
    parse_api_key,
    require_scope,
    revoke_api_key,
)
from app.main import API_PREFIX, create_app
from app.security.auth import AuthError, create_access_token, hash_password


@pytest.fixture(autouse=True)
def _entorno(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHATIAPP_SECRET_KEY", "llave-de-prueba-" + "x" * 32)


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    eng = make_engine(f"sqlite:///{tmp_path / 'app.db'}")
    Base.metadata.create_all(eng)
    with Session(eng) as session:
        pw = hash_password("x")
        session.add(User(email="admin@example.com", password_hash=pw, is_admin=True))
        session.add(User(email="ana@example.com", password_hash=pw, is_admin=False))
        session.commit()
    yield eng
    eng.dispose()


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    with Session(engine, expire_on_commit=False) as s:
        yield s


@pytest.fixture
def client(engine: Engine) -> TestClient:
    application: FastAPI = create_app()

    def _session() -> Iterator[Session]:
        with Session(engine, expire_on_commit=False) as s:
            yield s

    application.dependency_overrides[get_session] = _session

    router = APIRouter()

    @router.get("/quien")
    def quien(principal: Annotated[Principal, Depends(get_principal)]) -> dict[str, object]:
        return {"kind": principal.kind, "admin": principal.is_admin}

    @router.get("/chat")
    def chat(_p: Annotated[Principal, Depends(require_scope("chat"))]) -> dict[str, bool]:
        return {"ok": True}

    application.include_router(router, prefix=API_PREFIX)
    return TestClient(application)


def _jwt(engine: Engine, email: str) -> dict[str, str]:
    with Session(engine) as s:
        user = s.query(User).filter_by(email=email).one()
        return {"Authorization": f"Bearer {create_access_token(user.id)}"}


def _bearer(secret: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {secret}"}


# --- Formato y almacenamiento -----------------------------------------------------------------


def test_formato_y_secreto_de_al_menos_32_bytes(session: Session) -> None:
    api_key, secret = create_api_key(session, name="Portal", scopes=["chat"])
    parsed = parse_api_key(secret)
    assert parsed is not None
    prefix, raw_secret = parsed
    assert secret.startswith("chia_")
    assert prefix == api_key.prefix
    assert len(raw_secret) >= 43  # token_urlsafe(32)


def test_la_base_nunca_contiene_el_secreto_en_claro(session: Session, engine: Engine) -> None:
    api_key, secret = create_api_key(session, name="Portal", scopes=["chat"])
    raw_secret = secret.split("_", 2)[2]
    assert api_key.secret_hash == hash_secret(raw_secret)
    with engine.connect() as conn:
        for table in conn.execute(text("select name from sqlite_master where type='table'")):
            for row in conn.execute(text(f'select * from "{table[0]}"')):
                assert raw_secret not in repr(tuple(row))
                assert secret not in repr(tuple(row))


def test_dos_keys_distintas_tienen_secretos_y_prefijos_distintos(session: Session) -> None:
    a, secret_a = create_api_key(session, name="a", scopes=["chat"])
    b, secret_b = create_api_key(session, name="b", scopes=["chat"])
    assert a.prefix != b.prefix
    assert secret_a != secret_b


def test_alcance_o_datos_invalidos_se_rechazan(session: Session) -> None:
    with pytest.raises(ValueError):
        create_api_key(session, name="x", scopes=["admin"])
    with pytest.raises(ValueError):
        create_api_key(session, name="x", scopes=[])
    with pytest.raises(ValueError):
        create_api_key(session, name=" ", scopes=["chat"])
    with pytest.raises(ValueError):
        create_api_key(
            session, name="x", scopes=["chat"], expires_at=datetime.now(UTC) - timedelta(days=1)
        )


# --- Verificación -----------------------------------------------------------------------------


def test_key_valida_autentica_y_registra_ultimo_uso(session: Session) -> None:
    api_key, secret = create_api_key(session, name="Portal", scopes=["chat"])
    assert api_key.last_used_at is None
    found = authenticate_api_key(session, secret)
    assert found.id == api_key.id
    assert found.last_used_at is not None


@pytest.mark.parametrize("mal", ["", "chia_", "chia_abc", "otra_abc_def", "chia__x", "chia_a_"])
def test_formato_incorrecto_es_401(session: Session, mal: str) -> None:
    with pytest.raises(AuthError) as exc:
        authenticate_api_key(session, mal)
    assert exc.value.status_code == 401


def test_secreto_incorrecto_o_key_inexistente_es_401(session: Session) -> None:
    api_key, secret = create_api_key(session, name="Portal", scopes=["chat"])
    for bad in (f"{api_key.prefix}_otro-secreto", "chia_noexiste_secreto", secret + "x"):
        with pytest.raises(AuthError) as exc:
            authenticate_api_key(session, bad)
        assert exc.value.status_code == 401


def test_key_revocada_es_rechazada(session: Session) -> None:
    api_key, secret = create_api_key(session, name="Portal", scopes=["chat"])
    revoke_api_key(session, api_key.id)
    with pytest.raises(AuthError) as exc:
        authenticate_api_key(session, secret)
    assert exc.value.status_code == 401


def test_key_expirada_es_rechazada(session: Session) -> None:
    _, secret = create_api_key(
        session, name="Portal", scopes=["chat"], expires_at=datetime.now(UTC) + timedelta(hours=1)
    )
    authenticate_api_key(session, secret)
    with pytest.raises(AuthError) as exc:
        authenticate_api_key(session, secret, now=datetime.now(UTC) + timedelta(hours=2))
    assert exc.value.status_code == 401


# --- Principal y alcances por HTTP ------------------------------------------------------------


def test_principal_acepta_jwt_de_usuario_y_api_key(client: TestClient, engine: Engine) -> None:
    with Session(engine) as s:
        _, secret = create_api_key(s, name="Portal", scopes=["chat"])
    por_jwt = client.get(f"{API_PREFIX}/quien", headers=_jwt(engine, "admin@example.com"))
    por_key = client.get(f"{API_PREFIX}/quien", headers=_bearer(secret))
    assert por_jwt.json() == {"kind": "user", "admin": True}
    assert por_key.json() == {"kind": "api_key", "admin": False}
    assert client.get(f"{API_PREFIX}/quien").status_code == 401


def test_endpoint_sin_el_alcance_requerido_responde_403(client: TestClient, engine: Engine) -> None:
    with Session(engine) as s:
        _, con_chat = create_api_key(s, name="chat", scopes=["chat"])
        _, sin_chat = create_api_key(s, name="sql", scopes=["sql:preview"])
    assert client.get(f"{API_PREFIX}/chat", headers=_bearer(con_chat)).status_code == 200
    denegada = client.get(f"{API_PREFIX}/chat", headers=_bearer(sin_chat))
    assert denegada.status_code == 403
    assert denegada.json()["error"]["code"] == "insufficient_scope"
    # Un usuario con sesión no queda limitado por alcances.
    ana = _jwt(engine, "ana@example.com")
    assert client.get(f"{API_PREFIX}/chat", headers=ana).status_code == 200


def test_revocar_surte_efecto_en_la_siguiente_peticion(client: TestClient, engine: Engine) -> None:
    admin = _jwt(engine, "admin@example.com")
    creada = client.post(
        f"{API_PREFIX}/api-keys", json={"name": "Portal", "scopes": ["chat"]}, headers=admin
    ).json()
    key = _bearer(creada["secret"])
    assert client.get(f"{API_PREFIX}/chat", headers=key).status_code == 200
    revocada = client.post(f"{API_PREFIX}/api-keys/{creada['id']}/revoke", headers=admin)
    assert revocada.status_code == 200
    assert revocada.json()["revoked_at"] is not None
    assert client.get(f"{API_PREFIX}/chat", headers=key).status_code == 401


def test_ninguna_key_administra_keys_ni_usuarios(client: TestClient, engine: Engine) -> None:
    with Session(engine) as s:
        _, secret = create_api_key(s, name="Todo", scopes=list(SCOPES))
    headers = _bearer(secret)
    assert client.get(f"{API_PREFIX}/api-keys", headers=headers).status_code == 401
    assert client.post(f"{API_PREFIX}/api-keys", json={}, headers=headers).status_code == 401
    assert client.get(f"{API_PREFIX}/auth/me", headers=headers).status_code == 401


# --- API de administración --------------------------------------------------------------------


def test_administracion_exige_administrador(client: TestClient, engine: Engine) -> None:
    assert client.get(f"{API_PREFIX}/api-keys").status_code == 401
    ana = _jwt(engine, "ana@example.com")
    assert client.get(f"{API_PREFIX}/api-keys", headers=ana).status_code == 403


def test_crear_listar_editar(client: TestClient, engine: Engine) -> None:
    admin = _jwt(engine, "admin@example.com")
    body = {
        "name": "Portal",
        "scopes": ["chat", "embed"],
        "datasources": ["ventas"],
        "allowed_roles": ["gerente_sucursal"],
        "allowed_origins": ["https://portal.example.com"],
        "rate_limit_per_minute": 60,
        "monthly_budget_usd": "25.5",
    }
    creada = client.post(f"{API_PREFIX}/api-keys", json=body, headers=admin)
    assert creada.status_code == 201
    data = creada.json()
    assert data["secret"].startswith(data["prefix"] + "_")

    listada = client.get(f"{API_PREFIX}/api-keys", headers=admin).json()
    assert [k["id"] for k in listada] == [data["id"]]
    assert "secret" not in listada[0]
    assert "secret_hash" not in listada[0]
    assert data["secret"] not in str(listada)

    editada = client.patch(
        f"{API_PREFIX}/api-keys/{data['id']}",
        json={"scopes": ["chat"], "rate_limit_per_minute": None},
        headers=admin,
    )
    assert editada.status_code == 200
    assert editada.json()["scopes"] == ["chat"]
    assert editada.json()["rate_limit_per_minute"] is None
    assert editada.json()["datasources"] == ["ventas"]  # lo no enviado no cambia


def test_validaciones_de_la_api(client: TestClient, engine: Engine) -> None:
    admin = _jwt(engine, "admin@example.com")
    url = f"{API_PREFIX}/api-keys"
    for scopes in (["admin"], []):
        respuesta = client.post(url, json={"name": "x", "scopes": scopes}, headers=admin)
        assert respuesta.status_code == 422
    pasada = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    malo = {"name": "x", "scopes": ["chat"], "expires_at": pasada}
    assert client.post(url, json=malo, headers=admin).status_code == 422
    inexistente = f"{url}/{uuid.uuid4()}"
    assert client.patch(inexistente, json={"name": "y"}, headers=admin).status_code == 404
    assert client.post(f"{inexistente}/revoke", headers=admin).status_code == 404


def test_no_se_edita_una_key_revocada(client: TestClient, engine: Engine) -> None:
    admin = _jwt(engine, "admin@example.com")
    creada = client.post(
        f"{API_PREFIX}/api-keys", json={"name": "Portal", "scopes": ["chat"]}, headers=admin
    ).json()
    client.post(f"{API_PREFIX}/api-keys/{creada['id']}/revoke", headers=admin)
    respuesta = client.patch(
        f"{API_PREFIX}/api-keys/{creada['id']}", json={"name": "otro"}, headers=admin
    )
    assert respuesta.status_code == 409


# --- CLI --------------------------------------------------------------------------------------


def test_cli_crea_lista_y_revoca(engine: Engine, capsys: pytest.CaptureFixture[str]) -> None:
    def factory() -> Session:
        return Session(engine, expire_on_commit=False)

    code = cli.main(
        [
            "keys",
            "create",
            "--name",
            "Portal",
            "--scopes",
            "chat,embed",
            "--datasource",
            "ventas",
            "--roles",
            "gerente_sucursal",
            "--origin",
            "https://portal.example.com",
            "--rate-limit",
            "30",
            "--monthly-budget",
            "10",
        ],
        factory,
    )
    assert code == 0
    secret = capsys.readouterr().out.strip()
    assert secret.startswith("chia_")
    with Session(engine) as s:
        key = s.query(ApiKey).one()
        assert key.scopes == ["chat", "embed"]
        assert key.datasources == ["ventas"]
        assert key.rate_limit_per_minute == 30
        authenticate_api_key(s, secret)

    assert cli.main(["keys", "list"], factory) == 0
    listado = capsys.readouterr().out
    assert key.prefix in listado
    assert "activa" in listado
    assert secret not in listado

    assert cli.main(["keys", "revoke", key.prefix], factory) == 0
    with Session(engine) as s, pytest.raises(AuthError):
        authenticate_api_key(s, secret)
    cli.main(["keys", "list"], factory)
    assert "revocada" in capsys.readouterr().out


def test_cli_rechaza_alcance_invalido(engine: Engine, capsys: pytest.CaptureFixture[str]) -> None:
    def factory() -> Session:
        return Session(engine, expire_on_commit=False)

    assert cli.main(["keys", "create", "--name", "x", "--scopes", "admin"], factory) == 1
    assert "Alcances desconocidos" in capsys.readouterr().err
    assert cli.main(["keys", "revoke", "chia_noexiste"], factory) == 1
