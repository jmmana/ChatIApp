import uuid
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.db.models import Base, User
from app.db.session import get_session, make_engine
from app.main import API_PREFIX, create_app
from app.security.auth import (
    LoginThrottle,
    create_access_token,
    create_refresh_token,
    ensure_initial_admin,
    get_current_user,
    get_throttle,
    hash_password,
    require_admin,
    verify_password,
)

ADMIN = ("admin@example.com", "clave-admin-1")
USER = ("ana@example.com", "clave-ana-1")


@pytest.fixture(autouse=True)
def _entorno(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHATIAPP_SECRET_KEY", "llave-de-prueba-" + "x" * 32)
    monkeypatch.setenv("CHATIAPP_COOKIE_SECURE", "false")


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    eng = make_engine(f"sqlite:///{tmp_path / 'app.db'}")
    Base.metadata.create_all(eng)
    with Session(eng) as session:
        session.add(User(email=ADMIN[0], password_hash=hash_password(ADMIN[1]), is_admin=True))
        session.add(User(email=USER[0], password_hash=hash_password(USER[1]), is_admin=False))
        session.commit()
    yield eng
    eng.dispose()


@pytest.fixture
def client(engine: Engine) -> TestClient:
    application: FastAPI = create_app()

    def _session() -> Iterator[Session]:
        with Session(engine, expire_on_commit=False) as session:
            yield session

    application.dependency_overrides[get_session] = _session
    throttle = LoginThrottle()
    application.dependency_overrides[get_throttle] = lambda: throttle

    privadas = APIRouter(dependencies=[Depends(get_current_user)])
    admin = APIRouter(dependencies=[Depends(require_admin)])

    @privadas.get("/privada")
    def privada() -> dict[str, bool]:
        return {"ok": True}

    @admin.get("/admin")
    def administracion() -> dict[str, bool]:
        return {"ok": True}

    application.include_router(privadas, prefix=API_PREFIX)
    application.include_router(admin, prefix=API_PREFIX)
    return TestClient(application)


def _login(client: TestClient, creds: tuple[str, str]) -> str:
    response = client.post(
        f"{API_PREFIX}/auth/login", json={"email": creds[0], "password": creds[1]}
    )
    assert response.status_code == 200
    return str(response.json()["access_token"])


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# --- Hash y login ---


def test_hash_argon2_verifica_y_rechaza() -> None:
    hashed = hash_password("secreto")
    assert hashed.startswith("$argon2")
    assert verify_password("secreto", hashed)
    assert not verify_password("otro", hashed)
    assert not verify_password("secreto", "no-es-un-hash")


def test_login_correcto_devuelve_jwt_y_cookie_httponly(client: TestClient) -> None:
    response = client.post(
        f"{API_PREFIX}/auth/login", json={"email": "ANA@example.com", "password": USER[1]}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 900
    assert body["user"]["email"] == USER[0]
    assert body["user"]["is_admin"] is False
    cookie = response.headers["set-cookie"].lower()
    assert "chatiapp_refresh=" in cookie
    assert "httponly" in cookie
    assert "samesite=strict" in cookie
    assert "refresh_token" not in body


def test_login_incorrecto_responde_401(client: TestClient) -> None:
    for email, password in [(USER[0], "mala"), ("nadie@example.com", "mala")]:
        response = client.post(
            f"{API_PREFIX}/auth/login", json={"email": email, "password": password}
        )
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "invalid_credentials"


# --- Refresh ---


def test_refresh_con_cookie_emite_nuevo_jwt(client: TestClient) -> None:
    _login(client, USER)

    response = client.post(f"{API_PREFIX}/auth/refresh")

    assert response.status_code == 200
    token = response.json()["access_token"]
    assert client.get(f"{API_PREFIX}/privada", headers=_bearer(token)).status_code == 200


def test_refresh_sin_cookie_o_con_token_de_acceso_se_rechaza(client: TestClient) -> None:
    assert client.post(f"{API_PREFIX}/auth/refresh").status_code == 401

    me = client.get(f"{API_PREFIX}/auth/me", headers=_bearer(_login(client, USER))).json()
    access = create_access_token(uuid.UUID(me["id"]))
    client.cookies.set("chatiapp_refresh", access, path="/api/v1/auth")
    assert client.post(f"{API_PREFIX}/auth/refresh").status_code == 401


def test_logout_borra_la_cookie(client: TestClient) -> None:
    _login(client, USER)

    response = client.post(f"{API_PREFIX}/auth/logout")

    assert response.status_code == 204
    assert client.post(f"{API_PREFIX}/auth/refresh").status_code == 401


# --- Bloqueo ---


def test_bloqueo_tras_cinco_intentos_fallidos(client: TestClient) -> None:
    for _ in range(5):
        response = client.post(
            f"{API_PREFIX}/auth/login", json={"email": USER[0], "password": "mala"}
        )
        assert response.status_code == 401

    # Ni siquiera la contraseña correcta entra mientras dura el bloqueo.
    response = client.post(
        f"{API_PREFIX}/auth/login", json={"email": USER[0], "password": USER[1]}
    )
    assert response.status_code == 429
    assert response.json()["error"]["code"] == "too_many_attempts"

    # Otro correo no se ve afectado.
    assert _login(client, ADMIN)


def test_throttle_expira_la_ventana(monkeypatch: pytest.MonkeyPatch) -> None:
    now = [1000.0]
    monkeypatch.setattr("app.security.auth.time.monotonic", lambda: now[0])
    throttle = LoginThrottle(max_attempts=5, window_seconds=900)
    for _ in range(5):
        throttle.register_failure("a@b.c")
    assert throttle.retry_after("a@b.c") > 0

    now[0] += 901

    assert throttle.retry_after("a@b.c") == 0


def test_login_correcto_reinicia_el_contador(client: TestClient) -> None:
    for _ in range(4):
        client.post(f"{API_PREFIX}/auth/login", json={"email": USER[0], "password": "mala"})
    _login(client, USER)
    for _ in range(4):
        client.post(f"{API_PREFIX}/auth/login", json={"email": USER[0], "password": "mala"})

    assert _login(client, USER)


# --- Acceso por ruta ---


def test_rutas_publicas_sin_token(client: TestClient) -> None:
    assert client.get(f"{API_PREFIX}/health").status_code == 200
    assert client.get(f"{API_PREFIX}/docs").status_code == 200


def test_ruta_privada_sin_token_es_401(client: TestClient) -> None:
    for path in ("/privada", "/admin", "/auth/me"):
        response = client.get(f"{API_PREFIX}{path}")
        assert response.status_code == 401, path
        assert response.json()["error"]["code"] == "not_authenticated"


def test_ruta_privada_con_token_invalido_es_401(client: TestClient) -> None:
    for token in ("basura", create_refresh_token(uuid.uuid4())):
        response = client.get(f"{API_PREFIX}/privada", headers=_bearer(token))
        assert response.status_code == 401


def test_token_expirado_es_401(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    token = _login(client, USER)
    monkeypatch.setattr("app.security.auth.ACCESS_TTL", timedelta(0))
    expired = create_access_token(uuid.uuid4())

    assert client.get(f"{API_PREFIX}/privada", headers=_bearer(expired)).status_code == 401
    assert client.get(f"{API_PREFIX}/privada", headers=_bearer(token)).status_code == 200


def test_usuario_normal_accede_a_privada_pero_no_a_admin(client: TestClient) -> None:
    headers = _bearer(_login(client, USER))

    assert client.get(f"{API_PREFIX}/privada", headers=headers).status_code == 200
    denied = client.get(f"{API_PREFIX}/admin", headers=headers)
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "forbidden"


def test_administrador_accede_a_todo(client: TestClient) -> None:
    headers = _bearer(_login(client, ADMIN))

    assert client.get(f"{API_PREFIX}/privada", headers=headers).status_code == 200
    assert client.get(f"{API_PREFIX}/admin", headers=headers).status_code == 200


def test_token_de_usuario_borrado_es_401(client: TestClient, engine: Engine) -> None:
    headers = _bearer(_login(client, USER))
    with Session(engine) as session:
        session.delete(session.query(User).filter_by(email=USER[0]).one())
        session.commit()

    assert client.get(f"{API_PREFIX}/privada", headers=headers).status_code == 401


# --- Administrador inicial ---


def test_administrador_inicial_se_crea_una_vez(
    engine: Engine, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fresh = make_engine(f"sqlite:///{tmp_path / 'vacia.db'}")
    Base.metadata.create_all(fresh)
    monkeypatch.setenv("CHATIAPP_ADMIN_EMAIL", "Root@Example.com")
    monkeypatch.setenv("CHATIAPP_ADMIN_PASSWORD", "inicial-123")

    with Session(fresh) as session:
        created = ensure_initial_admin(session)
        assert created is not None
        assert created.email == "root@example.com"
        assert created.is_admin
        assert verify_password("inicial-123", created.password_hash)
        assert ensure_initial_admin(session) is None
        assert session.query(User).count() == 1
    fresh.dispose()


def test_sin_variables_no_se_crea_administrador(
    engine: Engine, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fresh = make_engine(f"sqlite:///{tmp_path / 'vacia.db'}")
    Base.metadata.create_all(fresh)
    monkeypatch.delenv("CHATIAPP_ADMIN_EMAIL", raising=False)
    monkeypatch.delenv("CHATIAPP_ADMIN_PASSWORD", raising=False)

    with Session(fresh) as session:
        assert ensure_initial_admin(session) is None
        assert session.query(User).count() == 0
    fresh.dispose()


def test_no_crea_administrador_si_ya_existe_uno(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CHATIAPP_ADMIN_EMAIL", "otro@example.com")
    monkeypatch.setenv("CHATIAPP_ADMIN_PASSWORD", "inicial-123")

    with Session(engine) as session:
        assert ensure_initial_admin(session) is None
        assert session.query(User).count() == 2
