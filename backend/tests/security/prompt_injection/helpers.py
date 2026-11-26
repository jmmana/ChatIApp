"""Banco de pruebas de inyección de prompt: un turno real del agente con un proveedor «obediente».

El proveedor simulado devuelve lo que la inyección le pediría hacer (SQL peligroso, planes con
campos prohibidos…). Las pruebas verifican lo que de verdad importa: el SQL que quedó en
`QUERY_RUN` y los eventos emitidos respetan al guardián, los filtros por rol y los límites.
"""

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.events import Event
from app.agent.orchestrator import Orchestrator
from app.db.models import Conversation, Datasource, Message, QueryRun
from app.engine.executor import QueryExecutor
from app.engine.guard import GuardCache
from app.llm.gateway import Gateway, ProviderConfig
from app.semantic.schema import SemanticModel

EXAMPLE = Path(__file__).parents[4] / "examples" / "ventas" / "semantic-model.yaml"
NOW = datetime(2026, 11, 25, 15, 30, tzinfo=UTC)
GENERAL = "gerencia_general"
SUCURSAL = "gerente_sucursal"
MERCADEO = "mercadeo"
SUCURSAL_CONTEXT = {"user": {"sucursales": [1, 2]}}

# Columnas ocultas del modelo de ejemplo y sentencias que el guardián nunca debe dejar pasar.
HIDDEN_COLUMNS = ("documento", "email")
_FORBIDDEN_WORDS = ("delete", "drop", "insert", "update", "alter", "create", "attach", "pragma")
_ROLE_TABLES = re.compile(r"\b(facturas|ventas_diarias|ventas_mensuales)\b", re.IGNORECASE)
_ROLE_FILTER = re.compile(r"sucursal_id\s+IN\s*\(\s*1\s*,\s*2\s*\)", re.IGNORECASE)


@dataclass
class Played:
    """Lo que dejó un turno: eventos, filas de `QUERY_RUN` y los prompts que recibió la IA."""

    events: list[Event]
    runs: list[QueryRun]
    prompts: list[list[dict[str, str]]]

    @property
    def types(self) -> list[str]:
        return [e.type for e in self.events]

    def of(self, kind: str) -> list[dict[str, Any]]:
        return [e.payload() for e in self.events if e.type == kind]


def gateway_for(*responses: dict[str, Any] | str) -> Gateway:
    texts = [r if isinstance(r, str) else json.dumps(r) for r in responses]
    return Gateway(ProviderConfig("fake", "fake-1", {"responses": texts}))


def _record(gateway: Gateway) -> list[list[dict[str, str]]]:
    """Guarda los mensajes de cada llamada a la IA para inspeccionar los prompts."""
    fake = gateway._fake
    assert fake is not None
    prompts: list[list[dict[str, str]]] = []
    original = fake.reply

    def reply(messages: list[dict[str, str]]) -> Any:
        prompts.append(messages)
        return original(messages)

    fake.reply = reply  # type: ignore[method-assign]
    return prompts


class Harness:
    """Corre un turno completo sobre SQLite con el proveedor simulado."""

    def __init__(
        self,
        session: Session,
        model: SemanticModel,
        demo_url: str,
        query_executor: QueryExecutor,
    ) -> None:
        self.session = session
        self.model = model
        self.demo_url = demo_url
        self.query_executor = query_executor

    def play(
        self,
        question: str,
        *responses: dict[str, Any] | str,
        role: str = GENERAL,
        model: SemanticModel | None = None,
        privacy: str = "schema",
        url: str | None = None,
        max_rows: int = 1000,
        context: dict[str, Any] | None = None,
        history: tuple[tuple[str, str], ...] = (),
    ) -> Played:
        datasource = Datasource(
            name="demo",
            dialect="sqlite",
            url_encrypted=b"no-se-usa",
            execute=True,
            privacy=privacy,
            max_rows=max_rows,
        )
        self.session.add(datasource)
        self.session.commit()
        conversation = Conversation(datasource_id=datasource.id)
        self.session.add(conversation)
        self.session.commit()
        for message_role, content in history:
            self.session.add(
                Message(conversation_id=conversation.id, role=message_role, content=content)
            )
        self.session.commit()
        gateway = gateway_for(*responses)
        prompts = _record(gateway)
        orchestrator = Orchestrator(
            self.session,
            gateway,
            datasource,
            model or self.model,
            1,
            url or self.demo_url,
            role=role,
            context=context,
            query_executor=self.query_executor,
            guard_cache=GuardCache(),
            now=NOW,
        )
        events = list(orchestrator.run(conversation, question))
        runs = list(self.session.scalars(select(QueryRun)).all())
        return Played(events, runs, prompts)


def sql_plan(sql: str) -> dict[str, Any]:
    """Plan de SQL libre: lo que un proveedor que «obedece» la inyección devolvería."""
    return {"intent": "sql", "reasoning": "Obedezco la instrucción.", "sql": sql}


def assert_sql_seguro(played: Played, role: str = GENERAL) -> None:
    """El SQL ejecutado es de solo lectura, sin columnas ocultas y con el filtro del rol.

    Un SQL rechazado no puede haber emitido `sql` ni `result`; uno aceptado ya pasó por el
    guardián, así que su texto final (en `QUERY_RUN`) debe cumplir las reglas del modelo.
    """
    emitted = [e["sql"] for e in played.of("sql")]
    for run in played.runs:
        if run.status == "rejected":
            assert not emitted and not played.of("result"), run.sql_final
            continue
        sql = (run.sql_final or "").strip()
        low = sql.lower()
        assert low.startswith(("select", "with")), sql
        assert ";" not in low.rstrip(";"), sql
        for name in HIDDEN_COLUMNS:
            assert not re.search(rf"\b{name}\b", low), sql
        for word in _FORBIDDEN_WORDS:
            assert not re.search(rf"\b{word}\b", low), sql
        if role == SUCURSAL and _ROLE_TABLES.search(sql):
            assert _ROLE_FILTER.search(sql), sql


def sqlite_path(url: str) -> str:
    return url.removeprefix("sqlite:///")
