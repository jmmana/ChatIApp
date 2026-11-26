import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.db.models import (
    ApiKey,
    Base,
    Conversation,
    Datasource,
    Message,
    Provider,
    QueryRun,
    User,
)
from app.db.session import make_engine
from app.integrations.api_keys import Principal
from app.security.limits import (
    LimitError,
    RateLimiter,
    UsageLimits,
    api_key_status,
    budget_alerts,
    budget_level,
    check_api_key_budget,
    check_turn,
    choose_provider,
    month_start,
)


def _user_principal() -> Principal:
    return Principal("user", frozenset(), user=User(id=uuid.uuid4(), email="a@x.com"))


def _key_principal(per_minute: int | None) -> Principal:
    key = ApiKey(id=uuid.uuid4(), name="k", rate_limit_per_minute=per_minute)
    return Principal("api_key", frozenset({"chat"}), api_key=key)


# --- Turnos por minuto y por día --------------------------------------------------------------


def test_turnos_por_minuto_responde_429_con_espera() -> None:
    limiter = RateLimiter()
    principal = _user_principal()
    limits = UsageLimits(turns_per_minute=2, turns_per_day=None)
    check_turn(principal, limiter, limits, now=100.0)
    check_turn(principal, limiter, limits, now=110.0)
    with pytest.raises(LimitError) as info:
        check_turn(principal, limiter, limits, now=120.0)
    assert info.value.status_code == 429
    assert info.value.retry_after == 40  # el primer turno sale de la ventana en t=160
    assert "40 s" in info.value.message
    check_turn(principal, limiter, limits, now=160.0)


def test_turnos_por_dia() -> None:
    limiter = RateLimiter()
    principal = _user_principal()
    limits = UsageLimits(turns_per_minute=None, turns_per_day=3)
    for i in range(3):
        check_turn(principal, limiter, limits, now=1000.0 + i * 3600)
    with pytest.raises(LimitError) as info:
        check_turn(principal, limiter, limits, now=1000.0 + 3 * 3600)
    assert info.value.retry_after == 86_400 - 3 * 3600
    check_turn(principal, limiter, limits, now=1000.0 + 86_400)


def test_el_rechazo_no_consume_cupo_y_los_usuarios_son_independientes() -> None:
    limiter = RateLimiter()
    ana, beto = _user_principal(), _user_principal()
    limits = UsageLimits(turns_per_minute=1, turns_per_day=10)
    check_turn(ana, limiter, limits, now=0.0)
    for t in (1.0, 2.0):
        with pytest.raises(LimitError):
            check_turn(ana, limiter, limits, now=t)
    check_turn(beto, limiter, limits, now=3.0)
    check_turn(ana, limiter, limits, now=60.0)


def test_limites_desde_el_entorno(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHATIAPP_LIMIT_TURNS_PER_MINUTE", "5")
    monkeypatch.setenv("CHATIAPP_LIMIT_TURNS_PER_DAY", "0")
    assert UsageLimits.from_env() == UsageLimits(turns_per_minute=5, turns_per_day=None)
    monkeypatch.setenv("CHATIAPP_LIMIT_TURNS_PER_MINUTE", "mucho")
    with pytest.raises(ValueError):
        UsageLimits.from_env()


def test_api_key_aplica_su_limite_por_minuto() -> None:
    limiter = RateLimiter()
    limited, free = _key_principal(2), _key_principal(None)
    check_turn(limited, limiter, now=0.0)
    check_turn(limited, limiter, now=1.0)
    with pytest.raises(LimitError) as info:
        check_turn(limited, limiter, now=2.0)
    assert info.value.retry_after == 58
    for t in range(50):
        check_turn(free, limiter, now=float(t))


# --- Presupuesto mensual ----------------------------------------------------------------------


@pytest.fixture
def session(tmp_path: Path) -> Iterator[Session]:
    engine: Engine = make_engine(f"sqlite:///{tmp_path / 'app.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s
    engine.dispose()


def _provider(session: Session, name: str, **params: Any) -> Provider:
    provider = Provider(name=name, kind="fake", model="m", params=params)
    session.add(provider)
    session.commit()
    return provider


def _spend(
    session: Session,
    cost: str,
    *,
    provider: Provider | None = None,
    api_key: ApiKey | None = None,
    when: datetime | None = None,
) -> None:
    datasource = session.query(Datasource).first()
    if datasource is None:
        datasource = Datasource(name="demo", dialect="sqlite", url_encrypted=b"x")
        session.add(datasource)
        session.flush()
    conversation = Conversation(datasource_id=datasource.id)
    message = Message(conversation=conversation, role="assistant", content="")
    session.add_all([conversation, message])
    session.flush()
    session.add(
        QueryRun(
            message_id=message.id,
            provider_id=provider.id if provider else None,
            api_key_id=api_key.id if api_key else None,
            origin="llm",
            status="ok",
            cost_usd=Decimal(cost),
            created_at=when or datetime.now(UTC),
        )
    )
    session.commit()


def test_niveles_de_presupuesto() -> None:
    budget = Decimal(10)
    assert budget_level(Decimal("7.99"), budget) == "ok"
    assert budget_level(Decimal(8), budget) == "warning"
    assert budget_level(Decimal("9.99"), budget) == "warning"
    assert budget_level(Decimal(10), budget) == "exceeded"
    assert budget_level(Decimal(1000), None) == "ok"


def test_al_80_por_ciento_avisa_y_sigue_con_el_proveedor(session: Session) -> None:
    primary = _provider(session, "claude", monthly_budget_usd=10)
    _spend(session, "8.5", provider=primary)
    choice = choose_provider(session, primary, [primary])
    assert choice.provider is primary
    assert not choice.used_fallback
    assert choice.status.level == "warning"
    alerts = budget_alerts(session, [primary])
    assert [(p.name, s.level) for p, s in alerts] == [("claude", "warning")]


def test_al_100_por_ciento_usa_el_respaldo(session: Session) -> None:
    primary = _provider(session, "claude", monthly_budget_usd=10)
    second = _provider(session, "local", fallback=1)
    first = _provider(session, "deepseek", fallback=0, monthly_budget_usd=5)
    _spend(session, "10", provider=primary)
    choice = choose_provider(session, primary, [primary, second, first])
    assert choice.provider is first and choice.used_fallback
    _spend(session, "5", provider=first)  # el primer respaldo también se agotó
    choice = choose_provider(session, primary, [primary, second, first])
    assert choice.provider is second and choice.used_fallback


def test_al_100_por_ciento_sin_respaldo_se_detiene(session: Session) -> None:
    primary = _provider(session, "claude", monthly_budget_usd=10)
    _spend(session, "10.5", provider=primary)
    with pytest.raises(LimitError) as info:
        choose_provider(session, primary, [primary])
    assert info.value.status_code == 429
    assert info.value.code == "budget_exceeded"


def test_el_gasto_de_meses_anteriores_no_cuenta(session: Session) -> None:
    primary = _provider(session, "claude", monthly_budget_usd=10)
    last_month = month_start() - timedelta(days=1)
    _spend(session, "50", provider=primary, when=last_month)
    assert choose_provider(session, primary, [primary]).status.level == "ok"


def test_proveedor_sin_presupuesto_nunca_se_limita(session: Session) -> None:
    primary = _provider(session, "local")
    _spend(session, "9999", provider=primary)
    assert choose_provider(session, primary, [primary]).status.level == "ok"


def test_presupuesto_mensual_por_api_key(session: Session) -> None:
    key = ApiKey(name="k", prefix="chia_abc", secret_hash="0" * 64, monthly_budget_usd=Decimal(2))
    other = ApiKey(name="o", prefix="chia_def", secret_hash="0" * 64)
    session.add_all([key, other])
    session.commit()
    _spend(session, "1.7", api_key=key)
    assert api_key_status(session, key).level == "warning"
    check_api_key_budget(session, key)
    _spend(session, "0.3", api_key=key)
    with pytest.raises(LimitError) as info:
        check_api_key_budget(session, key)
    assert info.value.code == "budget_exceeded"
    check_api_key_budget(session, other)  # sin presupuesto: sin límite
