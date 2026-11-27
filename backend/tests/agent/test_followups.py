"""Preguntas de seguimiento (docs/FLUJO_CONVERSACIONAL.md#preguntas-de-seguimiento)."""

import importlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from app.agent.plan import Plan, PlanFilter
from app.agent.planner import plan_question, render_prompt
from app.llm.gateway import Gateway, ProviderConfig
from app.semantic.schema import SemanticModel, parse_semantic_model

EXAMPLE = Path(__file__).parents[3] / "examples" / "ventas" / "semantic-model.yaml"
NOW = datetime(2026, 11, 25, 15, 30, tzinfo=UTC)

LAST = Plan(
    intent="metric",
    reasoning="Ventas netas de este mes.",
    metric="ventas_netas",
    period_text="este mes",
)


@pytest.fixture
def model() -> SemanticModel:
    yaml = importlib.import_module("yaml")
    return parse_semantic_model(yaml.safe_load(EXAMPLE.read_text()))


def _follow(model: SemanticModel, question: str, last: Plan, reply: dict[str, Any]) -> Plan:
    gateway = Gateway(
        ProviderConfig(kind="fake", model="fake-1", config={"responses": [json.dumps(reply)]})
    )
    return plan_question(gateway, model, question, now=NOW, last_plan=last).plan


def _base(**changes: Any) -> dict[str, Any]:
    return {**LAST.model_dump(mode="json"), **changes}


def test_el_prompt_lleva_el_ultimo_plan_y_las_reglas_de_seguimiento(model: SemanticModel) -> None:
    prompt = render_prompt(model, "¿y el mes pasado?", now=NOW, last_plan=LAST)
    assert '"metric": "ventas_netas"' in prompt
    assert "Preguntas de seguimiento" in prompt


def test_mes_pasado_cambia_solo_el_periodo(model: SemanticModel) -> None:
    plan = _follow(
        model, "¿Y el mes pasado?", LAST, _base(period_text="el mes pasado", reasoning="Otro mes.")
    )
    assert plan.metric == "ventas_netas"
    assert plan.period_text == "el mes pasado"
    assert plan.dimensions == [] and plan.filters == []
    assert "Se mantuvo: métrica" in plan.reasoning
    assert "Cambió: período" in plan.reasoning


def test_por_sucursal_agrega_la_dimension(model: SemanticModel) -> None:
    plan = _follow(model, "¿Y por sucursal?", LAST, _base(dimensions=["sucursales.nombre"]))
    assert plan.dimensions == ["sucursales.nombre"]
    assert plan.period_text == "este mes"
    assert "Se mantuvo: métrica, período" in plan.reasoning
    assert "Cambió: dimensiones" in plan.reasoning


def test_solo_en_linea_agrega_el_filtro(model: SemanticModel) -> None:
    flt = {"field": "facturas.canal", "op": "=", "value": "ONLINE"}
    plan = _follow(model, "Solo en línea", LAST, _base(filters=[flt]))
    assert plan.filters == [PlanFilter(field="facturas.canal", op="=", value="ONLINE")]
    assert plan.metric == "ventas_netas"
    assert "Cambió: filtros" in plan.reasoning


def test_en_unidades_cambia_la_metrica(model: SemanticModel) -> None:
    plan = _follow(model, "¿Y en unidades?", LAST, _base(metric="unidades_vendidas"))
    assert plan.metric == "unidades_vendidas"
    assert plan.period_text == "este mes"
    assert "Se mantuvo: período" in plan.reasoning
    assert "Cambió: métrica" in plan.reasoning


def test_comparar_con_el_ano_pasado_activa_compare_previous(model: SemanticModel) -> None:
    plan = _follow(model, "Compáralo con el año pasado", LAST, _base(compare_previous=True))
    assert plan.compare_previous is True
    assert plan.period_text == "este mes"
    assert "Cambió: comparación con el período anterior" in plan.reasoning


def test_pregunta_nueva_no_agrega_nota(model: SemanticModel) -> None:
    reply = {
        "intent": "metric",
        "reasoning": "Clientes.",
        "metric": "clientes_activos",
        "period_text": "hoy",
    }
    plan = _follow(model, "¿Cuántos clientes activos hoy?", LAST, reply)
    assert plan.reasoning == "Clientes."
