import { describe, expect, it } from "vitest";
import { initialTurnState, turnReducer, type TurnAction, type TurnState } from "../turnReducer";

const run = (events: TurnAction[], from: TurnState = initialTurnState) =>
  events.reduce(turnReducer, from);

const started: TurnAction = {
  type: "turn.started",
  data: { turn_id: "t1", conversation_id: "c1" },
};
const completed: TurnAction = {
  type: "turn.completed",
  data: { usage: { tokens_in: 10, tokens_out: 5, cost_usd: 0.001 }, elapsed_ms: 900 },
};

describe("turnReducer por evento", () => {
  it("turn.started guarda los ids y pasa a streaming", () => {
    const s = run([started]);
    expect(s).toMatchObject({ status: "streaming", turnId: "t1", conversationId: "c1" });
  });

  it("step agrega y luego actualiza por id", () => {
    const s = run([
      started,
      { type: "step", data: { id: "a", label: "Entendiendo", status: "running" } },
      { type: "step", data: { id: "b", label: "Período", status: "running" } },
      { type: "step", data: { id: "a", label: "Entendiendo", status: "done", detail: "ok" } },
    ]);
    expect(s.steps).toEqual([
      { id: "a", label: "Entendiendo", status: "done", detail: "ok" },
      { id: "b", label: "Período", status: "running" },
    ]);
  });

  it("reasoning, sql y result se guardan", () => {
    const sql = {
      sql: "SELECT 1",
      dialect: "sqlite",
      origin: "catalog" as const,
      filters_applied: [],
    };
    const result = { columns: ["x"], rows: [[1]], row_count: 1, truncated: false, elapsed_ms: 3 };
    const s = run([
      started,
      { type: "reasoning", data: { text: "plan" } },
      { type: "sql", data: sql },
      { type: "result", data: result },
    ]);
    expect(s.reasoning).toBe("plan");
    expect(s.sql).toEqual(sql);
    expect(s.result).toEqual(result);
  });

  it("clarification pasa a clarifying", () => {
    const data = { question: "¿Período?", options: ["Hoy"], slot: "period" };
    const s = run([started, { type: "clarification", data }]);
    expect(s.status).toBe("clarifying");
    expect(s.clarification).toEqual(data);
  });

  it("answer.delta acumula y answer lo reemplaza de forma definitiva", () => {
    let s = run([
      started,
      { type: "answer.delta", data: { text: "Este " } },
      { type: "answer.delta", data: { text: "mes" } },
    ]);
    expect(s.answer).toBe("Este mes");
    s = run(
      [
        { type: "answer", data: { text: "Este mes vendiste 5." } },
        { type: "answer.delta", data: { text: " tardío" } },
      ],
      s,
    );
    expect(s.answer).toBe("Este mes vendiste 5.");
    expect(s.answerFinal).toBe(true);
  });

  it("error conserva recoverable", () => {
    const s = run([
      started,
      { type: "error", data: { code: "cancelled", message: "Cancelado", recoverable: true } },
    ]);
    expect(s.status).toBe("error");
    expect(s.error?.recoverable).toBe(true);
  });

  it("turn.completed cierra el turno con el uso", () => {
    const s = run([started, completed]);
    expect(s.status).toBe("completed");
    expect(s.completed?.usage.tokens_in).toBe(10);
  });

  it("un nuevo turn.started descarta el estado anterior", () => {
    const s = run([
      started,
      { type: "reasoning", data: { text: "viejo" } },
      { type: "turn.started", data: { turn_id: "t2", conversation_id: "c1" } },
    ]);
    expect(s.reasoning).toBeNull();
    expect(s.turnId).toBe("t2");
  });

  it("no muta el estado anterior", () => {
    const before = run([started]);
    const snapshot = structuredClone(before);
    turnReducer(before, { type: "step", data: { id: "a", label: "x", status: "running" } });
    expect(before).toEqual(snapshot);
  });
});

describe("turnReducer por secuencias", () => {
  it("turno completo con SQL, resultado y respuesta", () => {
    const s = run([
      started,
      { type: "step", data: { id: "understand", label: "Entendiendo", status: "running" } },
      { type: "reasoning", data: { text: "ventas_netas" } },
      { type: "step", data: { id: "understand", label: "Entendiendo", status: "done" } },
      {
        type: "sql",
        data: { sql: "SELECT 1", dialect: "sqlite", origin: "llm", filters_applied: ["a"] },
      },
      {
        type: "result",
        data: { columns: ["v"], rows: [[1]], row_count: 1, truncated: false, elapsed_ms: 2 },
      },
      { type: "answer.delta", data: { text: "Hola" } },
      { type: "answer", data: { text: "Hola mundo" } },
      completed,
    ]);
    expect(s.status).toBe("completed");
    expect(s.steps).toHaveLength(1);
    expect(s.answer).toBe("Hola mundo");
    expect(s.error).toBeNull();
  });

  it("aclaración: el turno termina esperando respuesta del usuario", () => {
    const s = run([
      started,
      { type: "clarification", data: { question: "¿?", options: [], slot: "period" } },
      completed,
    ]);
    expect(s.status).toBe("clarifying");
    expect(s.completed).not.toBeNull();
  });

  it("cancelación: error recuperable y sin turn.completed", () => {
    const s = run([
      started,
      { type: "answer.delta", data: { text: "par" } },
      { type: "error", data: { code: "cancelled", message: "x", recoverable: true } },
    ]);
    expect(s.status).toBe("error");
    expect(s.completed).toBeNull();
    expect(s.answer).toBe("par");
  });

  it("error de red recuperable y reintento limpia el estado", () => {
    let s = run([started, { type: "client.network_error", message: "Failed to fetch" }]);
    expect(s.status).toBe("error");
    expect(s.error).toEqual({
      code: "network_error",
      message: "Failed to fetch",
      recoverable: true,
    });
    s = run([{ type: "client.start" }], s);
    expect(s).toEqual({ ...initialTurnState, status: "streaming" });
  });

  it("client.reset vuelve al estado inicial", () => {
    expect(run([started, { type: "client.reset" }])).toEqual(initialTurnState);
  });
});
