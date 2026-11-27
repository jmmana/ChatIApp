from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from app.agent.plan import Plan
from app.eval import recorded
from app.eval.golden import cargar
from app.eval.runner import ResultadoCaso
from app.llm.gateway import GatewayError


def test_fixture_grabado_cubre_cada_caso_y_turno_del_set() -> None:
    conjunto = cargar()
    config = recorded.cargar_planes()

    entradas = recorded._entradas(conjunto, config)

    assert len(entradas) == sum(
        1 + len(caso.previous) + int(bool(caso.answers)) for caso in conjunto.casos
    )
    assert len({registro.id for registro in config.casos}) == len(conjunto.casos)


def test_preguntas_con_respuesta_reproducen_aclaracion_y_respuesta() -> None:
    conjunto = cargar()
    config = recorded.cargar_planes()
    caso = next(caso for caso in conjunto.casos if caso.id == "acl-es-resp-periodo-mes")

    entradas = recorded._entradas(conjunto, config)
    pregunta, respuesta = [
        entrada for entrada in entradas if entrada.caso == caso.id
    ]

    assert caso.expect is not None
    assert pregunta.pregunta == caso.question
    assert pregunta.plan["intent"] == "clarify"
    assert pregunta.plan["clarification"]["slot"] == "period"
    assert respuesta.pregunta == caso.answers[0]
    assert respuesta.plan == {"intent": "sql", "sql": caso.expect.sql}


def test_proveedor_grabado_valida_pregunta_y_reproduce_plan() -> None:
    entrada = recorded.EntradaGrabada(
        "caso-uno",
        "question",
        "Ventas del mes pasado",
        {"intent": "sql", "sql": "SELECT 1"},
    )
    proveedor = recorded.ProveedorGrabado([entrada])

    resultado = proveedor.complete_json(
        [{"role": "user", "content": "Ventas del mes pasado"}], Plan
    )

    assert resultado.data.intent == "sql"
    assert resultado.data.sql == "SELECT 1"
    proveedor.assert_consumed()

    desfasado = recorded.ProveedorGrabado([entrada])
    with pytest.raises(GatewayError, match="desalineado"):
        desfasado.complete_json([{"role": "user", "content": "Otra pregunta"}], Plan)


def test_evaluacion_falla_bajo_100_y_publica_el_resumen(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    resumen = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(resumen))

    def evaluar_con_fallo(conjunto, proveedor, modelo):
        for entrada in proveedor.entradas:
            proveedor.complete_json([{"role": "user", "content": entrada.pregunta}], Plan)
        return [
            ResultadoCaso(
                id="caso-fallido",
                lang="es",
                tags=["metrica"],
                tipo="resultado",
                correcto=False,
                motivo="fallo simulado",
                latencia_ms=0,
                tokens_in=0,
                tokens_out=0,
                costo_usd=0,
            )
        ]

    monkeypatch.setattr(
        recorded,
        "evaluar",
        evaluar_con_fallo,
    )

    assert recorded.main([]) == 1
    assert "0.0 %" in resumen.read_text(encoding="utf-8")


def test_yaml_invalido_del_modelo_devuelve_error_sin_traceback(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def cargar_modelo_invalido(_path: Path):
        raise yaml.YAMLError("modelo mal formado")

    monkeypatch.setattr(recorded, "cargar_modelo", cargar_modelo_invalido)

    assert recorded.main([]) == 2
    assert "modelo mal formado" in capsys.readouterr().err
