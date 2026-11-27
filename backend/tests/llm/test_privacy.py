import importlib
import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from app.agent.answer import AnswerWriter, Outcome
from app.agent.free_sql import repair_sql
from app.agent.plan import Plan
from app.agent.planner import plan_question
from app.llm.gateway import Gateway, JsonCompletion, ProviderConfig, StreamEvent
from app.llm.privacy import (
    ALLOWED,
    LEVELS,
    PrivacyGateway,
    PrivacyLog,
    PrivacyViolation,
    classify,
    effective_level,
    parse_level,
)
from app.semantic.context import Privacy
from app.semantic.schema import SemanticModel, parse_semantic_model
from app.semantic.suggest import suggest

EXAMPLE = Path(__file__).parents[3] / "examples" / "ventas" / "semantic-model.yaml"
NOW = datetime(2026, 11, 25, 15, 30, tzinfo=UTC)
SAMPLE = "MAYORISTA"  # valor de ejemplo del canal en el modelo de ventas
ROW_VALUE = 98765432  # valor que solo existe en una fila de resultado


class Proveedor:
    """Proveedor simulado: guarda, tal cual, lo que recibe de la pasarela."""

    def __init__(self, *responses: str) -> None:
        config = {"responses": list(responses)}
        self.gateway = Gateway(ProviderConfig(kind="fake", model="fake-1", config=config))
        self.recibidos: list[list[dict[str, str]]] = []

    def complete(self, messages: list[dict[str, str]], **params: Any) -> Any:
        self.recibidos.append(messages)
        return self.gateway.complete(messages, **params)

    def complete_json[T: BaseModel](
        self, messages: list[dict[str, str]], schema: type[T], **params: Any
    ) -> JsonCompletion[T]:
        self.recibidos.append(messages)
        return self.gateway.complete_json(messages, schema, **params)

    def stream(self, messages: list[dict[str, str]], **params: Any) -> Iterator[StreamEvent]:
        self.recibidos.append(messages)
        return self.gateway.stream(messages, **params)

    def texto(self) -> str:
        return "\n".join(m["content"] for call in self.recibidos for m in call)


@pytest.fixture(scope="module")
def model() -> SemanticModel:
    yaml = importlib.import_module("yaml")
    return parse_semantic_model(yaml.safe_load(EXAMPLE.read_text()))


def _suggestion_reply() -> str:
    return json.dumps({"suggestions": []})


def _run_task(
    task: str, model: SemanticModel, level: Privacy, provider: Proveedor, log: PrivacyLog
) -> None:
    """Ejecuta la tarea con los constructores de prompt reales y la pasarela con interceptor."""
    gateway = PrivacyGateway(provider, task, level, log)
    if task == "planner":
        reply = {"intent": "out_of_scope", "answer": "Solo respondo de tus datos."}
        provider.gateway = Gateway(
            ProviderConfig("fake", "fake-1", {"responses": [json.dumps(reply)]})
        )
        plan = plan_question(gateway, model, "ventas por canal", now=NOW, privacy=level).plan
        assert isinstance(plan, Plan)
    elif task == "sql":
        repair_sql(
            gateway, model, "ventas por canal", "SELECT 1", "error", dialect="sqlite", privacy=level
        )
    elif task == "answer":
        outcome = Outcome(columns=["valor"], rows=[[ROW_VALUE]])
        writer = AnswerWriter(gateway, model, level, "ventas por canal")
        list(writer.stream(outcome))
    else:
        provider.gateway = Gateway(
            ProviderConfig("fake", "fake-1", {"responses": [_suggestion_reply()]})
        )
        suggest(model, gateway, privacy=level)


# --- Niveles y categorías ---


def test_parse_level_cae_en_el_mas_restrictivo() -> None:
    assert parse_level("samples") == "samples"
    assert parse_level("todo") == "schema"
    assert parse_level(None) == "schema"


def test_el_nivel_efectivo_no_supera_el_maximo() -> None:
    assert effective_level("samples", "aggregates") == "aggregates"
    assert effective_level("schema", "samples") == "schema"
    assert effective_level("aggregates", "aggregates") == "aggregates"


def test_cada_nivel_incluye_al_anterior() -> None:
    for lower, upper in zip(LEVELS, LEVELS[1:], strict=False):
        assert ALLOWED[lower] < ALLOWED[upper]


def test_classify_reconoce_las_categorias() -> None:
    plano = [{"role": "user", "content": "hola"}]
    assert classify(plano) == {"question"}
    esquema = [{"role": "system", "content": "<modelo_semantico>\n- canal {valores: A, B}"}]
    assert classify(esquema) == {"question", "schema", "sample_values"}
    filas = [{"role": "user", "content": "<resultado>\nColumnas: v\nFila: [1]\n</resultado>"}]
    assert classify(filas) == {"question", "result_rows"}


# --- Contenido exacto enviado, por nivel y tarea ---


@pytest.mark.parametrize("level", LEVELS)
@pytest.mark.parametrize("task", ["planner", "sql", "answer", "suggest"])
def test_lo_enviado_respeta_el_nivel(model: SemanticModel, level: Privacy, task: str) -> None:
    provider, log = Proveedor(), PrivacyLog()
    _run_task(task, model, level, provider, log)
    enviado = provider.texto()

    # Lo que el interceptor registra es exactamente lo que recibió el proveedor.
    assert [e.messages for e in log.entries] == [
        tuple((m["role"], m["content"]) for m in call) for call in provider.recibidos
    ]
    for entry in log.entries:
        assert entry.task == task
        assert entry.level == level
        assert entry.categories <= ALLOWED[level]

    if level == "schema":
        assert SAMPLE not in enviado
        assert str(ROW_VALUE) not in enviado
        assert "Fila:" not in enviado
        assert "sample_values" not in log.categories()
        assert "result_rows" not in log.categories()
    if level == "aggregates":
        assert SAMPLE not in enviado
        assert ("result_rows" in log.categories()) == (task == "answer")
    if level == "samples" and task != "answer":
        assert SAMPLE in enviado
        assert "sample_values" in log.categories()
    if task == "answer":
        # Con `schema` la respuesta sale de plantilla: no hay llamada al proveedor.
        assert bool(log.entries) == (level != "schema")
        assert (str(ROW_VALUE) in enviado) == (level != "schema")


# --- El interceptor bloquea lo que excede el nivel ---


def test_filas_con_schema_se_bloquean_sin_llegar_al_proveedor() -> None:
    provider, log = Proveedor(), PrivacyLog()
    gateway = PrivacyGateway(provider, "answer", "schema", log)
    messages = [{"role": "user", "content": "<resultado>\nFila: [123456]\n</resultado>"}]
    with pytest.raises(PrivacyViolation) as exc:
        gateway.complete(messages)
    assert exc.value.categories == {"result_rows"}
    assert provider.recibidos == []
    assert log.entries == []


@pytest.mark.parametrize("task", ["planner", "sql", "answer", "suggest"])
def test_valores_de_ejemplo_bloqueados_sin_samples(task: str) -> None:
    provider = Proveedor()
    messages = [{"role": "system", "content": "<modelo_semantico>\n- canal {valores: A}"}]
    for level in ("schema", "aggregates"):
        with pytest.raises(PrivacyViolation):
            PrivacyGateway(provider, task, parse_level(level)).complete(messages)
    assert provider.recibidos == []


def test_bloqueo_en_json_y_stream() -> None:
    provider = Proveedor()
    gateway = PrivacyGateway(provider, "answer", "schema")
    messages = [{"role": "user", "content": "<resultado>\nFila: [1]\n</resultado>"}]
    with pytest.raises(PrivacyViolation):
        gateway.complete_json(messages, Plan)
    with pytest.raises(PrivacyViolation):
        gateway.stream(messages)
    assert provider.recibidos == []


def test_los_avisos_de_respaldo_pasan_por_la_envoltura() -> None:
    assert PrivacyGateway(Proveedor(), "sql", "schema").take_notices() == []
