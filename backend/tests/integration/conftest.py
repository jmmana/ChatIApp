"""Pruebas de integración contra PostgreSQL, MySQL y SQL Server reales.

Cada motor se activa con su variable de entorno (``CHATIAPP_IT_POSTGRES_URL``,
``CHATIAPP_IT_MYSQL_URL``, ``CHATIAPP_IT_TSQL_URL``); sin ella sus pruebas se omiten, así que
``pytest`` a secas sigue funcionando sin servicios. Las URL apuntan a una base vacía (en SQL Server,
al servidor: la base se crea sola). El generador de la demo carga en cada motor los mismos datos
que en SQLite, y SQLite es la referencia: todo resultado debe coincidir con el suyo.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest

from app.demo.seed import generar
from app.engine.dialects import Dialect
from app.semantic.schema import SemanticModel
from tests.integration.helpers import (
    HASTA,
    SEMILLA,
    VARIABLES,
    Motor,
    cargar_demo,
    cargar_modelo,
    cerrar_pools,
    preparar_url,
    url_configurada,
)

_CARGADOS: dict[Dialect, Motor] = {}


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if "tests/integration/" in item.nodeid.replace("\\", "/"):
            item.add_marker(pytest.mark.integration)


def motor_cargado(dialect: Dialect) -> Motor:
    """Carga la demo una sola vez por motor y por sesión; omite la prueba si no hay URL."""
    if dialect in _CARGADOS:
        return _CARGADOS[dialect]
    url = url_configurada(dialect)
    if url is None:
        pytest.skip(f"Define {VARIABLES[dialect]} para probar contra {dialect}")
    motor = Motor(dialect, preparar_url(dialect, url))
    cargar_demo(motor)
    _CARGADOS[dialect] = motor
    return motor


@pytest.fixture(scope="session", params=list(VARIABLES))
def motor(request: pytest.FixtureRequest) -> Motor:
    return motor_cargado(request.param)


@pytest.fixture(scope="session")
def sqlserver() -> Motor:
    return motor_cargado("tsql")


@pytest.fixture(scope="session")
def sqlite(tmp_path_factory: pytest.TempPathFactory) -> Motor:
    ruta: Path = tmp_path_factory.mktemp("integracion") / "ventas.db"
    generar(ruta, seed=SEMILLA, hasta=HASTA)
    return Motor("sqlite", f"sqlite:///{ruta}")


@pytest.fixture(scope="session")
def modelo() -> SemanticModel:
    return cargar_modelo()


@pytest.fixture(scope="session", autouse=True)
def _cerrar_pools() -> Iterator[None]:
    yield
    cerrar_pools()
