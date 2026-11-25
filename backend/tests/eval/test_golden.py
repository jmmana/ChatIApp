import json
from pathlib import Path

import pytest

from app.eval.golden import ARCHIVO_VALORES, RAIZ_SET, cargar, congelar, validar

SET_MINIMO = """
name: prueba
dataset: {seed: 42, hasta: 2026-11-25}
role: gerencia_general
minimos: {es: 0, en: 0}
etiquetas_obligatorias: []
"""

CASO_OK = """
- id: caso-uno
  lang: es
  question: "¿Cuántas sucursales hay?"
  tags: [sql_libre]
  expect:
    sql: "SELECT COUNT(*) AS total FROM sucursales"
"""


def _crear(tmp_path: Path, casos: str) -> Path:
    (tmp_path / "casos").mkdir()
    (tmp_path / "set.yaml").write_text(SET_MINIMO, encoding="utf-8")
    (tmp_path / "casos" / "prueba.yaml").write_text(casos, encoding="utf-8")
    return tmp_path


def test_el_set_real_cumple_los_minimos_y_es_ejecutable() -> None:
    assert validar(RAIZ_SET) == []


def test_el_set_real_tiene_ids_unicos_y_las_tres_expectativas() -> None:
    casos = cargar(RAIZ_SET).casos
    assert len({c.id for c in casos}) == len(casos)
    assert any(c.expect_clarification for c in casos)
    assert any(c.expect_out_of_scope for c in casos)
    assert any(c.previous for c in casos)
    assert any(c.answers for c in casos)


def test_un_caso_necesita_exactamente_una_expectativa(tmp_path: Path) -> None:
    raiz = _crear(
        tmp_path,
        '- {id: caso-uno, lang: es, question: "¿Hola?", tags: [x]}\n',
    )
    with pytest.raises(ValueError, match="exactamente una"):
        cargar(raiz)


def test_rechaza_sql_de_escritura(tmp_path: Path) -> None:
    raiz = _crear(tmp_path, CASO_OK.replace("SELECT COUNT(*) AS total FROM", "DELETE FROM"))
    errores = validar(raiz)
    assert any("SELECT o WITH" in e or "escritura" in e for e in errores)


def test_rechaza_sql_que_no_se_ejecuta(tmp_path: Path) -> None:
    raiz = _crear(tmp_path, CASO_OK.replace("sucursales", "no_existe"))
    errores = validar(raiz)
    assert any("no se ejecuta" in e for e in errores)


def test_congelar_y_validar_estricto_ida_y_vuelta(tmp_path: Path) -> None:
    raiz = _crear(tmp_path, CASO_OK)
    assert congelar(raiz) == 1
    valores = json.loads((raiz / ARCHIVO_VALORES).read_text(encoding="utf-8"))
    assert valores["dataset"] == {"seed": 42, "hasta": "2026-11-25"}
    assert valores["casos"]["caso-uno"]["rows"] == [[6]]
    assert validar(raiz, estricto=True) == []


def test_valores_guardados_del_set_real_coinciden_si_existen() -> None:
    if not (RAIZ_SET / ARCHIVO_VALORES).exists():
        pytest.skip("valores.json aún no se ha generado: `python -m app.eval.golden --congelar`")
    assert validar(RAIZ_SET, estricto=True) == []
