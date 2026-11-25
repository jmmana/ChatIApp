"""Endpoint de salud."""

from fastapi import APIRouter
from pydantic import BaseModel

from app.version import __version__

router = APIRouter(tags=["salud"])


class HealthResponse(BaseModel):
    status: str
    version: str


@router.get("/health", summary="Estado y versión del servicio")
def health() -> HealthResponse:
    return HealthResponse(status="ok", version=__version__)
