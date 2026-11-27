"""Recurso público del componente web para integrar el chat."""

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

router = APIRouter(tags=["embed"])
WIDGET_PATH = Path(__file__).parents[1] / "static" / "chatiapp.js"


@router.get("/embed/v1/chatiapp.js", include_in_schema=False)
def widget_script() -> FileResponse:
    return FileResponse(WIDGET_PATH, media_type="application/javascript")
