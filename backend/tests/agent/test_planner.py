import importlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.agent.plan import Plan
from app.agent.planner import PlannerError, Turn, plan_question, render_prompt
from app.llm.gateway import Gateway, ProviderConfig
from app.semantic.schema import SemanticModel, parse_semantic_model

EXAMPLE = Path(__file__).parents[3] / "examples" / "ventas" / "semantic-model.yaml"
NOW = datetime(2026, 11, 25, 15, 30, tzinfo=UTC)  # miércoles, 10:30 en Bogotá


@pytest.fixture
def model() -> SemanticModel:
    yaml = importlib.import_module("yaml")
    return parse_semantic_model(yaml.safe_load(EXAMPLE.read_text()))


def _gateway(*responses: dict[str, Any] | str) -> Gateway:
    texts = [r if isinstance(r, str) else json.dumps(r) for r in responses]
    return Gateway(ProviderConfig(kind="fake", model="fake-1", config={"responses": texts}))


def _plan(gateway: Gateway, model: SemanticModel, question: str = "hola", **kw: Any) -> Plan:
    return plan_question(gateway, model, question, now=NOW, **kw).plan


# --- Una prueba por intent ---


def test_intent_metric(model: SemanticModel) -> None:
    gateway = _gateway(
        {
            "intent": "metric",
            "reasoning": "Ventas por tienda del mes.",
            "metric": "ventas_netas",
            "dimensions": ["tiendas.nombre"],
            "filters": [{"field": "tiendas.ciudad", "op": "in", "value": ["Bogotá", "Cali"]}],
            "time_grain": None,
            "period_text": "este mes",
            "compare_previous": True,
            "order": {"by": "ventas_netas", "direction": "desc"},
            "limit": 5,
        }
    )
    plan = _plan(gateway, model, "top 5 tiendas de este mes en Bogotá y Cali")
    assert plan.intent == "metric"
    assert plan.metric == "ventas_netas"
    assert plan.period_text == "este mes"
    assert plan.compare_previous is True
    assert plan.filters[0].op == "in"
    assert plan.limit == 5


def test_intent_sql(model: SemanticModel) -> None:
    plan = _plan(_gateway({"intent": "sql", "sql": "SELECT 1"}), model)
    assert plan.intent == "sql"
    assert plan.sql == "SELECT 1"


def test_intent_clarify(model: SemanticModel) -> None:
    gateway = _gateway(
        {
            "intent": "clarify",
            "metric": "ventas_netas",
            "clarification": {
                "question": "¿De qué período?",
                "options": ["Hoy", "Este mes"],
                "slot": "period",
            },
        }
    )
    plan = _plan(gateway, model, "¿Cuánto vendí?")
    assert plan.intent == "clarify"
    assert plan.clarification is not None
    assert plan.clarification.options == ["Hoy", "Este mes"]
    assert plan.clarification.slot == "period"


def test_intent_explain(model: SemanticModel) -> None:
    plan = _plan(_gateway({"intent": "explain", "answer": "Son las ventas sin IVA."}), model)
    assert plan.intent == "explain"
    assert plan.answer == "Son las ventas sin IVA."


def test_intent_out_of_scope(model: SemanticModel) -> None:
    gateway = _gateway({"intent": "out_of_scope", "answer": "Solo respondo de tus datos."})
    plan = _plan(gateway, model)
    assert plan.intent == "out_of_scope"


# --- Reintento y error tipado ---


def test_json_invalido_se_reintenta_con_el_error(model: SemanticModel) -> None:
    gateway = _gateway("esto no es json", {"intent": "explain", "answer": "ok"})
    result = plan_question(gateway, model, "hola", now=NOW)
    assert result.plan.answer == "ok"
    assert result.usage.input_tokens > 0


def test_esquema_incumplido_se_reintenta(model: SemanticModel) -> None:
    gateway = _gateway({"intent": "metric"}, {"intent": "metric", "metric": "ventas_netas"})
    assert _plan(gateway, model).metric == "ventas_netas"


def test_dos_fallos_dan_error_tipado(model: SemanticModel) -> None:
    gateway = _gateway("no json", {"intent": "inventada"})
    with pytest.raises(PlannerError) as info:
        _plan(gateway, model)
    assert info.value.kind == "invalid_plan"


def test_error_del_proveedor_se_tipa(model: SemanticModel) -> None:
    gateway = Gateway(ProviderConfig(kind="fake", model="f", config={"error": "timeout"}))
    with pytest.raises(PlannerError) as info:
        _plan(gateway, model)
    assert info.value.kind == "gateway"


# --- Contrato del plan ---


@pytest.mark.parametrize(
    "data",
    [
        {"intent": "metric"},
        {"intent": "clarify"},
        {"intent": "sql"},
        {"intent": "explain"},
        {"intent": "metric", "metric": "m", "sql": "SELECT 1"},
        {"intent": "explain", "answer": "a", "clarification": {"question": "q"}},
        {"intent": "metric", "metric": "m", "limit": 0},
        {"intent": "metric", "metric": "m", "time_grain": "hora"},
        {"intent": "metric", "metric": "m", "filters": [{"field": "a", "op": "~", "value": 1}]},
        {"intent": "metric", "metric": "m", "inventado": 1},
    ],
)
def test_plan_rechaza_contratos_incumplidos(data: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        Plan.model_validate(data)


def test_plan_por_defecto_coincide_con_la_documentacion() -> None:
    plan = Plan.model_validate({"intent": "metric", "metric": "ventas_netas"})
    assert plan.dimensions == [] and plan.filters == []
    assert plan.compare_previous is False
    assert plan.time_grain is None and plan.order is None and plan.limit is None


# --- Prompt ---


def test_prompt_incluye_contexto_fecha_historial_y_ultimo_plan(model: SemanticModel) -> None:
    last = Plan(intent="metric", metric="ventas_netas", period_text=None)
    history = [Turn("user", "¿Cuánto vendí?"), Turn("assistant", "¿De qué período?")]
    prompt = render_prompt(model, "este mes", now=NOW, history=history, last_plan=last)
    assert "<modelo_semantico>" in prompt
    assert "ventas_netas" in prompt
    assert "miércoles 2026-11-25" in prompt
    assert "America/Bogota" in prompt
    assert "- user: ¿Cuánto vendí?" in prompt
    assert '"metric": "ventas_netas"' in prompt
    assert "{{" not in prompt


def test_prompt_sin_historial_ni_plan(model: SemanticModel) -> None:
    prompt = render_prompt(model, "hola", now=NOW)
    assert "(sin historial)" in prompt
    assert "(ninguno)" in prompt


def test_prompt_limita_el_historial_a_los_turnos_recientes(model: SemanticModel) -> None:
    history = [Turn("user", f"pregunta-{i}") for i in range(10)]
    prompt = render_prompt(model, "hola", now=NOW, history=history)
    assert "pregunta-3" not in prompt
    assert "pregunta-4" in prompt
    assert "pregunta-9" in prompt


def test_la_fecha_usa_la_zona_horaria_del_modelo(model: SemanticModel) -> None:
    # 02:00 UTC del jueves sigue siendo miércoles por la noche en Bogotá.
    late = datetime(2026, 11, 26, 2, 0, tzinfo=UTC)
    assert "miércoles 2026-11-25" in render_prompt(model, "hola", now=late)
