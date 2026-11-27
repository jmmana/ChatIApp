"""Línea de comandos de la evaluación (desde `backend/`):

    uv run python -m app.eval run --set evals/ventas --providers claude,deepseek
    uv run python -m app.eval run --providers claude,deepseek --max-calls 400 --yes

Con proveedores reales (todo `kind` distinto de `fake`) la corrida es un ensayo por defecto:
imprime cuántas llamadas haría y a qué modelos, y sale con 0 sin llamar a nadie. Para ejecutarla
hacen falta `--yes` y `--max-calls N`; la corrida se aborta antes de pasar de N llamadas. Los
proveedores `fake` son gratis y no tienen control de gasto. Nunca se imprimen ni se escriben claves.

Los proveedores se buscan por nombre en la base de la app (`CHATIAPP_DATABASE_URL`), donde los
deja el arranque a partir de `chatiapp.yaml`. Por cada uno se corre todo el set, se guarda un
`EVAL_RUN` y se escriben `<set>.md` y `<set>.json` en `--out`.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Iterator, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import EvalRun, Provider
from app.db.session import get_engine
from app.eval import report
from app.eval.golden import RAIZ_SET, Caso, SetDorado, cargar
from app.eval.runner import MODELO_VENTAS, ResultadoCaso, cargar_modelo, evaluar
from app.llm.gateway import Completion, Gateway, JsonCompletion, ProviderConfig, StreamEvent
from app.semantic.schema import SemanticModel

SessionFactory = Callable[[], Session]
GatewayFactory = Callable[[Provider], Gateway]


def _gateway(provider: Provider) -> Gateway:
    return Gateway(ProviderConfig.from_provider(provider))


class PresupuestoAgotado(BaseException):  # noqa: N818
    """Se llegó al tope de `--max-calls`. Es `BaseException` para que ningún `except Exception`
    del orquestador o del runner la convierta en el fallo de un caso y la corrida siga."""


class Presupuesto:
    """Cuenta las llamadas a proveedores reales y corta antes de pasar del tope."""

    def __init__(self, maximo: int) -> None:
        self.maximo = maximo
        self.hechas = 0

    def tomar(self) -> None:
        if self.hechas >= self.maximo:
            raise PresupuestoAgotado
        self.hechas += 1


class GatewayMedido(Gateway):
    """Cuenta cada llamada de `interno` contra el presupuesto antes de hacerla."""

    def __init__(self, interno: Gateway, presupuesto: Presupuesto) -> None:
        super().__init__(interno.provider)
        self._interno = interno
        self._presupuesto = presupuesto

    def complete(self, messages: list[dict[str, str]], **params: Any) -> Completion:
        self._presupuesto.tomar()
        return self._interno.complete(messages, **params)

    def complete_json[T: BaseModel](
        self, messages: list[dict[str, str]], schema: type[T], **params: Any
    ) -> JsonCompletion[T]:
        self._presupuesto.tomar()
        return self._interno.complete_json(messages, schema, **params)

    def stream(self, messages: list[dict[str, str]], **params: Any) -> Iterator[StreamEvent]:
        self._presupuesto.tomar()
        return self._interno.stream(messages, **params)


def es_real(provider: Provider) -> bool:
    return provider.kind != "fake"


def _llamadas_caso(caso: Caso) -> int:
    """Cota superior: cada turno (previos, pregunta y respuestas de aclaración) hace como mucho
    una llamada de plan y una de redacción."""
    return 2 * (1 + len(caso.previous) + len(caso.answers))


def llamadas_previstas(conjunto: SetDorado) -> int:
    """Llamadas que haría un proveedor real con todo el set."""
    return sum(_llamadas_caso(c) for c in conjunto.casos)


def _nombres(valor: str) -> list[str]:
    return [n.strip() for n in valor.split(",") if n.strip()]


def buscar_proveedores(session: Session, nombres: Sequence[str]) -> list[Provider]:
    """Los proveedores por nombre, en el orden pedido; `ValueError` si alguno no existe."""
    encontrados = {
        p.name: p for p in session.scalars(select(Provider).where(Provider.name.in_(nombres)))
    }
    faltan = [n for n in nombres if n not in encontrados]
    if faltan:
        disponibles = sorted(session.scalars(select(Provider.name)))
        raise ValueError(
            f"proveedores desconocidos: {', '.join(faltan)}. "
            f"Disponibles: {', '.join(disponibles) or 'ninguno'}"
        )
    return [encontrados[n] for n in nombres]


def guardar_eval_run(
    session: Session, provider: Provider, nombre_set: str, resumen: report.Informe
) -> EvalRun:
    """Guarda el resultado de un proveedor como un `EVAL_RUN`."""
    run = EvalRun(
        provider_id=provider.id,
        eval_set=nombre_set,
        accuracy=resumen["exactitud"],
        p50_latency_ms=resumen["latencia_ms"]["p50"],
        cost_usd=Decimal(str(resumen["costo_usd"])),
        details=resumen,
    )
    session.add(run)
    session.commit()
    return run


def _avisar(
    callback: Callable[[str, ResultadoCaso], None] | None, proveedor: str
) -> Callable[[ResultadoCaso], None] | None:
    """El runner no sabe de qué proveedor es cada caso: el nombre se fija aquí."""
    if callback is None:
        return None

    def aviso(resultado: ResultadoCaso) -> None:
        callback(proveedor, resultado)

    return aviso


def resolver_set(ruta: Path) -> Path:
    """`evals/ventas` se busca desde el directorio actual y, si no está, desde la raíz del repo."""
    if ruta.is_absolute() or ruta.exists():
        return ruta
    return RAIZ_SET.parents[1] / ruta


def evaluar_proveedores(
    session: Session,
    conjunto: SetDorado,
    model: SemanticModel,
    proveedores: Sequence[Provider],
    *,
    gateway_de: GatewayFactory = _gateway,
    al_terminar_caso: Callable[[str, ResultadoCaso], None] | None = None,
) -> report.Informe:
    """Corre el set con cada proveedor, guarda un `EVAL_RUN` por proveedor y arma el informe."""
    resumenes: list[report.Informe] = []
    for provider in proveedores:
        gateway = gateway_de(provider)
        resultados = evaluar(
            conjunto, gateway, model, al_terminar_caso=_avisar(al_terminar_caso, provider.name)
        )
        resumen = report.resumir(provider.name, provider.kind, provider.model, resultados)
        guardar_eval_run(session, provider, conjunto.config.name, resumen)
        resumenes.append(resumen)
    return report.armar_informe(conjunto.config.name, resumenes)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="app.eval", description="Evaluación de proveedores")
    comandos = parser.add_subparsers(dest="command", required=True)
    run = comandos.add_parser("run", help="Corre el set dorado contra uno o varios proveedores")
    run.add_argument("--set", dest="set_dir", type=Path, default=RAIZ_SET, help="Carpeta del set")
    run.add_argument(
        "--providers", required=True, type=_nombres, help="Nombres de proveedor, con comas"
    )
    run.add_argument("--model", type=Path, default=MODELO_VENTAS, help="Modelo semántico (YAML)")
    run.add_argument("--out", type=Path, default=Path("eval-reports"), help="Carpeta del informe")
    run.add_argument(
        "--max-calls",
        type=int,
        default=None,
        help="Tope de llamadas a proveedores reales; obligatorio con --yes si hay alguno",
    )
    run.add_argument(
        "--yes",
        action="store_true",
        help="Ejecuta de verdad con proveedores reales (sin esto solo se muestra el plan)",
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    session_factory: SessionFactory | None = None,
    gateway_de: GatewayFactory = _gateway,
) -> int:
    args = build_parser().parse_args(argv)
    factory = session_factory or sessionmaker(bind=get_engine(), expire_on_commit=False)
    try:
        conjunto = cargar(resolver_set(args.set_dir))
        model = cargar_modelo(args.model)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    with factory() as session:
        try:
            proveedores = buscar_proveedores(session, args.providers)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2

        reales = [p for p in proveedores if es_real(p)]
        presupuesto: Presupuesto | None = None
        if reales:
            por_proveedor = llamadas_previstas(conjunto)
            total = por_proveedor * len(reales)
            if not args.yes:
                print(
                    f"Ensayo: la corrida haría hasta {total} llamadas "
                    f"({len(conjunto.casos)} casos, {por_proveedor} por proveedor):",
                    file=sys.stderr,
                )
                for p in reales:
                    print(f"  - {p.name} ({p.model}): hasta {por_proveedor}", file=sys.stderr)
                print(
                    "No se llamó a ningún proveedor. Para ejecutar: --yes --max-calls N",
                    file=sys.stderr,
                )
                return 0
            if args.max_calls is None or args.max_calls < 1:
                print(
                    "error: con proveedores reales hace falta --max-calls N (N >= 1)",
                    file=sys.stderr,
                )
                return 2
            if total > args.max_calls:
                print(
                    f"error: la corrida haría hasta {total} llamadas y --max-calls es "
                    f"{args.max_calls}; no se hizo ninguna llamada. Sube el tope o reduce "
                    "proveedores.",
                    file=sys.stderr,
                )
                return 2
            presupuesto = Presupuesto(args.max_calls)
        interno = gateway_de

        def gateway_medido(provider: Provider) -> Gateway:
            gateway = interno(provider)
            if presupuesto is not None and es_real(provider):
                return GatewayMedido(gateway, presupuesto)
            return gateway

        def avance(proveedor: str, r: ResultadoCaso) -> None:
            print(f"[{proveedor}] {r.id}: {'ok' if r.correcto else 'FALLA'}", file=sys.stderr)

        try:
            informe = evaluar_proveedores(
                session,
                conjunto,
                model,
                proveedores,
                gateway_de=gateway_medido,
                al_terminar_caso=avance,
            )
        except PresupuestoAgotado:
            session.rollback()
            hechas = presupuesto.hechas if presupuesto else 0
            print(
                f"error: se alcanzó --max-calls ({args.max_calls}) tras {hechas} llamadas; "
                "corrida abortada, sin informe.",
                file=sys.stderr,
            )
            return 3
    args.out.mkdir(parents=True, exist_ok=True)
    nombre = conjunto.config.name
    (args.out / f"{nombre}.json").write_text(report.a_json(informe), encoding="utf-8")
    texto = report.a_markdown(informe)
    (args.out / f"{nombre}.md").write_text(texto, encoding="utf-8")
    print(texto)
    return 0
