import importlib
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from app.agent.answer import (
    MAX_ANSWER_ROWS,
    AnswerWriter,
    Outcome,
    format_value,
    template_answer,
)
from app.agent.events import AnswerDelta
from app.engine.periods import PeriodRange
from app.llm.gateway import Gateway, ProviderConfig, StreamEvent
from app.semantic.context import Privacy
from app.semantic.schema import Metric, SemanticModel, parse_semantic_model

EXAMPLE = Path(__file__).parents[3] / "examples" / "ventas" / "semantic-model.yaml"
PERIODO = PeriodRange(date(2026, 3, 1), date(2026, 4, 1), "Marzo 2026", "month", False)


class EspiaGateway(Gateway):
    """Pasarela simulada que guarda los mensajes que se le enviaron."""

    def __init__(self, *responses: str) -> None:
        super().__init__(ProviderConfig("fake", "fake-1", {"responses": list(responses)}))
        self.enviados: list[list[dict[str, str]]] = []

    def stream(self, messages: list[dict[str, str]], **params: Any) -> Iterator[StreamEvent]:
        self.enviados.append(messages)
        return super().stream(messages, **params)


@pytest.fixture(scope="module")
def model() -> SemanticModel:
    yaml = importlib.import_module("yaml")
    return parse_semantic_model(yaml.safe_load(EXAMPLE.read_text()))


@pytest.fixture(scope="module")
def ventas(model: SemanticModel) -> Metric:
    return next(m for m in model.metrics if m.format == "currency")


def _outcome(metric: Metric, rows: list[list[Any]] | None = None) -> Outcome:
    return Outcome(
        columns=["valor"],
        rows=rows if rows is not None else [[1234567.5]],
        metric=metric,
        period=PERIODO,
    )


def _redactar(
    gateway: Gateway, model: SemanticModel, privacy: Privacy, outcome: Outcome
) -> tuple[AnswerWriter, list[str]]:
    writer = AnswerWriter(gateway, model, privacy, "¿Cuánto vendí?")
    deltas = [e.data.text for e in writer.stream(outcome) if isinstance(e.data, AnswerDelta)]
    return writer, deltas


@pytest.mark.parametrize("privacy", ["aggregates", "samples"])
def test_con_privacidad_permitida_redacta_la_ia_con_streaming(
    model: SemanticModel, ventas: Metric, privacy: Privacy
) -> None:
    gateway = EspiaGateway("Vendiste mucho en Marzo 2026.")

    writer, deltas = _redactar(gateway, model, privacy, _outcome(ventas))

    assert len(gateway.enviados) == 1
    assert len(deltas) > 1 and "".join(deltas) == writer.text == "Vendiste mucho en Marzo 2026."
    assert "1234567.5" in gateway.enviados[0][1]["content"]
    assert writer.usage.input_tokens > 0 and writer.warning is None


def test_la_respuesta_de_la_ia_siempre_menciona_el_periodo(
    model: SemanticModel, ventas: Metric
) -> None:
    gateway = EspiaGateway("Vendiste mucho.")

    writer, deltas = _redactar(gateway, model, "aggregates", _outcome(ventas))

    assert "Marzo 2026" in writer.text
    assert "".join(deltas) == writer.text


def test_el_prompt_lleva_locale_y_moneda_del_modelo(
    model: SemanticModel, ventas: Metric
) -> None:
    gateway = EspiaGateway("ok Marzo 2026")

    _redactar(gateway, model, "aggregates", _outcome(ventas))

    assert "locale es-CO, moneda COP" in gateway.enviados[0][1]["content"]


def test_con_privacidad_schema_el_proveedor_no_recibe_ninguna_fila(
    model: SemanticModel, ventas: Metric
) -> None:
    gateway = EspiaGateway("no debe usarse")
    outcome = _outcome(ventas, [[987654321.0]])

    writer, deltas = _redactar(gateway, model, "schema", outcome)

    assert gateway.enviados == []  # ni siquiera se llama a la IA
    assert deltas == []
    assert "987.654.321" in writer.text and "Marzo 2026" in writer.text
    assert "no debe usarse" not in writer.text


def test_resultados_grandes_usan_la_plantilla(model: SemanticModel, ventas: Metric) -> None:
    gateway = EspiaGateway("no debe usarse")
    filas = [[float(i)] for i in range(MAX_ANSWER_ROWS + 1)]

    writer, deltas = _redactar(gateway, model, "samples", _outcome(ventas, filas))

    assert gateway.enviados == [] and deltas == []
    assert f"{MAX_ANSWER_ROWS + 1} filas" in writer.text and "Marzo 2026" in writer.text


def test_si_la_ia_falla_responde_la_plantilla(model: SemanticModel, ventas: Metric) -> None:
    gateway = Gateway(ProviderConfig("fake", "fake-1", {"error": "timeout"}))

    writer, _ = _redactar(gateway, model, "aggregates", _outcome(ventas))

    assert writer.warning is not None and "plantilla" in writer.warning
    assert "Marzo 2026" in writer.text and "$1.234.567,50" in writer.text


def test_la_plantilla_formatea_con_locale_y_moneda(ventas: Metric) -> None:
    outcome = _outcome(ventas)

    assert template_answer(outcome, locale="es-CO", currency="COP").endswith("$1.234.567,50.")
    assert template_answer(outcome, locale="en-US", currency="USD").endswith("US$1,234,567.50.")
    assert template_answer(outcome, locale="de-DE", currency="EUR").endswith(
        "1.234.567,50 €."
    )


def test_format_value_sin_metrica_ni_numero() -> None:
    assert format_value(None) == "sin datos"
    assert format_value("Norte") == "Norte"
    assert format_value(1500) == "1.500"
    assert format_value(1500, locale="en-US") == "1,500"
