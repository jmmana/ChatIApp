import json
from pathlib import Path

import pytest

from app.agent.plan import Plan
from app.eval.golden import RAIZ_SET, Caso, cargar
from app.eval.recorded import (
    GatewayGrabado,
    cargar_grabaciones,
    faltantes,
    main,
    ruta_grabaciones,
)
from app.llm.gateway import GatewayError

PLAN_SQL = {"intent": "sql", "sql": "SELECT 1"}


def _mensajes(pregunta: str) -> list[dict[str, str]]:
    return [{"role": "system", "content": "sistema"}, {"role": "user", "content": pregunta}]


def test_las_grabaciones_cubren_todo_el_set_dorado() -> None:
    conjunto = cargar(RAIZ_SET)
    grabaciones = cargar_grabaciones(ruta_grabaciones(RAIZ_SET))
    assert faltantes(conjunto, grabaciones) == []
    for turnos in grabaciones.values():
        for turno in turnos:
            Plan.model_validate(turno["plan"])


def test_el_motor_acierta_el_set_dorado_con_planes_grabados(tmp_path: Path) -> None:
    resumen = tmp_path / "resumen.md"
    codigo = main(["--out", str(tmp_path / "out"), "--summary", str(resumen)])
    assert codigo == 0
    assert "100" in resumen.read_text("utf-8")
    informe = json.loads((tmp_path / "out" / "ventas-grabado.json").read_text("utf-8"))
    assert informe["proveedores"][0]["exactitud"] == 1.0


def test_el_gateway_sigue_los_turnos_en_orden() -> None:
    turnos = [{"pregunta": "uno", "plan": PLAN_SQL}, {"pregunta": "dos", "plan": PLAN_SQL}]
    grabaciones = {"c": turnos}
    gateway = GatewayGrabado(grabaciones)
    gateway.empezar_caso(_caso("c"))
    assert gateway.complete_json(_mensajes("uno"), Plan).data.sql == "SELECT 1"
    # El reintento con plan rechazado empieza con la misma pregunta.
    assert gateway.complete_json(_mensajes("dos\n\nCorrige"), Plan).data.intent == "sql"
    with pytest.raises(GatewayError):
        gateway.complete_json(_mensajes("uno"), Plan)


def test_un_plan_grabado_invalido_falla_como_error_del_proveedor() -> None:
    gateway = GatewayGrabado({"c": [{"pregunta": "uno", "plan": {"intent": "metric"}}]})
    gateway.empezar_caso(_caso("c"))
    with pytest.raises(GatewayError):
        gateway.complete_json(_mensajes("uno"), Plan)


def test_sale_con_error_si_la_exactitud_baja_del_minimo(tmp_path: Path) -> None:
    grabaciones = json.loads(ruta_grabaciones(RAIZ_SET).read_text("utf-8"))
    primero = next(iter(grabaciones["casos"]))
    grabaciones["casos"][primero] = [
        {"pregunta": t["pregunta"], "plan": {"intent": "out_of_scope", "answer": "no"}}
        for t in grabaciones["casos"][primero]
    ]
    archivo = tmp_path / "ventas.json"
    archivo.write_text(json.dumps(grabaciones), encoding="utf-8")
    argumentos = ["--recorded", str(archivo), "--out", str(tmp_path / "out")]
    assert main(argumentos) == 1
    assert main([*argumentos, "--min-accuracy", "0.9"]) == 0


def test_falla_con_un_caso_sin_grabacion(tmp_path: Path) -> None:
    archivo = tmp_path / "ventas.json"
    archivo.write_text(json.dumps({"casos": {}}), encoding="utf-8")
    assert main(["--recorded", str(archivo), "--out", str(tmp_path / "out")]) == 2


def _caso(caso_id: str) -> Caso:
    return Caso(id=caso_id, lang="es", question="q", tags=["x"], expect_out_of_scope=True)
