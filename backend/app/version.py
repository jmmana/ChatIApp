"""Versión del backend, tomada de los metadatos del paquete (`pyproject.toml`)."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("chatiapp-backend")
except PackageNotFoundError:  # pragma: no cover - solo sin instalar el paquete
    __version__ = "0.0.0"
