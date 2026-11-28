"""Evaluación en CI con planes grabados: sin red, sin tokens y determinista.

El proveedor grabado (`GatewayGrabado`) no llama a ninguna IA: por cada caso del set dorado
responde con el plan guardado en `evals/recorded/<set>.json`. Con planes fijos, lo que se mide es
el motor y el agente (guardián, ejecutor, aclaraciones, comparación de resultados), así que la
exactitud esperada es 100 % y cualquier caída es una regresión.

    uv run python -m app.eval.recorded --set evals/ventas --out eval-reports --min-accuracy 1.0

Escribe `<set>-grabado.md` y `<set>-grabado.json` en `--out` y, si se pasa `--summary` (en GitHub
Actions, `$GITHUB_STEP_SUMMARY`), añade el reporte Markdown al resumen del job. Sale con 1 si la
exactitud queda por debajo de `--min-accuracy`.

Formato del archivo de grabaciones (`casos`: id del caso → un elemento por turno, en orden):

    {"set": "ventas", "casos": {"per-es-mes-pasado": [{"pregunta": "...", "plan": {...}}]}}
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from app.eval import report
from app.eval.golden import RAIZ_SET, Caso, SetDorado, cargar
from app.eval.runner import MODELO_VENTAS, ResultadoCaso, cargar_modelo, evaluar
from app.llm.gateway import (
    Completion,
    Gateway,
    GatewayError,
    JsonCompletion,
    ProviderConfig,
    StreamEvent,
    Usage,
)

TEXTO_GRABADO = "Respuesta grabada."
KIND = "fake"
MODELO = "grabado"

Turno = dict[str, Any]


def ruta_grabaciones(raiz_set: Path) -> Path:
    """`evals/recorded/<nombre del set>.json`, junto a la carpeta del set."""
    return raiz_set.parent / "recorded" / f"{raiz_set.name}.json"


def cargar_grabaciones(ruta: Path) -> dict[str, list[Turno]]:
    """Lee el archivo de grabaciones; `ValueError` si no existe o no tiene la forma esperada."""
    try:
        datos = json.loads(ruta.read_text("utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{ruta}: {exc}") from exc
    casos = datos.get("casos") if isinstance(datos, dict) else None
    if not isinstance(casos, dict):
        raise ValueError(f"{ruta}: falta el objeto «casos»")
    for caso_id, turnos in casos.items():
        if not isinstance(turnos, list) or not all(
            isinstance(t, dict) and isinstance(t.get("pregunta"), str) and "plan" in t
            for t in turnos
        ):
            raise ValueError(f"{ruta}: «{caso_id}» debe ser una lista de {{pregunta, plan}}")
    return {str(k): list(v) for k, v in casos.items()}


def faltantes(conjunto: SetDorado, grabaciones: dict[str, list[Turno]]) -> list[str]:
    """Casos del set sin grabación y grabaciones de casos que ya no existen."""
    ids = {c.id for c in conjunto.casos}
    problemas = [f"{c.id}: sin plan grabado" for c in conjunto.casos if c.id not in grabaciones]
    problemas += [f"{i}: grabación de un caso que ya no existe" for i in sorted(set(grabaciones) - ids)]
    return problemas


class GatewayGrabado(Gateway):
    """Responde con el plan grabado del caso en curso. Sin red y sin azar.

    `empezar_caso` elige las grabaciones; cada llamada de plan toma el siguiente turno cuya
    pregunta coincide con el mensaje del usuario (los reintentos con plan rechazado empiezan con
    la misma pregunta). Si no hay grabación para la pregunta, falla como un error del proveedor.
    """

    def __init__(self, grabaciones: dict[str, list[Turno]]) -> None:
        super().__init__(ProviderConfig(KIND, MODELO))
        self._grabaciones = grabaciones
        self._turnos: list[Turno] = []
        self._cursor = 0

    def empezar_caso(self, caso: Caso) -> None:
        self._turnos = self._grabaciones.get(caso.id, [])
        self._cursor = 0

    def _siguiente(self, messages: list[dict[str, str]]) -> Turno:
        pregunta = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
        for i in range(self._cursor, len(self._turnos)):
            if pregunta.startswith(self._turnos[i]["pregunta"]):
                self._cursor = i + 1
                return self._turnos[i]
        raise GatewayError("provider_error", f"Sin plan grabado para «{pregunta[:80]}».")

    def complete_json[T: BaseModel](
        self, messages: list[dict[str, str]], schema: type[T], **params: Any
    ) -> JsonCompletion[T]:
        turno = self._siguiente(messages)
        try:
            return JsonCompletion(schema.model_validate(turno["plan"]), Usage())
        except ValidationError as exc:
            raise GatewayError("provider_error", f"Plan grabado inválido: {exc}") from exc

    def complete(self, messages: list[dict[str, str]], **params: Any) -> Completion:
        return Completion(TEXTO_GRABADO, Usage())

    def stream(self, messages: list[dict[str, str]], **params: Any) -> Iterator[StreamEvent]:
        yield StreamEvent(delta=TEXTO_GRABADO)
        yield StreamEvent(usage=Usage())


def evaluar_grabado(conjunto: SetDorado, grabaciones: dict[str, list[Turno]]) -> report.Informe:
    """Corre el set con el proveedor grabado y devuelve el informe de un solo «proveedor»."""
    gateway = GatewayGrabado(grabaciones)
    resultados: list[ResultadoCaso] = evaluar(
        conjunto, gateway, cargar_modelo(), al_empezar_caso=gateway.empezar_caso
    )
    resumen = report.resumir("grabado", KIND, MODELO, resultados)
    return report.armar_informe(conjunto.config.name, [resumen])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="app.eval.recorded", description="Evalúa el motor con planes grabados"
    )
    parser.add_argument("--set", dest="set_dir", type=Path, default=RAIZ_SET, help="Carpeta del set")
    parser.add_argument(
        "--recorded", type=Path, default=None, help="Archivo de grabaciones (por defecto, el del set)"
    )
    parser.add_argument("--out", type=Path, default=Path("eval-reports"), help="Carpeta del informe")
    parser.add_argument(
        "--min-accuracy",
        type=float,
        default=1.0,
        help="Exactitud mínima (0 a 1); por debajo, sale con código 1",
    )
    parser.add_argument(
        "--summary", type=Path, default=None, help="Archivo al que añadir el informe en Markdown"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    raiz = args.set_dir if args.set_dir.is_absolute() or args.set_dir.exists() else (
        RAIZ_SET.parents[1] / args.set_dir
    )
    try:
        conjunto = cargar(raiz)
        grabaciones = cargar_grabaciones(args.recorded or ruta_grabaciones(raiz))
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    problemas = faltantes(conjunto, grabaciones)
    if problemas:
        for p in problemas:
            print(f"error: {p}", file=sys.stderr)
        return 2
    informe = evaluar_grabado(conjunto, grabaciones)
    nombre = f"{conjunto.config.name}-grabado"
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / f"{nombre}.json").write_text(report.a_json(informe), encoding="utf-8")
    texto = report.a_markdown(informe)
    (args.out / f"{nombre}.md").write_text(texto, encoding="utf-8")
    print(texto)
    if args.summary is not None:
        with args.summary.open("a", encoding="utf-8") as f:
            f.write(texto + "\n")
    exactitud: float = informe["proveedores"][0]["exactitud"]
    if exactitud < args.min_accuracy:
        for r in informe["proveedores"][0].get("fallos", []):
            print(f"FALLA {r}", file=sys.stderr)
        print(
            f"error: exactitud {exactitud:.1%} por debajo del mínimo {args.min_accuracy:.1%}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
