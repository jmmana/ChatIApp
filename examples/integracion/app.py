"""App anfitriona de ejemplo: integra el chat de ChatIApp (docs/INTEGRACION.md).

Tiene su propio login de prueba, el endpoint `POST /chatiapp-token` y una página con
`<chatiapp-chat>`. La API key vive solo en este servidor: el navegador recibe únicamente la
página, el script del widget y un token de sesión de 15 minutos.

    uvicorn app:app --port 8000
"""

import base64
import hashlib
import hmac
import html
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

COOKIE = "anfitriona_sesion"
ROLE = "gerente_sucursal"  # rol del modelo semántico de la demo; la key lo fija además

# Usuarios de prueba de ESTA app (no son usuarios de ChatIApp). Cada uno ve sus sucursales.
USERS: dict[str, dict[str, Any]] = {
    "ana": {"password": "clave-ana-1234", "name": "Ana", "branch_ids": [1]},
    "bruno": {"password": "clave-bruno-1234", "name": "Bruno", "branch_ids": [2]},
}


@dataclass(frozen=True)
class Settings:
    chatiapp_url: str  # cómo llega ESTE servidor a ChatIApp (red interna)
    public_url: str  # cómo llega el NAVEGADOR a ChatIApp
    api_key: str
    datasource: str  # UUID o id de la fuente
    origin: str  # origen desde el que el navegador abre esta app
    secret: str = "secreto-de-la-sesion-de-ejemplo"


def _read(env: str, default: str = "") -> str:
    """Valor de `VAR`, o el contenido del archivo de `VAR_FILE` (p. ej. un secreto montado)."""
    path = os.environ.get(f"{env}_FILE")
    if path:
        return Path(path).read_text(encoding="utf-8").strip()
    return os.environ.get(env, default)


def settings_from_env() -> Settings:
    chatiapp_url = os.environ.get("CHATIAPP_URL", "http://localhost:8080").rstrip("/")
    return Settings(
        chatiapp_url=chatiapp_url,
        public_url=os.environ.get("CHATIAPP_PUBLIC_URL", chatiapp_url).rstrip("/"),
        api_key=_read("CHATIAPP_API_KEY"),
        datasource=_read("CHATIAPP_DATASOURCE", "ventas"),
        origin=os.environ.get("HOST_ORIGIN", "http://localhost:8000"),
        secret=os.environ.get("HOST_SECRET", Settings.secret),
    )


def _sign(secret: str, payload: str) -> str:
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def make_cookie(secret: str, username: str) -> str:
    payload = base64.urlsafe_b64encode(username.encode()).decode()
    return f"{payload}.{_sign(secret, payload)}"


def read_cookie(secret: str, value: str | None) -> str | None:
    """Usuario de una cookie firmada; `None` si falta, está alterada o ya no existe."""
    payload, _, signature = (value or "").partition(".")
    if not hmac.compare_digest(signature, _sign(secret, payload)):
        return None
    try:
        username = base64.urlsafe_b64decode(payload.encode()).decode()
    except ValueError:
        return None
    return username if username in USERS else None


LOGIN_PAGE = """<!doctype html>
<html lang="es"><meta charset="utf-8"><title>Portal de ejemplo · Entrar</title>
<body style="font-family:system-ui;max-width:24rem;margin:3rem auto">
<h1>Portal de ejemplo</h1>
<p>Usuarios de prueba: <code>ana</code> (sucursal 1) y <code>bruno</code> (sucursal 2).</p>
{error}
<form method="post" action="/login">
  <p><label>Usuario <input name="username" autofocus required></label></p>
  <p><label>Contraseña <input name="password" type="password" required></label></p>
  <button>Entrar</button>
</form></body></html>"""

CHAT_PAGE = """<!doctype html>
<html lang="es"><meta charset="utf-8"><title>Portal de ejemplo</title>
<script src="{public_url}/embed/v1/chatiapp.js" defer></script>
<body style="font-family:system-ui;max-width:56rem;margin:2rem auto">
<header style="display:flex;justify-content:space-between;align-items:center">
  <h1>Hola, {name}</h1>
  <form method="post" action="/logout"><button>Salir</button></form>
</header>
<p>Tus sucursales: {branches}. El chat solo responde con los datos de ellas.</p>
<chatiapp-chat id="chat" base-url="{public_url}" lang="es" theme="auto" show-sql="true"
  style="display:block;height:32rem"></chatiapp-chat>
<script>
  document.getElementById("chat").getToken = async () => {{
    const r = await fetch("/chatiapp-token", {{ method: "POST", credentials: "include" }});
    if (!r.ok) throw new Error("No se pudo obtener el token del chat");
    return (await r.json()).token;
  }};
</script></body></html>"""


def create_app(settings: Settings, transport: httpx.BaseTransport | None = None) -> FastAPI:
    """`transport` permite probar sin red (las pruebas lo conectan a ChatIApp en memoria)."""
    app = FastAPI(title="App anfitriona de ejemplo", docs_url=None, redoc_url=None)

    def current_user(request: Request) -> str | None:
        return read_cookie(settings.secret, request.cookies.get(COOKIE))

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request) -> str:
        username = current_user(request)
        if username is None:
            return LOGIN_PAGE.format(error="")
        user = USERS[username]
        branches = ", ".join(str(b) for b in user["branch_ids"])
        return CHAT_PAGE.format(
            public_url=html.escape(settings.public_url, quote=True),
            name=html.escape(str(user["name"])),
            branches=branches,
        )

    @app.post("/login")
    async def login(request: Request) -> Response:
        form = parse_qs((await request.body()).decode())
        username = form.get("username", [""])[0]
        password = form.get("password", [""])[0]
        user = USERS.get(username)
        if user is None or not hmac.compare_digest(str(user["password"]), password):
            error = '<p style="color:#b91c1c">Usuario o contraseña incorrectos.</p>'
            return HTMLResponse(LOGIN_PAGE.format(error=error), status_code=401)
        response = RedirectResponse("/", status_code=303)
        response.set_cookie(
            COOKIE, make_cookie(settings.secret, username), httponly=True, samesite="lax"
        )
        return response

    @app.post("/logout")
    def logout() -> Response:
        response = RedirectResponse("/", status_code=303)
        response.delete_cookie(COOKIE)
        return response

    @app.post("/chatiapp-token")
    def chatiapp_token(request: Request) -> dict[str, str]:
        """Cambia la API key por un token de sesión del usuario que tiene sesión AQUÍ."""
        username = current_user(request)
        if username is None:
            raise HTTPException(401, "Inicia sesión primero.")
        with httpx.Client(transport=transport, timeout=30) as client:
            try:
                r = client.post(
                    f"{settings.chatiapp_url}/api/v1/embed/sessions",
                    headers={"Authorization": f"Bearer {settings.api_key}"},
                    json={
                        "datasource": settings.datasource,
                        "origin": settings.origin,
                        "user": {
                            "id": username,
                            "role": ROLE,
                            "attributes": {"sucursales": USERS[username]["branch_ids"]},
                        },
                    },
                )
            except httpx.HTTPError as exc:
                raise HTTPException(502, "ChatIApp no responde.") from exc
        if r.status_code != 200:
            # Sin reenviar el cuerpo: es un detalle del servidor, no del navegador.
            raise HTTPException(502, f"ChatIApp rechazó la sesión ({r.status_code}).")
        return {"token": str(r.json()["token"])}

    return app


def __getattr__(name: str) -> FastAPI:
    """`uvicorn app:app` construye la app con el entorno solo cuando se la pide."""
    if name == "app":
        return create_app(settings_from_env())
    raise AttributeError(name)
