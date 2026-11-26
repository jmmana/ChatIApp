"""Línea de comandos de la evaluación (desde `backend/`):

    uv run python -m app.eval run --set evals/ventas --providers claude,deepseek

Los proveedores se buscan por nombre en la base de la app (`CHATIAPP_DATABASE_URL`), donde los
deja el arranque a partir de `chatiapp.yaml`. Por cada uno se corre todo el set, se guarda un
`EVAL_RUN` y se escriben `<set>.md` y `<set>.json` en `--out`.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import EvalRun, Provider
from app.db.session import get_engine
from app.eval import report
from app.eval.golden import RAIZ_SET, SetDorado, cargar
from app.eval.runner import MODELO_VENTAS, ResultadoCaso, cargar_modelo, evaluar
from app.llm.gateway import Gateway, ProviderConfig
from app.semantic.schema import SemanticModel

SessionFactory = Callable[[], Session]
GatewayFactory = Callable[[Provider], Gateway]


def _gateway(provider: Provider) -> Gateway:
    return Gateway(ProviderConfig.from_provider(provider))


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
    parser = argparse.ArgumentParser(prog="app.eval", description="Evaluación de proveedores de IA")
    comandos = parser.add_subparsers(dest="command", required=True)
    run = comandos.add_parser("run", help="Corre el set dorado contra uno o varios proveedores")
    run.add_argument("--set", dest="set_dir", type=Path, default=RAIZ_SET, help="Carpeta del set")
    run.add_argument(
        "--providers", required=True, type=_nombres, help="Nombres de proveedor, separados por coma"
    )
    run.add_argument("--model", type=Path, default=MODELO_VENTAS, help="Modelo semántico (YAML)")
    run.add_argument("--out", type=Path, default=Path("eval-reports"), help="Carpeta del informe")
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

        def avance(proveedor: str, r: ResultadoCaso) -> None:
            print(f"[{proveedor}] {r.id}: {'ok' if r.correcto else 'FALLA'}", file=sys.stderr)

        informe = evaluar_proveedores(
            session, conjunto, model, proveedores, gateway_de=gateway_de, al_terminar_caso=avance
        )
    args.out.mkdir(parents=True, exist_ok=True)
    nombre = conjunto.config.name
    (args.out / f"{nombre}.json").write_text(report.a_json(informe), encoding="utf-8")
    texto = report.a_markdown(informe)
    (args.out / f"{nombre}.md").write_text(texto, encoding="utf-8")
    print(texto)
    return 0
