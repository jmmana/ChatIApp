"""Marca de endpoints obsoletos: cabeceras `Deprecation` y `Sunset` (docs/INTEGRACION.md).

Uso en una ruta:

    @router.get("/viejo", **deprecated_route(sunset=date(2027, 6, 1)))

Además de las cabeceras en cada respuesta, la ruta queda con `deprecated: true` en OpenAPI.
"""

from collections.abc import Callable
from datetime import UTC, date, datetime, time
from email.utils import format_datetime
from typing import Any

from fastapi import Depends, Response

# Aviso mínimo entre anunciar el retiro y que ocurra (docs/INTEGRACION.md#versionado-de-la-api).
MIN_NOTICE_DAYS = 183


def deprecation_headers(sunset: date, deprecated_since: date | None = None) -> dict[str, str]:
    """Cabeceras `Deprecation` (RFC 9745, `@<epoch>`) y `Sunset` (RFC 8594, fecha HTTP)."""
    since = deprecated_since or datetime.now(UTC).date()
    if sunset <= since:
        raise ValueError("La fecha de retiro (Sunset) debe ser posterior a la de obsolescencia")
    since_dt = datetime.combine(since, time.min, tzinfo=UTC)
    sunset_dt = datetime.combine(sunset, time.min, tzinfo=UTC)
    return {
        "Deprecation": f"@{int(since_dt.timestamp())}",
        "Sunset": format_datetime(sunset_dt, usegmt=True),
    }


def deprecated_route(sunset: date, deprecated_since: date | None = None) -> dict[str, Any]:
    """Argumentos para el decorador de la ruta: la marca como obsoleta y agrega las cabeceras."""
    headers = deprecation_headers(sunset, deprecated_since)

    def add_headers(response: Response) -> None:
        response.headers.update(headers)

    dependency: Callable[[Response], None] = add_headers
    return {"deprecated": True, "dependencies": [Depends(dependency)]}
