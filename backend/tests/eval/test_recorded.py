from __future__ import annotations

from pathlib import Path

import pytest

from app.agent.plan import Plan
from app.eval import recorded
from app.eval.golden import cargar
from app.eval.runner import ResultadoCaso
from app.llm.gateway import GatewayError


def test_fixture_grabado_cubre_cada_caso_y_turno_del_set() -> None:
    conjunto = cargar()
    config = recorded.cargar_planes()

    entradas = recorded._entradas(conjunto, config)

    assert len(entradas) == sum(1 + len(caso.previous) for caso in conjunto.casos)
    assert len({registro.id for registro in config.casos}) == len(conjunto.casos)


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
