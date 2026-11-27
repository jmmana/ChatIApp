"""Evaluación de modelos: lanza el set dorado contra proveedores y expone el avance y el informe.

La corrida se hace en un hilo aparte (puede tardar minutos) y su estado vive en memoria: se pierde
al reiniciar, pero cada proveedor deja su `EVAL_RUN` en la base. Solo corre una a la vez.
Con proveedores reales hace falta `max_calls`, igual que en la CLI (`python -m app.eval`).
"""

import threading
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.api.errors import ApiError
from app.db.models import Provider
from app.db.session import get_engine, get_session
from app.eval.cli import (
    GatewayFactory,
    GatewayMedido,
    Presupuesto,
    PresupuestoAgotado,
    _gateway,
    es_real,
    evaluar_proveedores,
    llamadas_previstas,
)
from app.eval.golden import RAIZ_SET, SetDorado, cargar
from app.eval.runner import MODELO_VENTAS, ResultadoCaso, cargar_modelo
from app.llm.gateway import Gateway

router = APIRouter(prefix="/evals", tags=["evaluación"])

SessionDep = Annotated[Session, Depends(get_session)]
SessionFactory = Callable[[], Session]
Estado = Literal["running", "done", "error"]


def get_session_factory() -> SessionFactory:
    """Fábrica de sesiones para el hilo de la corrida (las pruebas la sustituyen)."""
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def get_gateway_factory() -> GatewayFactory:
    return _gateway


SessionFactoryDep = Annotated[SessionFactory, Depends(get_session_factory)]
GatewayFactoryDep = Annotated[GatewayFactory, Depends(get_gateway_factory)]


class EvalRunCreate(BaseModel):
    provider_ids: list[uuid.UUID] = Field(min_length=1, max_length=10)
    # Tope de llamadas a proveedores reales; obligatorio si alguno lo es.
    max_calls: int | None = Field(default=None, ge=1)


class EvalProviderOut(BaseModel):
    id: uuid.UUID
    name: str
    kind: str
    model: str


class EvalRunOut(BaseModel):
    id: uuid.UUID
    status: Estado
    created_at: datetime
    providers: list[EvalProviderOut]
    cases_total: int
    cases_done: int
    error: str | None
    # Informe de `app.eval.report`: `proveedores[]` con exactitud, latencia, costo y `fallidos`.
    report: dict[str, Any] | None


class _Corrida:
    def __init__(self, providers: list[Provider], cases_total: int) -> None:
        self.id = uuid.uuid4()
        self.status: Estado = "running"
        self.created_at = datetime.now(UTC)
        self.providers = [
            EvalProviderOut(id=p.id, name=p.name, kind=p.kind, model=p.model) for p in providers
        ]
        self.cases_total = cases_total
        self.cases_done = 0
        self.error: str | None = None
        self.report: dict[str, Any] | None = None

    def out(self) -> EvalRunOut:
        return EvalRunOut(
            id=self.id,
            status=self.status,
            created_at=self.created_at,
            providers=self.providers,
            cases_total=self.cases_total,
            cases_done=self.cases_done,
            error=self.error,
            report=self.report,
        )


_CORRIDAS: dict[uuid.UUID, _Corrida] = {}
_LOCK = threading.Lock()


def cargar_set() -> SetDorado:
    return cargar(RAIZ_SET)


def _ejecutar(
    corrida: _Corrida,
    provider_ids: list[uuid.UUID],
    conjunto: SetDorado,
    session_factory: SessionFactory,
    gateway_de: GatewayFactory,
    presupuesto: Presupuesto | None,
) -> None:
    def gateway_medido(provider: Provider) -> Gateway:
        gateway = gateway_de(provider)
        if presupuesto is not None and es_real(provider):
            return GatewayMedido(gateway, presupuesto)
        return gateway

    def avance(_proveedor: str, _resultado: ResultadoCaso) -> None:
        corrida.cases_done += 1

    try:
        with session_factory() as session:
            por_id = {p.id: p for p in session.scalars(select(Provider))}
            informe = evaluar_proveedores(
                session,
                conjunto,
                cargar_modelo(MODELO_VENTAS),
                [por_id[i] for i in provider_ids],
                gateway_de=gateway_medido,
                al_terminar_caso=avance,
            )
        corrida.report = informe
        corrida.status = "done"
    except PresupuestoAgotado:
        corrida.error = "Se alcanzó el tope de llamadas; la corrida se abortó sin informe."
        corrida.status = "error"
    except Exception as exc:  # un fallo del hilo se informa en la corrida, no se pierde
        corrida.error = f"La corrida falló: {exc}"
        corrida.status = "error"


@router.post("/runs", status_code=202, summary="Lanza una corrida del set dorado")
def create_run(
    body: EvalRunCreate,
    session: SessionDep,
    session_factory: SessionFactoryDep,
    gateway_de: GatewayFactoryDep,
) -> EvalRunOut:
    ids = list(dict.fromkeys(body.provider_ids))
    por_id = {p.id: p for p in session.scalars(select(Provider).where(Provider.id.in_(ids)))}
    missing = [str(i) for i in ids if i not in por_id]
    if missing:
        raise ApiError(404, "provider_not_found", "Proveedor no encontrado.", {"ids": missing})
    providers = [por_id[i] for i in ids]
    try:
        conjunto = cargar_set()
    except ValueError as exc:
        raise ApiError(500, "eval_set_invalid", f"El set no es válido: {exc}") from exc

    presupuesto: Presupuesto | None = None
    reales = [p for p in providers if es_real(p)]
    if reales:
        previstas = llamadas_previstas(conjunto) * len(reales)
        if body.max_calls is None or body.max_calls < previstas:
            raise ApiError(
                422,
                "max_calls_required",
                f"Con proveedores reales indica un tope de llamadas de al menos {previstas}.",
                {"planned_calls": previstas},
            )
        presupuesto = Presupuesto(body.max_calls)

    with _LOCK:
        if any(c.status == "running" for c in _CORRIDAS.values()):
            raise ApiError(409, "eval_in_progress", "Ya hay una evaluación en curso.")
        corrida = _Corrida(providers, len(conjunto.casos) * len(providers))
        _CORRIDAS[corrida.id] = corrida
    threading.Thread(
        target=_ejecutar,
        args=(corrida, ids, conjunto, session_factory, gateway_de, presupuesto),
        daemon=True,
    ).start()
    return corrida.out()


@router.get("/runs", summary="Corridas de evaluación, la más reciente primero")
def list_runs() -> list[EvalRunOut]:
    corridas = sorted(_CORRIDAS.values(), key=lambda c: c.created_at, reverse=True)
    return [c.out() for c in corridas]


@router.get("/runs/{run_id}", summary="Una corrida de evaluación")
def get_run(run_id: uuid.UUID) -> EvalRunOut:
    corrida = _CORRIDAS.get(run_id)
    if corrida is None:
        raise ApiError(404, "eval_run_not_found", "La corrida no existe.")
    return corrida.out()
