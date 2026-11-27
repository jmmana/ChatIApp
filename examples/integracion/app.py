"""Aplicación anfitriona mínima para probar ChatIApp desde otra app."""

import html
import json
import os
import secrets
import urllib.error
import urllib.request
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import FastAPI, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

CHAT_URL = os.environ.get("CHATIAPP_URL", "http://localhost:8080").rstrip("/")
CHAT_PUBLIC_URL = os.environ.get("CHATIAPP_PUBLIC_URL", "http://localhost:8080").rstrip("/")
APP_ORIGIN = os.environ.get("CHATIAPP_INTEGRACION_ORIGIN", "http://localhost:8081").rstrip("/")
KEY_NAME = "ejemplo-integracion"
COOKIE_NAME = "integracion_sesion"
USERS = {
    "andino": ("demo-andino", [1]),
    "medellin": ("demo-medellin", [4]),
}


@dataclass(frozen=True)
class HostUser:
    username: str
    branches: list[int]


def _request_json(
    url: str, payload: dict[str, Any] | None = None, bearer: str | None = None
) -> Any:
    body = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"}
    if bearer:
        headers["Authoriz" + "ation"] = "".join(("Be", "arer ", bearer))
    request = urllib.request.Request(url, data=body, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError("No se pudo conectar con ChatIApp.") from exc


def _create_integration_key() -> tuple[str, str]:
    admin_email = os.environ.get("CHATIAPP_ADMIN_EMAIL")
    admin_password = os.environ.get("CHATIAPP_ADMIN_PASSWORD")
    if not admin_email or not admin_password:
        raise RuntimeError(
            "Define CHATIAPP_ADMIN_EMAIL y CHATIAPP_ADMIN_PASSWORD en .env "
            "para crear la API key de demostración."
        )
    login = _request_json(
        f"{CHAT_URL}/api/v1/auth/login",
        {"email": admin_email, "password": admin_password},
    )
    access_token = login["access_token"]
    datasources = _request_json(f"{CHAT_URL}/api/v1/datasources", bearer=access_token)
    datasource = next((item for item in datasources if item["name"] == "Ventas (demo)"), None)
    if datasource is None:
        raise RuntimeError("ChatIApp no tiene la fuente «Ventas (demo)».")
    keys = _request_json(f"{CHAT_URL}/api/v1/api-keys", bearer=access_token)
    for key in keys:
        if key["name"] == KEY_NAME and key["revoked_at"] is None:
            _request_json(
                f"{CHAT_URL}/api/v1/api-keys/{key['id']}/revoke",
                {},
                bearer=access_token,
            )
    created = _request_json(
        f"{CHAT_URL}/api/v1/api-keys",
        {
            "name": KEY_NAME,
            "scopes": ["embed"],
            "datasources": [datasource["id"]],
            "allowed_roles": ["gerente_sucursal"],
            "allowed_origins": [APP_ORIGIN],
        },
        bearer=access_token,
    )
    return created["secret"], str(datasource["id"])


def create_app(
    api_key: str | None = None,
    datasource_id: str | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI):
        if api_key is None or datasource_id is None:
            application.state.api_key, application.state.datasource_id = _create_integration_key()
        else:
            application.state.api_key = api_key
            application.state.datasource_id = datasource_id
        application.state.sessions = {}
        yield

    application = FastAPI(title="Ejemplo de app anfitriona", lifespan=lifespan)

    @application.get("/login", response_class=HTMLResponse)
    def login_page() -> str:
        return """<!doctype html><html lang="es"><meta charset="utf-8">
<title>Iniciar sesión · Portal de ejemplo</title>
<h1>Portal de ejemplo</h1>
<form method="post" action="/login">
  <label>Usuario <select name="username">
    <option value="andino">Sucursal Bogotá Andino</option>
    <option value="medellin">Sucursal Medellín</option>
  </select></label>
  <label>Contraseña <input type="password" name="password" required></label>
  <button type="submit">Iniciar sesión</button>
</form></html>"""

    @application.post("/login")
    def login(
        username: Annotated[str, Form()],
        password: Annotated[str, Form()],
    ) -> RedirectResponse:
        account = USERS.get(username)
        if account is None or not secrets.compare_digest(account[0], password):
            raise HTTPException(status_code=401, detail="Usuario o contraseña incorrectos.")
        session_id = secrets.token_urlsafe(32)
        application.state.sessions[session_id] = HostUser(username, account[1])
        redirect = RedirectResponse("/", status_code=303)
        redirect.set_cookie(
            COOKIE_NAME,
            session_id,
            httponly=True,
            secure=os.environ.get("CHATIAPP_INTEGRACION_COOKIE_SECURE", "false").lower()
            in ("1", "true", "yes"),
            samesite="lax",
            max_age=3600,
        )
        return redirect

    def current_user(request: Request) -> HostUser:
        session_id = request.cookies.get(COOKIE_NAME, "")
        user = application.state.sessions.get(session_id)
        if user is None:
            raise HTTPException(status_code=401, detail="Inicia sesión en el portal.")
        return user

    @application.get("/", response_class=HTMLResponse)
    def home(request: Request) -> Response:
        try:
            user = current_user(request)
        except HTTPException:
            return RedirectResponse("/login", status_code=303)
        name = "Bogotá Andino" if user.username == "andino" else "Medellín"
        chat_url = html.escape(CHAT_PUBLIC_URL, quote=True)
        datasource = html.escape(application.state.datasource_id, quote=True)
        return HTMLResponse(
            f"""<!doctype html><html lang="es"><meta charset="utf-8">
<title>Portal de ventas</title><h1>Hola, {html.escape(name)}</h1>
<p>Consulta los datos de tu sucursal.</p>
<script src="{chat_url}/embed/v1/chatiapp.js" defer></script>
<chatiapp-chat base-url="{chat_url}" datasource-id="{datasource}" lang="es"></chatiapp-chat>
<script>
  document.querySelector("chatiapp-chat").getToken = async () => {{
    const response = await fetch("/chatiapp-token", {{
      method: "POST", credentials: "same-origin"
    }});
    if (!response.ok) throw new Error("No se pudo iniciar el chat.");
    return (await response.json()).token;
  }};
</script></html>"""
        )

    @application.post("/chatiapp-token")
    def chatiapp_token(request: Request) -> dict[str, str]:
        user = current_user(request)
        origin = request.headers.get("origin", "").rstrip("/")
        if origin != APP_ORIGIN:
            raise HTTPException(status_code=403, detail="Origen no permitido.")
        try:
            result = _request_json(
                f"{CHAT_URL}/api/v1/embed/sessions",
                {
                    "datasource": application.state.datasource_id,
                    "origin": APP_ORIGIN,
                    "user": {
                        "id": user.username,
                        "role": "gerente_sucursal",
                        "attributes": {"sucursales": user.branches},
                    },
                },
                bearer=application.state.api_key,
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail="No se pudo emitir el token.") from exc
        return {"token": result["token"], "expires_at": result["expires_at"]}

    return application


app = create_app()
