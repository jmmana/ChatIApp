"""Endpoints de proveedores de IA."""

from fastapi import APIRouter

from app.llm.catalog import CATALOG, ProviderSpec

router = APIRouter(prefix="/providers", tags=["proveedores"])


@router.get("/catalog", summary="Catálogo de proveedores de IA")
def get_catalog() -> list[ProviderSpec]:
    return list(CATALOG)
