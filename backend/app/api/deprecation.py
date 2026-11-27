"""Utilidades para anunciar la retirada de endpoints."""

import calendar
from collections.abc import Callable
from datetime import date, datetime, time, timezone
from email.utils import format_datetime

from fastapi import Response


def _add_months(value: date, months: int) -> date:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def deprecation_headers(*, deprecated_on: date, sunset: date) -> Callable[[Response], None]:
    """Crea una dependencia que anuncia la retirada con al menos seis meses de aviso."""
    if sunset < _add_months(deprecated_on, 6):
        raise ValueError("Sunset debe ser al menos seis meses posterior a la fecha de deprecación")

    deprecated_at = datetime.combine(deprecated_on, time(), tzinfo=timezone.utc)
    sunset_at = datetime.combine(sunset, time(23, 59, 59), tzinfo=timezone.utc)

    def add_headers(response: Response) -> None:
        response.headers["Deprecation"] = f"@{int(deprecated_at.timestamp())}"
        response.headers["Sunset"] = format_datetime(sunset_at, usegmt=True)

    return add_headers
