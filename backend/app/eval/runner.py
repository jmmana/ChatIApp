"""Runner de evaluación: ejecuta el set dorado contra un proveedor y mide el resultado.

Cada caso corre por el orquestador real (la misma ruta que el chat), sobre la demo «Ventas»
generada con el `seed` y la fecha del set. La exactitud compara **resultados** (con la tolerancia
numérica del set), no texto SQL: el SQL esperado se ejecuta sobre la misma base y se compara con
las filas del evento `result` del turno.

Las conversaciones del orquestador se guardan en una base temporal; la base de la app no se toca.
"""

from __future__ import annotations

import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Literal

import yaml
from sqlalchemy.orm import Session

from app.agent.events import Event, TurnCompleted
from app.agent.orchestrator import Orchestrator
from app.db.models import Base, Conversation, Datasource
from app.db.session import make_engine
from app.engine.executor import QueryExecutor
from app.engine.guard import GuardCache
from app.eval.golden import Caso, Fila, SetDorado, _abrir_demo, _coinciden, _ejecutar
from app.llm.gateway import Gateway
from app.semantic.schema import SemanticModel, parse_semantic_model

Tipo = Literal["resultado", "aclaracion", "fuera_de_alcance"]

MODELO_VENTAS = Path(__file__).resolve().parents[3] / "examples" / "ventas" / "semantic-model.yaml"
# Errores que no demuestran que el agente supo rechazar: son fallos de infraestructura o internos.
_ERRORES_NO_CONTABLES = {"provider_error", "internal_error", "execution_error", "invalid_plan"}
_MUESTRA_FILAS = 5


@dataclass
class ResultadoCaso:
    id: str
    lang: str
    tags: list[str]
    tipo: Tipo
    correcto: bool
    motivo: str | None
    latencia_ms: float
    tokens_in: int
    tokens_out: int
    costo_usd: float
    sql: str | None = None
    sql_esperado: str | None = None
    filas: list[Fila] = field(default_factory=list)
    slot: str | None = None
    aclaracion_innecesaria: bool = False


def cargar_modelo(ruta: Path = MODELO_VENTAS) -> SemanticModel:
    return parse_semantic_model(yaml.safe_load(ruta.read_text("utf-8")))


def _ahora(dia: date) -> datetime:
    """«Hoy» de la evaluación: las 10:30 en Bogotá del día en que se congelaron los datos."""
    return datetime(dia.year, dia.month, dia.day, 15, 30, tzinfo=UTC)


def _tipo(caso: Caso) -> Tipo:
    if caso.expect_clarification is not None:
        return "aclaracion"
    if caso.expect_out_of_scope:
        return "fuera_de_alcance"
    return "resultado"


def _de_tipo(eventos: list[Event], tipo: str) -> list[dict[str, Any]]:
    return [e.payload() for e in eventos if e.type == tipo]


def _uso(eventos: list[Event]) -> tuple[int, int, float]:
    for e in eventos:
        if isinstance(e.data, TurnCompleted):
            u = e.data.usage
            return u.tokens_in, u.tokens_out, u.cost_usd
    return 0, 0, 0.0


class Evaluador:
    """Corre casos del set contra un orquestador ya armado."""

    def __init__(self, orchestrator: Orchestrator) -> None:
        self.orchestrator = orchestrator
        self.session = orchestrator.session

    def _turno(self, conversacion: Conversation, texto: str) -> list[Event]:
        return list(self.orchestrator.run(conversacion, texto))

    def evaluar_caso(self, caso: Caso, esperado: list[Fila] | None) -> ResultadoCaso:
        conversacion = Conversation(datasource_id=self.orchestrator.datasource.id)
        self.session.add(conversacion)
        self.session.commit()
        turnos: list[list[Event]] = []
        latencia = 0.0
        try:
            for previa in caso.previous:
                turnos.append(self._turno(conversacion, previa))
            inicio = time.perf_counter()
            actual = self._turno(conversacion, caso.question)
            turnos.append(actual)
            pendientes = list(caso.answers)
            while pendientes and _de_tipo(actual, "clarification"):
                actual = self._turno(conversacion, pendientes.pop(0))
                turnos.append(actual)
            latencia = (time.perf_counter() - inicio) * 1000
        except Exception as exc:  # el orquestador no debería lanzar; un caso roto no frena el set
            self.session.rollback()
            return self._resultado(caso, [], turnos, latencia, False, f"excepción: {exc}", None)
        correcto, motivo = self._juzgar(caso, actual, esperado)
        return self._resultado(caso, actual, turnos, latencia, correcto, motivo, esperado)

    def _juzgar(
        self, caso: Caso, eventos: list[Event], esperado: list[Fila] | None
    ) -> tuple[bool, str | None]:
        resultados = _de_tipo(eventos, "result")
        aclaraciones = _de_tipo(eventos, "clarification")
        errores = _de_tipo(eventos, "error")
        if caso.expect_clarification is not None:
            if resultados:
                return False, "ejecutó una consulta en vez de preguntar"
            if not aclaraciones:
                return False, "no hizo la aclaración esperada"
            slot = aclaraciones[0].get("slot")
            if slot != caso.expect_clarification.slot:
                return False, f"aclaró «{slot}» en vez de «{caso.expect_clarification.slot}»"
            return True, None
        if caso.expect_out_of_scope:
            if resultados:
                return False, "ejecutó una consulta que debía rechazar"
            if aclaraciones:
                return False, "preguntó en vez de rechazar"
            if errores and errores[0]["code"] in _ERRORES_NO_CONTABLES:
                return False, f"falló ({errores[0]['code']}): {errores[0]['message']}"
            return True, None
        assert caso.expect is not None and esperado is not None
        if errores:
            return False, f"error ({errores[0]['code']}): {errores[0]['message']}"
        if aclaraciones:
            return False, "preguntó de más en vez de responder"
        if not resultados:
            return False, "no devolvió resultado"
        if not _coinciden(resultados[-1]["rows"], esperado, caso.expect.ordered):
            return False, "el resultado no coincide con el esperado"
        return True, None

    def _resultado(
        self,
        caso: Caso,
        eventos: list[Event],
        turnos: list[list[Event]],
        latencia: float,
        correcto: bool,
        motivo: str | None,
        esperado: list[Fila] | None,
    ) -> ResultadoCaso:
        usos = [_uso(t) for t in turnos]
        sqls = _de_tipo(eventos, "sql")
        resultados = _de_tipo(eventos, "result")
        aclaraciones = _de_tipo(eventos, "clarification")
        return ResultadoCaso(
            id=caso.id,
            lang=caso.lang,
            tags=list(caso.tags),
            tipo=_tipo(caso),
            correcto=correcto,
            motivo=motivo,
            latencia_ms=latencia,
            tokens_in=sum(u[0] for u in usos),
            tokens_out=sum(u[1] for u in usos),
            costo_usd=sum(u[2] for u in usos),
            sql=sqls[-1]["sql"] if sqls else None,
            sql_esperado=caso.expect.sql if caso.expect else None,
            filas=resultados[-1]["rows"][:_MUESTRA_FILAS] if resultados else [],
            slot=aclaraciones[0].get("slot") if aclaraciones else None,
            aclaracion_innecesaria=(
                caso.expect_clarification is None and not caso.answers and bool(aclaraciones)
            ),
        )


def evaluar(
    conjunto: SetDorado,
    gateway: Gateway,
    model: SemanticModel,
    *,
    al_terminar_caso: Callable[[ResultadoCaso], None] | None = None,
) -> list[ResultadoCaso]:
    """Ejecuta todos los casos del set con `gateway` y devuelve un resultado por caso."""
    config = conjunto.config
    with tempfile.TemporaryDirectory() as tmp:
        carpeta = Path(tmp)
        conn = _abrir_demo(config, carpeta)
        try:
            esperados = {c.id: _ejecutar(conn, c.expect.sql)[1] for c in conjunto.casos if c.expect}
        finally:
            conn.close()
        engine = make_engine(f"sqlite:///{carpeta / 'eval.db'}")
        Base.metadata.create_all(engine)
        ejecutor = QueryExecutor()
        try:
            with Session(engine, expire_on_commit=False) as session:
                fuente = Datasource(
                    name=config.name,
                    dialect="sqlite",
                    url_encrypted=b"no-se-usa",
                    execute=True,
                    privacy="aggregates",
                )
                session.add(fuente)
                session.commit()
                orquestador = Orchestrator(
                    session,
                    gateway,
                    fuente,
                    model,
                    1,
                    f"sqlite:///{carpeta / 'ventas.db'}",
                    role=config.role,
                    query_executor=ejecutor,
                    guard_cache=GuardCache(),
                    now=_ahora(config.dataset.hasta),
                )
                evaluador = Evaluador(orquestador)
                resultados: list[ResultadoCaso] = []
                for caso in conjunto.casos:
                    resultado = evaluador.evaluar_caso(caso, esperados.get(caso.id))
                    resultados.append(resultado)
                    if al_terminar_caso is not None:
                        al_terminar_caso(resultado)
                return resultados
        finally:
            ejecutor.dispose()
            engine.dispose()
