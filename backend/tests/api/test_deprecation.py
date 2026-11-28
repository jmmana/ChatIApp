from datetime import UTC, date, datetime, time
from email.utils import format_datetime

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.api.deprecation import deprecation_headers


def test_endpoint_deprecado_incluye_cabeceras_y_metadatos_openapi() -> None:
    deprecated_on = date(2026, 1, 15)
    sunset = date(2026, 7, 15)
    application = FastAPI()
    application.get(
        "/legacy",
        deprecated=True,
        dependencies=[Depends(deprecation_headers(deprecated_on=deprecated_on, sunset=sunset))],
    )(lambda: {"status": "ok"})
    client = TestClient(application)

    response = client.get("/legacy")
    deprecated_at = datetime.combine(deprecated_on, time(), tzinfo=UTC)
    sunset_at = datetime.combine(sunset, time(23, 59, 59), tzinfo=UTC)

    assert response.status_code == 200
    assert response.headers["deprecation"] == f"@{int(deprecated_at.timestamp())}"
    assert response.headers["sunset"] == format_datetime(sunset_at, usegmt=True)
    assert application.openapi()["paths"]["/legacy"]["get"]["deprecated"] is True


def test_deprecacion_exige_seis_meses_de_aviso() -> None:
    with pytest.raises(ValueError, match="seis meses"):
        deprecation_headers(deprecated_on=date(2026, 1, 31), sunset=date(2026, 7, 30))
