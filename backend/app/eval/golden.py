"""Set dorado: carga, validación y congelado de los valores esperados.

Uso (desde `backend/`):

    uv run python -m app.eval.golden --validar
    uv run python -m app.eval.golden --congelar

`--congelar` genera la base de demostración con el `seed` y la fecha del set, ejecuta el SQL
escrito a mano de cada caso y guarda el resultado en `evals/ventas/valores.json`.
`--validar` comprueba la forma de los casos y que cada uno es ejecutable; con `--estricto`
exige además que los valores guardados coincidan con los que da la base hoy.
El formato está documentado en `evals/README.md`.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sqlite3
import tempfile
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.demo.seed import generar

RAIZ_SET = Path(__file__).resolve().parents[3] / "evals" / "ventas"
ARCHIVO_VALORES = "valores.json"

# Etiquetas que el set debe cubrir al menos una vez (criterio del issue #75).
ETIQUETAS_OBLIGATORIAS = (
    "metrica",
    "dimension",
    "filtro",
    "periodo",
    "aclaracion",
    "seguimiento",
    "sql_libre",
    "fuera_de_alcance",
)

_ESCRITURA = re.compile(
    r"\b(insert|update|delete|drop|alter|create|replace|attach|detach|pragma|vacuum)\b",
    re.IGNORECASE,
)

Fila = list[Any]


class Esperado(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sql: str = Field(min_length=1)
    ordered: bool = False


class Aclaracion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slot: Literal["period", "metric", "entity", "dimension"]


class Caso(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")
    lang: Literal["es", "en"]
    question: str = Field(min_length=1)
    previous: list[str] = Field(default_factory=list)
    answers: list[str] = Field(default_factory=list)
    tags: list[str] = Field(min_length=1)
    expect: Esperado | None = None
    expect_clarification: Aclaracion | None = None
    expect_out_of_scope: bool = False

    @model_validator(mode="after")
    def _una_sola_expectativa(self) -> Caso:
        definidas = [
            self.expect is not None,
            self.expect_clarification is not None,
            self.expect_out_of_scope,
        ]
        if sum(definidas) != 1:
            raise ValueError(
                "define exactamente una de `expect`, `expect_clarification` o "
                "`expect_out_of_scope`"
            )
        if self.answers and self.expect is None:
            raise ValueError("`answers` solo aplica a casos con `expect`")
        return self


class Dataset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seed: int
    hasta: date


class Minimos(BaseModel):
    model_config = ConfigDict(extra="forbid")

    es: int = 60
    en: int = 20


class ConfigSet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    dataset: Dataset
    role: str
    minimos: Minimos = Field(default_factory=Minimos)


class SetDorado(BaseModel):
    config: ConfigSet
    casos: list[Caso]


def cargar(raiz: Path = RAIZ_SET) -> SetDorado:
    """Lee `set.yaml` y todos los `casos/*.yaml`. Lanza `ValueError` con el archivo culpable."""
    try:
        config = ConfigSet.model_validate(yaml.safe_load((raiz / "set.yaml").read_text("utf-8")))
    except (OSError, yaml.YAMLError, ValidationError) as exc:
        raise ValueError(f"set.yaml: {exc}") from exc
    casos: list[Caso] = []
    for ruta in sorted((raiz / "casos").glob("*.yaml")):
        try:
            datos = yaml.safe_load(ruta.read_text("utf-8"))
            if not isinstance(datos, list):
                raise ValueError("debe ser una lista de casos")
            casos.extend(Caso.model_validate(d) for d in datos)
        except (yaml.YAMLError, ValidationError, ValueError) as exc:
            raise ValueError(f"{ruta.name}: {exc}") from exc
    return SetDorado(config=config, casos=casos)


def _comprobar_sql(sql: str) -> str | None:
    """Devuelve el motivo si el SQL no es una única consulta de solo lectura."""
    limpio = sql.strip().rstrip(";")
    if ";" in limpio:
        return "tiene más de una sentencia"
    if not re.match(r"(?is)^\s*(select|with)\b", limpio):
        return "debe empezar con SELECT o WITH"
    if _ESCRITURA.search(limpio):
        return "contiene palabras de escritura"
    return None


def _ejecutar(conn: sqlite3.Connection, sql: str) -> tuple[list[str], list[Fila]]:
    cursor = conn.execute(sql)
    columnas = [d[0] for d in cursor.description]
    return columnas, [list(f) for f in cursor.fetchall()]


def _clave(fila: Fila) -> str:
    return json.dumps(fila, ensure_ascii=False, default=str)


def _iguales(a: Any, b: Any) -> bool:
    if isinstance(a, int | float) and isinstance(b, int | float):
        return math.isclose(a, b, rel_tol=1e-9, abs_tol=0.005)
    return bool(a == b)


def _coinciden(obtenido: list[Fila], esperado: list[Fila], ordenado: bool) -> bool:
    if len(obtenido) != len(esperado):
        return False
    if not ordenado:
        obtenido = sorted(obtenido, key=_clave)
        esperado = sorted(esperado, key=_clave)
    return all(
        len(a) == len(b) and all(_iguales(x, y) for x, y in zip(a, b, strict=True))
        for a, b in zip(obtenido, esperado, strict=True)
    )


def _abrir_demo(config: ConfigSet, carpeta: Path) -> sqlite3.Connection:
    ruta = carpeta / "ventas.db"
    generar(ruta, seed=config.dataset.seed, hasta=config.dataset.hasta)
    conn = sqlite3.connect(f"{ruta.as_uri()}?mode=ro", uri=True)
    conn.execute("PRAGMA query_only = ON")
    return conn


def _leer_valores(raiz: Path) -> dict[str, Any] | None:
    ruta = raiz / ARCHIVO_VALORES
    if not ruta.exists():
        return None
    datos: dict[str, Any] = json.loads(ruta.read_text("utf-8"))
    return datos


def validar(raiz: Path = RAIZ_SET, estricto: bool = False) -> list[str]:
    """Devuelve la lista de problemas del set (vacía si es válido y ejecutable).

    Sin `estricto`, los casos sin valores guardados no son un error; con `estricto` sí.
    """
    try:
        conjunto = cargar(raiz)
    except ValueError as exc:
        return [str(exc)]
    config = conjunto.config
    errores: list[str] = []

    ids = [c.id for c in conjunto.casos]
    errores += [f"id repetido: {i}" for i in sorted({i for i in ids if ids.count(i) > 1})]
    for lang, minimo in (("es", config.minimos.es), ("en", config.minimos.en)):
        total = sum(1 for c in conjunto.casos if c.lang == lang)
        if total < minimo:
            errores.append(f"casos en «{lang}»: {total}, se exigen al menos {minimo}")
    etiquetas = {t for c in conjunto.casos for t in c.tags}
    errores += [
        f"ningún caso cubre la etiqueta «{t}»"
        for t in ETIQUETAS_OBLIGATORIAS
        if t not in etiquetas
    ]
    for caso in conjunto.casos:
        if caso.expect and (motivo := _comprobar_sql(caso.expect.sql)):
            errores.append(f"{caso.id}: el SQL {motivo}")
    if errores:
        return errores

    valores = _leer_valores(raiz)
    if valores is not None:
        esperado_ds = {"seed": config.dataset.seed, "hasta": config.dataset.hasta.isoformat()}
        if valores.get("dataset") != esperado_ds:
            errores.append(
                f"{ARCHIVO_VALORES} se calculó con {valores.get('dataset')}, "
                f"pero set.yaml declara {esperado_ds}: vuelve a congelar"
            )
    guardados: dict[str, Any] = (valores or {}).get("casos", {})

    with tempfile.TemporaryDirectory() as tmp:
        conn = _abrir_demo(config, Path(tmp))
        try:
            for caso in conjunto.casos:
                if caso.expect is None:
                    continue
                try:
                    _, filas = _ejecutar(conn, caso.expect.sql)
                except sqlite3.Error as exc:
                    errores.append(f"{caso.id}: el SQL no se ejecuta: {exc}")
                    continue
                if not filas or all(v is None for f in filas for v in f):
                    errores.append(f"{caso.id}: el SQL no devuelve datos")
                    continue
                if caso.id not in guardados:
                    if estricto:
                        errores.append(f"{caso.id}: sin valores en {ARCHIVO_VALORES}")
                    continue
                esperado = guardados[caso.id]["rows"]
                if not _coinciden(filas, esperado, caso.expect.ordered):
                    errores.append(f"{caso.id}: el resultado ya no coincide con {ARCHIVO_VALORES}")
        finally:
            conn.close()
    if estricto:
        sobrantes = sorted(set(guardados) - set(ids))
        errores += [f"{ARCHIVO_VALORES} tiene un caso que ya no existe: {i}" for i in sobrantes]
    return errores


def congelar(raiz: Path = RAIZ_SET) -> int:
    """Calcula los valores esperados con el SQL de cada caso y los guarda. Devuelve cuántos."""
    conjunto = cargar(raiz)
    config = conjunto.config
    casos: dict[str, Any] = {}
    with tempfile.TemporaryDirectory() as tmp:
        conn = _abrir_demo(config, Path(tmp))
        try:
            for caso in conjunto.casos:
                if caso.expect is None:
                    continue
                columnas, filas = _ejecutar(conn, caso.expect.sql)
                casos[caso.id] = {"columns": columnas, "rows": filas}
        finally:
            conn.close()
    salida = {
        "dataset": {"seed": config.dataset.seed, "hasta": config.dataset.hasta.isoformat()},
        "casos": casos,
    }
    (raiz / ARCHIVO_VALORES).write_text(
        json.dumps(salida, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    return len(casos)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Valida o congela el set dorado.")
    accion = parser.add_mutually_exclusive_group(required=True)
    accion.add_argument("--validar", action="store_true", help="Comprueba el set")
    accion.add_argument("--congelar", action="store_true", help="Recalcula valores.json")
    parser.add_argument("--estricto", action="store_true", help="Exige valores para cada caso")
    parser.add_argument("--dir", type=Path, default=RAIZ_SET, help="Carpeta del set")
    args = parser.parse_args(argv)
    if args.congelar:
        total = congelar(args.dir)
        print(f"{total} casos con valores guardados en {args.dir / ARCHIVO_VALORES}")
        return 0
    errores = validar(args.dir, estricto=args.estricto)
    for e in errores:
        print(f"ERROR {e}")
    if not errores:
        print("Set dorado válido")
    return 1 if errores else 0


if __name__ == "__main__":
    raise SystemExit(main())
