import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Base, EvalRun, Provider
from app.db.session import make_engine
from app.eval import report
from app.eval.cli import buscar_proveedores, main
from app.eval.golden import SetDorado, cargar
from app.eval.runner import ResultadoCaso, cargar_modelo, evaluar
from app.llm.gateway import Gateway, JsonCompletion, ProviderConfig, StreamEvent, Usage

SET_YAML = """
name: prueba
dataset: {seed: 42, hasta: 2026-11-25}
role: gerencia_general
minimos: {es: 0, en: 0}
etiquetas_obligatorias: []
"""

SQL_MES_PASADO = (
    "SELECT SUM(f.total) AS ventas_netas FROM facturas f WHERE f.estado = 'PAGADA' "
    "AND f.fecha >= '2026-10-01' AND f.fecha < '2026-11-01'"
)
SQL_AYER = (
    "SELECT SUM(f.total) AS ventas_netas FROM facturas f WHERE f.estado = 'PAGADA' "
    "AND f.fecha >= '2026-11-24' AND f.fecha < '2026-11-25'"
)

CASOS = f"""
- id: ok-mes-pasado
  lang: es
  question: "Ventas del mes pasado"
  tags: [metrica, periodo]
  expect:
    sql: "{SQL_MES_PASADO}"
- id: mal-periodo
  lang: es
  question: "Ventas de ayer"
  tags: [metrica, periodo]
  expect:
    sql: "{SQL_AYER}"
- id: aclara-periodo
  lang: es
  question: "¿Cuánto vendí?"
  tags: [aclaracion]
  expect_clarification: {{slot: period}}
- id: aclara-otro-slot
  lang: es
  question: "¿Cuánto vendí?"
  tags: [aclaracion]
  expect_clarification: {{slot: metric}}
- id: fuera-clima
  lang: es
  question: "¿Va a llover mañana?"
  tags: [fuera_de_alcance]
  expect_out_of_scope: true
- id: aclara-y-responde
  lang: es
  question: "¿Cuánto vendí?"
  answers: ["Mes pasado"]
  tags: [aclaracion, metrica]
  expect:
    sql: "{SQL_MES_PASADO}"
"""

METRICA = {"intent": "metric", "metric": "ventas_netas"}
PLANES: dict[str, dict[str, Any]] = {
    "Ventas del mes pasado": {**METRICA, "period_text": "mes pasado"},
    "Ventas de ayer": {**METRICA, "period_text": "mes pasado"},  # error a propósito
    "¿Cuánto vendí?": METRICA,
    "¿Va a llover mañana?": {"intent": "out_of_scope", "answer": "Solo respondo sobre ventas."},
    "Mes pasado": {**METRICA, "period_text": "mes pasado"},
}


class GatewayGuionado(Gateway):
    """Responde con el plan que corresponde a cada pregunta: sin red ni azar."""

    def __init__(self) -> None:
        super().__init__(ProviderConfig("fake", "fake-1"))

    def complete_json(  # type: ignore[override]
        self, messages: list[dict[str, str]], schema: Any, **params: Any
    ) -> JsonCompletion[Any]:
        pregunta = next(m["content"] for m in reversed(messages) if m["role"] == "user")
        return JsonCompletion(schema.model_validate(PLANES[pregunta]), Usage(10, 5, 1.0, 0.001))

    def stream(self, messages: list[dict[str, str]], **params: Any) -> Iterator[StreamEvent]:
        yield StreamEvent(delta="Listo.")
        yield StreamEvent(usage=Usage(3, 2, 1.0, 0.0005))


@pytest.fixture(scope="module")
def conjunto(tmp_path_factory: pytest.TempPathFactory) -> SetDorado:
    raiz = tmp_path_factory.mktemp("set")
    (raiz / "casos").mkdir()
    (raiz / "set.yaml").write_text(SET_YAML, encoding="utf-8")
    (raiz / "casos" / "prueba.yaml").write_text(CASOS, encoding="utf-8")
    return cargar(raiz)


@pytest.fixture(scope="module")
def resultados(conjunto: SetDorado) -> dict[str, ResultadoCaso]:
    hechos = evaluar(conjunto, GatewayGuionado(), cargar_modelo())
    return {r.id: r for r in hechos}


def test_compara_resultados_y_no_texto_sql(resultados: dict[str, ResultadoCaso]) -> None:
    ok = resultados["ok-mes-pasado"]
    assert ok.correcto and ok.motivo is None
    # El SQL del catálogo no se parece al escrito a mano, pero devuelve lo mismo.
    assert ok.sql is not None and ok.sql != ok.sql_esperado


def test_un_resultado_distinto_falla_con_su_sql(resultados: dict[str, ResultadoCaso]) -> None:
    mal = resultados["mal-periodo"]
    assert not mal.correcto and mal.motivo == "el resultado no coincide con el esperado"
    assert mal.sql is not None and "2026-10-01" in mal.sql
    assert mal.sql_esperado == SQL_AYER


def test_aclaraciones_correctas_y_con_slot_equivocado(
    resultados: dict[str, ResultadoCaso],
) -> None:
    assert resultados["aclara-periodo"].correcto
    otro = resultados["aclara-otro-slot"]
    assert not otro.correcto and "«period»" in (otro.motivo or "")


def test_fuera_de_alcance_no_ejecuta_nada(resultados: dict[str, ResultadoCaso]) -> None:
    assert resultados["fuera-clima"].correcto and resultados["fuera-clima"].sql is None


def test_aclara_y_responde_suma_los_dos_turnos(resultados: dict[str, ResultadoCaso]) -> None:
    caso = resultados["aclara-y-responde"]
    assert caso.correcto
    # La respuesta a la aclaración completa el plan pendiente sin llamar a la IA (main): el uso
    # suma los dos turnos, pero el segundo ya no cuesta tokens.
    assert caso.tokens_in >= resultados["ok-mes-pasado"].tokens_in


def test_resumen_con_exactitud_por_etiqueta_latencia_y_costo(
    resultados: dict[str, ResultadoCaso],
) -> None:
    resumen = report.resumir("claude", "fake", "fake-1", list(resultados.values()))
    assert resumen["total"] == 6 and resumen["correctos"] == 4
    assert resumen["exactitud"] == pytest.approx(4 / 6)
    assert resumen["por_etiqueta"]["periodo"]["exactitud"] == 0.5
    assert resumen["por_etiqueta"]["aclaracion"]["total"] == 3
    assert resumen["aclaraciones"] == {"esperadas": 2, "correctas": 1, "innecesarias": 0}
    assert resumen["latencia_ms"]["p50"] <= resumen["latencia_ms"]["p95"]
    assert resumen["tokens"]["entrada"] > 0 and resumen["costo_usd"] > 0
    assert {f["id"] for f in resumen["fallidos"]} == {"mal-periodo", "aclara-otro-slot"}


def test_percentiles_por_rango_mas_cercano() -> None:
    valores = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0]
    assert report.percentil(valores, 50) == 50.0
    assert report.percentil(valores, 95) == 100.0
    assert report.percentil([], 50) == 0.0


def test_el_informe_markdown_y_json_traen_los_fallos_con_su_sql(
    resultados: dict[str, ResultadoCaso],
) -> None:
    resumen = report.resumir("claude", "fake", "fake-1", list(resultados.values()))
    informe = report.armar_informe("prueba", [resumen])
    markdown = report.a_markdown(informe)
    assert "| claude |" in markdown and "66.7 %" in markdown and "p95" in markdown
    assert "**mal-periodo**" in markdown and SQL_AYER in markdown
    assert json.loads(report.a_json(informe))["proveedores"][0]["proveedor"] == "claude"


@pytest.fixture
def app_db(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    engine = make_engine(f"sqlite:///{tmp_path / 'app.db'}")
    Base.metadata.create_all(engine)
    fabrica = sessionmaker(bind=engine, expire_on_commit=False)
    with fabrica() as session:
        for nombre in ("claude", "deepseek"):
            session.add(Provider(name=nombre, kind="fake", model=f"{nombre}-modelo"))
        session.commit()
    yield fabrica
    engine.dispose()


def test_la_cli_guarda_un_eval_run_por_proveedor_y_escribe_el_informe(
    app_db: sessionmaker[Session], tmp_path: Path
) -> None:
    raiz = tmp_path / "set"
    (raiz / "casos").mkdir(parents=True)
    (raiz / "set.yaml").write_text(SET_YAML, encoding="utf-8")
    (raiz / "casos" / "prueba.yaml").write_text(CASOS, encoding="utf-8")
    salida = tmp_path / "informe"

    codigo = main(
        ["run", "--set", str(raiz), "--providers", "claude,deepseek", "--out", str(salida)],
        session_factory=app_db,
        gateway_de=lambda _p: GatewayGuionado(),
    )

    assert codigo == 0
    with app_db() as session:
        runs = session.scalars(select(EvalRun)).all()
        assert len(runs) == 2
        assert {r.provider_id for r in runs} == {p.id for p in session.scalars(select(Provider))}
        assert all(r.eval_set == "prueba" and r.accuracy == pytest.approx(4 / 6) for r in runs)
        assert all(r.details is not None and r.details["total"] == 6 for r in runs)
    assert (salida / "prueba.md").exists()
    datos = json.loads((salida / "prueba.json").read_text(encoding="utf-8"))
    assert [p["proveedor"] for p in datos["proveedores"]] == ["claude", "deepseek"]


def test_un_proveedor_desconocido_lista_los_disponibles(app_db: sessionmaker[Session]) -> None:
    with app_db() as session, pytest.raises(ValueError, match="gpt.*Disponibles: claude, deepseek"):
        buscar_proveedores(session, ["claude", "gpt"])
