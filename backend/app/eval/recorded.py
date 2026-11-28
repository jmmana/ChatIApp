"""Evaluación del set dorado con un proveedor que reproduce planes fijos, sin red ni tokens.

Uso desde `backend/`:

    uv run python -m app.eval.recorded
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from app.eval import report
from app.eval.golden import Caso, SetDorado, cargar, validar
from app.eval.runner import MODELO_VENTAS, cargar_modelo, evaluar
from app.llm.gateway import (
    Completion,
    Gateway,
    GatewayError,
    JsonCompletion,
    ProviderConfig,
    StreamEvent,
    Usage,
)

RAIZ_REPO = Path(__file__).resolve().parents[3]
ARCHIVO_PLANES = RAIZ_REPO / "evals" / "recorded" / "ventas.yaml"


class CasoGrabado(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    plan: Literal["sql", "aclaracion", "fuera_de_alcance", "respuesta_aclaracion"]
    slot: Literal["period", "metric", "entity", "dimension"] | None = None

    @model_validator(mode="after")
    def validar_slot(self) -> CasoGrabado:
        if (self.plan == "respuesta_aclaracion") != (self.slot is not None):
            raise ValueError(
                "«respuesta_aclaracion» requiere slot y los demás planes no lo admiten"
            )
        return self


class ConfigGrabada(BaseModel):
    model_config = ConfigDict(extra="forbid")

    baseline_sql: str
    answer: str
    casos: list[CasoGrabado]


@dataclass(frozen=True)
class EntradaGrabada:
    caso: str
    etapa: str
    pregunta: str
    plan: dict[str, Any]


def cargar_planes(ruta: Path = ARCHIVO_PLANES) -> ConfigGrabada:
    """Carga el mapa de planes grabados, con errores que identifican el archivo."""
    try:
        return ConfigGrabada.model_validate(yaml.safe_load(ruta.read_text("utf-8")))
    except (OSError, yaml.YAMLError, ValidationError) as exc:
        raise ValueError(f"{ruta}: {exc}") from exc


def _entradas(conjunto: SetDorado, config: ConfigGrabada) -> list[EntradaGrabada]:
    grabados = {registro.id: registro for registro in config.casos}
    if len(grabados) != len(config.casos):
        raise ValueError("hay ids de caso repetidos en los planes grabados")
    ids = {caso.id for caso in conjunto.casos}
    faltantes = sorted(ids - grabados.keys())
    sobrantes = sorted(grabados.keys() - ids)
    if faltantes or sobrantes:
        detalle = []
        if faltantes:
            detalle.append(f"sin plan grabado: {', '.join(faltantes)}")
        if sobrantes:
            detalle.append(f"planes sin caso: {', '.join(sobrantes)}")
        raise ValueError("; ".join(detalle))

    entradas: list[EntradaGrabada] = []
    for caso in conjunto.casos:
        for indice, pregunta in enumerate(caso.previous):
            entradas.append(
                EntradaGrabada(
                    caso.id,
                    f"previous-{indice}",
                    pregunta,
                    {"intent": "sql", "sql": config.baseline_sql},
                )
            )
        entradas.append(
            EntradaGrabada(
                caso.id,
                "question",
                caso.question,
                _plan(caso, grabados[caso.id].plan, config, grabados[caso.id].slot),
            )
        )
        if grabados[caso.id].plan == "respuesta_aclaracion":
            assert caso.answers and caso.expect is not None
            for indice, respuesta in enumerate(caso.answers):
                plan = (
                    {"intent": "sql", "sql": caso.expect.sql}
                    if indice == len(caso.answers) - 1
                    else _aclaracion_plan(grabados[caso.id].slot)
                )
                entradas.append(
                    EntradaGrabada(
                        caso.id,
                        f"answer-{indice}",
                        respuesta,
                        plan,
                    )
                )
    return entradas


def _plan(caso: Caso, tipo: str, config: ConfigGrabada, slot: str | None = None) -> dict[str, Any]:
    if caso.answers and tipo != "respuesta_aclaracion":
        raise ValueError(f"{caso.id}: sus respuestas requieren un plan `respuesta_aclaracion`")
    if tipo == "sql" and caso.expect is not None:
        return {"intent": "sql", "sql": caso.expect.sql}
    if tipo == "aclaracion" and caso.expect_clarification is not None:
        return {
            "intent": "clarify",
            "clarification": {
                "question": "Indica un dato para continuar.",
                "slot": caso.expect_clarification.slot,
            },
        }
    if tipo == "respuesta_aclaracion" and caso.answers and caso.expect is not None:
        return _aclaracion_plan(slot)
    if tipo == "fuera_de_alcance" and caso.expect_out_of_scope:
        return {"intent": "out_of_scope", "answer": config.answer}
    raise ValueError(f"{caso.id}: el tipo de plan grabado «{tipo}» no coincide con su expectativa")


def _aclaracion_plan(slot: str | None) -> dict[str, Any]:
    return {
        "intent": "clarify",
        "clarification": {
            "question": "Indica un dato para continuar.",
            "slot": slot,
        },
    }


class ProveedorGrabado(Gateway):
    """Reproduce los planes del fixture y falla si el flujo cambia o falta una grabación."""

    def __init__(self, entradas: Sequence[EntradaGrabada]) -> None:
        super().__init__(ProviderConfig("recorded", "planes-fijos"))
        self.entradas = list(entradas)
        self.indice = 0

    def complete_json[T: BaseModel](
        self, messages: list[dict[str, str]], schema: type[T], **params: Any
    ) -> JsonCompletion[T]:
        if self.indice >= len(self.entradas):
            raise GatewayError("provider_error", "El flujo pidió un plan grabado inexistente.")
        entrada = self.entradas[self.indice]
        pregunta = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
        if pregunta != entrada.pregunta:
            raise GatewayError(
                "provider_error",
                f"Plan desalineado en {entrada.caso}/{entrada.etapa}; revise el fixture grabado.",
            )
        self.indice += 1
        try:
            plan = schema.model_validate(entrada.plan)
        except ValidationError as exc:
            raise GatewayError(
                "provider_error", f"Plan grabado inválido en {entrada.caso}/{entrada.etapa}."
            ) from exc
        return JsonCompletion(plan, Usage())

    def complete(self, messages: list[dict[str, str]], **params: Any) -> Completion:
        raise GatewayError("provider_error", "La evaluación grabada no admite reparaciones.")

    def stream(self, messages: list[dict[str, str]], **params: Any) -> Iterator[StreamEvent]:
        yield StreamEvent(delta="Respuesta determinista.")
        yield StreamEvent(usage=Usage())

    def assert_consumed(self) -> None:
        if self.indice != len(self.entradas):
            entrada = self.entradas[self.indice]
            raise ValueError(
                f"Grabación sin consumir en {entrada.caso}/{entrada.etapa}: "
                "el flujo del agente cambió."
            )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evalúa el set dorado con planes grabados.")
    parser.add_argument("--set", dest="set_dir", type=Path, help="Carpeta del set dorado")
    parser.add_argument("--plans", type=Path, default=ARCHIVO_PLANES, help="Fixture de planes")
    parser.add_argument("--model", type=Path, default=MODELO_VENTAS, help="Modelo semántico")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        conjunto = cargar(args.set_dir) if args.set_dir else cargar()
        errores = validar(args.set_dir, estricto=True) if args.set_dir else validar(estricto=True)
        if errores:
            raise ValueError("set dorado inválido: " + "; ".join(errores))
        config = cargar_planes(args.plans)
        entradas = _entradas(conjunto, config)
        model = cargar_modelo(args.model)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    proveedor = ProveedorGrabado(entradas)
    resultados = evaluar(conjunto, proveedor, model)
    try:
        proveedor.assert_consumed()
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    resumen = report.resumir("grabado", "recorded", "planes-fijos", resultados)
    informe = report.armar_informe(conjunto.config.name, [resumen])
    markdown = report.a_markdown(informe)
    print(markdown, end="")
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with Path(summary_path).open("a", encoding="utf-8") as summary_file:
            summary_file.write(markdown)
    return 0 if resumen["exactitud"] == 1.0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
