"""Límites de uso: turnos por usuario y por API key, y presupuesto mensual de IA.

Contrato en docs/SEGURIDAD.md.

- Turnos por minuto y por día, por usuario; peticiones por minuto, por API key. Ventana deslizante
  en memoria, por proceso (como el límite de inicios de sesión). Al superarlo: 429 con
  `Retry-After` y el tiempo de espera en el mensaje.
- Presupuesto mensual en USD por proveedor (`params["monthly_budget_usd"]`) y por API key
  (`monthly_budget_usd`). Se mide con el costo de `QueryRun` del mes en curso (UTC). Al 80 % queda
  un aviso para administración; al 100 % se usa el respaldo (`params["fallback"]`) o se detiene.
"""

import logging
import math
import os
import threading
import time
import uuid
from collections import defaultdict, deque
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.orm import InstrumentedAttribute, Session

from app.db.models import ApiKey, Provider, QueryRun
from app.integrations.api_keys import Principal
from app.security.auth import AuthError

logger = logging.getLogger(__name__)

BUDGET_WARNING_RATIO = Decimal("0.8")
DEFAULT_TURNS_PER_MINUTE = 20
DEFAULT_TURNS_PER_DAY = 500
MINUTE = 60.0
DAY = 86_400.0

ENV_TURNS_PER_MINUTE = "CHATIAPP_LIMIT_TURNS_PER_MINUTE"
ENV_TURNS_PER_DAY = "CHATIAPP_LIMIT_TURNS_PER_DAY"

BudgetLevel = Literal["ok", "warning", "exceeded"]


class LimitError(AuthError):
    """Un límite de uso se superó: 429 con los segundos de espera cuando aplica."""

    def __init__(self, code: str, message: str, retry_after: int | None = None) -> None:
        super().__init__(429, code, message)
        self.retry_after = retry_after


# --- Turnos por minuto y por día --------------------------------------------------------------


@dataclass(frozen=True)
class UsageLimits:
    """Límites por usuario; `None` desactiva el límite correspondiente."""

    turns_per_minute: int | None = DEFAULT_TURNS_PER_MINUTE
    turns_per_day: int | None = DEFAULT_TURNS_PER_DAY

    @classmethod
    def from_env(cls) -> "UsageLimits":
        """Lee `CHATIAPP_LIMIT_TURNS_PER_MINUTE` y `..._PER_DAY`; `0` desactiva el límite."""
        return cls(
            _env_limit(ENV_TURNS_PER_MINUTE, DEFAULT_TURNS_PER_MINUTE),
            _env_limit(ENV_TURNS_PER_DAY, DEFAULT_TURNS_PER_DAY),
        )


def _env_limit(name: str, default: int) -> int | None:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(f"{name} debe ser un entero.") from None
    if value < 0:
        raise ValueError(f"{name} no puede ser negativo.")
    return value or None


class RateLimiter:
    """Ventana deslizante por clave (en memoria, por proceso)."""

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _prune(self, key: str, window: float, now: float) -> deque[float]:
        hits = self._hits[key]
        while hits and now - hits[0] >= window:
            hits.popleft()
        return hits

    def acquire(self, rules: Iterable[tuple[str, int, float]], *, now: float | None = None) -> int:
        """Cuenta una petición contra todas las reglas `(clave, máximo, ventana_s)`.

        Si alguna está agotada no cuenta nada y devuelve los segundos de espera (la mayor); si
        no, cuenta en todas y devuelve 0. Todo ocurre bajo un candado: las peticiones en
        paralelo no consiguen más cupo.
        """
        now = time.monotonic() if now is None else now
        rules = list(rules)
        with self._lock:
            wait = 0
            for key, maximum, window in rules:
                hits = self._prune(key, window, now)
                if len(hits) >= maximum:
                    wait = max(wait, max(1, math.ceil(hits[0] + window - now)))
            if wait:
                return wait
            for key, _maximum, _window in rules:
                self._hits[key].append(now)
            return 0

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


_limiter = RateLimiter()


def get_limiter() -> RateLimiter:
    return _limiter


def _format_wait(seconds: int) -> str:
    return f"Reintenta en {seconds} s."


def check_turn(
    principal: Principal,
    limiter: RateLimiter | None = None,
    limits: UsageLimits | None = None,
    *,
    now: float | None = None,
) -> None:
    """Cuenta un turno del principal o lanza `LimitError` 429 con el tiempo de espera.

    Usuario: turnos por minuto y por día. API key: sus peticiones por minuto
    (`rate_limit_per_minute`; sin valor, sin límite propio).
    """
    limiter = limiter or get_limiter()
    rules: list[tuple[str, int, float]] = []
    if principal.api_key is not None:
        per_minute = principal.api_key.rate_limit_per_minute
        if per_minute is not None:
            rules.append((f"key:{principal.api_key.id}:min", per_minute, MINUTE))
    elif principal.user is not None:
        limits = limits or UsageLimits.from_env()
        if limits.turns_per_minute is not None:
            rules.append((f"user:{principal.user.id}:min", limits.turns_per_minute, MINUTE))
        if limits.turns_per_day is not None:
            rules.append((f"user:{principal.user.id}:day", limits.turns_per_day, DAY))
    wait = limiter.acquire(rules, now=now)
    if wait:
        raise LimitError(
            "rate_limited", f"Límite de uso superado. {_format_wait(wait)}", retry_after=wait
        )


# --- Presupuesto mensual ----------------------------------------------------------------------


@dataclass(frozen=True)
class BudgetStatus:
    spent: Decimal
    budget: Decimal | None
    level: BudgetLevel

    @property
    def ratio(self) -> Decimal | None:
        if not self.budget:
            return None
        return self.spent / self.budget


def month_start(now: datetime | None = None) -> datetime:
    now = now or datetime.now(UTC)
    return datetime(now.year, now.month, 1, tzinfo=UTC)


def budget_level(spent: Decimal, budget: Decimal | None) -> BudgetLevel:
    if budget is None:
        return "ok"
    if spent >= budget:
        return "exceeded"
    if spent >= budget * BUDGET_WARNING_RATIO:
        return "warning"
    return "ok"


def _spent(
    session: Session,
    column: InstrumentedAttribute[uuid.UUID | None],
    value: uuid.UUID,
    now: datetime | None,
) -> Decimal:
    total = session.scalar(
        select(func.coalesce(func.sum(QueryRun.cost_usd), 0)).where(
            column == value, QueryRun.created_at >= month_start(now)
        )
    )
    return Decimal(str(total or 0))


def provider_budget(provider: Provider) -> Decimal | None:
    """Presupuesto mensual en USD guardado en `params`; `None` si no tiene."""
    raw = (provider.params or {}).get("monthly_budget_usd")
    if raw is None or raw == "":
        return None
    try:
        return Decimal(str(raw))
    except InvalidOperation:
        return None


def provider_status(
    session: Session, provider: Provider, *, now: datetime | None = None
) -> BudgetStatus:
    budget = provider_budget(provider)
    spent = _spent(session, QueryRun.provider_id, provider.id, now)
    return BudgetStatus(spent, budget, budget_level(spent, budget))


def api_key_status(
    session: Session, api_key: ApiKey, *, now: datetime | None = None
) -> BudgetStatus:
    budget = api_key.monthly_budget_usd
    spent = _spent(session, QueryRun.api_key_id, api_key.id, now)
    return BudgetStatus(spent, budget, budget_level(spent, budget))


def check_api_key_budget(session: Session, api_key: ApiKey, *, now: datetime | None = None) -> None:
    """Lanza `LimitError` 429 si la key ya gastó su presupuesto mensual."""
    status = api_key_status(session, api_key, now=now)
    if status.level == "exceeded":
        raise LimitError(
            "budget_exceeded", "La API key agotó su presupuesto mensual de IA.", retry_after=None
        )


@dataclass(frozen=True)
class ProviderChoice:
    provider: Provider
    status: BudgetStatus
    used_fallback: bool = False


def budget_alerts(
    session: Session, providers: Iterable[Provider], *, now: datetime | None = None
) -> list[tuple[Provider, BudgetStatus]]:
    """Proveedores al 80 % o más de su presupuesto, para mostrarlos en administración."""
    alerts: list[tuple[Provider, BudgetStatus]] = []
    for provider in providers:
        status = provider_status(session, provider, now=now)
        if status.level != "ok":
            alerts.append((provider, status))
    return alerts


def _fallback_order(provider: Provider) -> int | None:
    value = (provider.params or {}).get("fallback")
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def choose_provider(
    session: Session,
    primary: Provider,
    providers: Iterable[Provider],
    *,
    now: datetime | None = None,
) -> ProviderChoice:
    """Elige el proveedor a usar según el presupuesto.

    Con `primary` por debajo del 100 % lo devuelve (con aviso en el log desde el 80 %). Si lo
    agotó, recorre la cadena de respaldo en orden y devuelve el primero con presupuesto; si
    ninguno sirve, lanza `LimitError` 429 `budget_exceeded` (se detiene).
    """
    status = provider_status(session, primary, now=now)
    if status.level != "exceeded":
        if status.level == "warning":
            logger.warning("Proveedor %s al %.0f %% de su presupuesto", primary.name, _pct(status))
        return ProviderChoice(primary, status)
    logger.warning("Proveedor %s agotó su presupuesto mensual", primary.name)
    chain = sorted(
        (p for p in providers if p.id != primary.id and _fallback_order(p) is not None),
        key=lambda p: _fallback_order(p) or 0,
    )
    for candidate in chain:
        candidate_status = provider_status(session, candidate, now=now)
        if candidate_status.level != "exceeded":
            return ProviderChoice(candidate, candidate_status, used_fallback=True)
    raise LimitError(
        "budget_exceeded", "El presupuesto mensual de IA se agotó y no hay respaldo disponible."
    )


def _pct(status: BudgetStatus) -> float:
    return float((status.ratio or Decimal(0)) * 100)
