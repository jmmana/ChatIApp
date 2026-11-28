"""Sirve la interfaz web compilada desde la misma app (docs/adr/0008-imagen-unica-con-sqlite.md).

- `/assets/...` son los archivos con hash que genera Vite.
- Cualquier otra ruta GET que no sea de la API y no exista devuelve `index.html`, para que el
  enrutador de React resuelva `/chat`, `/modelo-semantico`, etc.
- Las rutas `/api/...` desconocidas siguen respondiendo 404 en JSON.
"""

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

API_ROOT = "/api"
ASSETS_ROOT = "/assets"
EMBED_ROOT = "/embed"


def _under(path: str, root: str) -> bool:
    return path == root or path.startswith(f"{root}/")


def mount_web(app: FastAPI, static_dir: Path) -> bool:
    """Monta la interfaz si `static_dir` tiene un `index.html`. Devuelve si la montó."""
    root = static_dir.resolve()
    index = root / "index.html"
    if not index.is_file():
        return False

    assets = root / "assets"
    if assets.is_dir():
        app.mount(ASSETS_ROOT, StaticFiles(directory=assets), name="web-assets")

    async def spa_fallback(request: Request, exc: Exception) -> Response:
        if not isinstance(exc, StarletteHTTPException):
            raise exc
        path = request.url.path
        # La API, los assets con hash y el widget no caen en index.html: un 404 ahí es un 404 real.
        if (
            exc.status_code != 404
            or request.method not in ("GET", "HEAD")
            or _under(path, API_ROOT)
            or _under(path, ASSETS_ROOT)
            or _under(path, EMBED_ROOT)
        ):
            return await http_exception_handler(request, exc)
        candidate = (root / path.lstrip("/")).resolve()
        if candidate != root and candidate.is_relative_to(root) and candidate.is_file():
            return FileResponse(candidate)
        # index.html no lleva hash: se revalida siempre para tomar la versión nueva.
        return FileResponse(index, headers={"Cache-Control": "no-cache"})

    app.add_exception_handler(StarletteHTTPException, spa_fallback)
    return True
