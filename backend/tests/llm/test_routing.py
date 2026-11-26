from typing import Any

import pytest
from pydantic import BaseModel

from app.llm.gateway import Gateway, GatewayError, InvalidJsonError, ProviderConfig
from app.llm.routing import Candidate, Router, TaskGateway, should_fallback

MESSAGES = [{"role": "user", "content": "cuánto vendí hoy"}]


class Out(BaseModel):
    total: int


def _cand(name: str, **config: Any) -> Candidate:
    return Candidate(name, Gateway(ProviderConfig(kind="fake", model="fake-1", config=config)))


def _ok(name: str, text: str = "ok") -> Candidate:
    return _cand(name, responses=[text])


def _failing(name: str, error: str) -> Candidate:
    return _cand(name, error=error)


def test_sin_asignacion_usa_el_predeterminado() -> None:
    router = Router({}, default=_ok("claude", "hola"))
    assert [c.name for c in router.chain("answer")] == ["claude"]
    assert router.for_task("answer").complete(MESSAGES).text == "hola"


def test_cada_tarea_usa_su_proveedor() -> None:
    router = Router(
        {"planner": _ok("claude", "fuerte"), "answer": _ok("deepseek", "barato")},
        default=_ok("local", "local"),
    )
    assert router.for_task("planner").complete(MESSAGES).text == "fuerte"
    assert router.for_task("answer").complete(MESSAGES).text == "barato"
    assert router.for_task("suggest").complete(MESSAGES).text == "local"


def test_la_cadena_no_repite_proveedores() -> None:
    claude, deepseek = _ok("claude"), _ok("deepseek")
    router = Router({"sql": claude}, default=claude, fallback=[claude, deepseek])
    assert [c.name for c in router.chain("sql")] == ["claude", "deepseek"]


@pytest.mark.parametrize("kind", ["auth", "quota", "timeout", "network", "provider_error"])
def test_respalda_en_errores_del_proveedor(kind: str) -> None:
    gateway = TaskGateway([_failing("claude", kind), _ok("deepseek", "listo")])
    assert gateway.complete(MESSAGES).text == "listo"
    assert gateway.take_notices() == ["claude no respondió; usé deepseek"]
    assert gateway.take_notices() == []


def test_fallan_en_orden_hasta_uno_que_responde() -> None:
    gateway = TaskGateway(
        [_failing("claude", "auth"), _failing("deepseek", "quota"), _ok("local", "ya")]
    )
    assert gateway.complete(MESSAGES).text == "ya"
    assert gateway.take_notices() == [
        "claude no respondió; usé deepseek",
        "deepseek no respondió; usé local",
    ]


def test_si_todos_fallan_se_relanza_el_ultimo_error() -> None:
    gateway = TaskGateway([_failing("claude", "auth"), _failing("deepseek", "timeout")])
    with pytest.raises(GatewayError) as info:
        gateway.complete(MESSAGES)
    assert info.value.kind == "timeout"
    assert gateway.notices == ["claude no respondió; usé deepseek"]


def test_model_not_found_no_respalda() -> None:
    gateway = TaskGateway([_failing("claude", "model_not_found"), _ok("deepseek")])
    with pytest.raises(GatewayError) as info:
        gateway.complete(MESSAGES)
    assert info.value.kind == "model_not_found"
    assert gateway.notices == []


def test_json_invalido_no_respalda() -> None:
    claude = _ok("claude", "esto no es json")
    deepseek = _ok("deepseek", '{"total": 3}')
    gateway = TaskGateway([claude, deepseek])
    with pytest.raises(InvalidJsonError):
        gateway.complete_json(MESSAGES, Out)
    assert gateway.notices == []
    assert not should_fallback(InvalidJsonError("x"))


def test_complete_json_respalda_si_el_proveedor_falla() -> None:
    gateway = TaskGateway([_failing("claude", "network"), _ok("deepseek", '{"total": 3}')])
    assert gateway.complete_json(MESSAGES, Out).data.total == 3
    assert gateway.take_notices() == ["claude no respondió; usé deepseek"]


def test_stream_respalda_antes_de_emitir_texto() -> None:
    gateway = TaskGateway([_failing("claude", "quota"), _ok("deepseek", "hola mundo")])
    text = "".join(e.delta for e in gateway.stream(MESSAGES))
    assert text == "hola mundo"
    assert gateway.take_notices() == ["claude no respondió; usé deepseek"]


def test_stream_no_respalda_si_ya_emitio_texto(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.llm.gateway import StreamEvent

    class _Cut:
        def stream(self, messages: Any, **params: Any) -> Any:
            yield StreamEvent(delta="parcial")
            raise GatewayError("network", "se cortó")

    cut = Candidate("claude", _Cut())  # type: ignore[arg-type]
    gateway = TaskGateway([cut, _ok("deepseek")])
    with pytest.raises(GatewayError):
        list(gateway.stream(MESSAGES))
    assert gateway.notices == []


def test_sin_proveedores_falla_con_error_claro() -> None:
    with pytest.raises(GatewayError) as info:
        Router({}).for_task("planner").complete(MESSAGES)
    assert info.value.kind == "provider_error"
