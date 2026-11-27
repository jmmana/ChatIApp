import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { Clarification } from "../Clarification";
import { Reasoning, summarizeSteps } from "../Reasoning";
import { initialTurnState, turnReducer, type TurnAction } from "../turnReducer";

// Secuencias grabadas de un turno real (docs/FLUJO_CONVERSACIONAL.md).
const started: TurnAction = {
  type: "turn.started",
  data: { turn_id: "t1", conversation_id: "c1" },
};
const midTurn: TurnAction[] = [
  started,
  { type: "step", data: { id: "understand", label: "Entendiendo la pregunta", status: "running" } },
  { type: "reasoning", data: { text: "Métrica: ventas_netas, período: este mes" } },
  { type: "step", data: { id: "understand", label: "Entendiendo la pregunta", status: "done" } },
  {
    type: "step",
    data: { id: "period", label: "Resolviendo el período", status: "warning", detail: "sin año" },
  },
  { type: "step", data: { id: "run", label: "Consultando", status: "error" } },
];
const finished: TurnAction[] = [
  ...midTurn,
  { type: "answer", data: { text: "Vendiste 10." } },
  {
    type: "turn.completed",
    data: { usage: { tokens_in: 1, tokens_out: 1, cost_usd: 0 }, elapsed_ms: 5 },
  },
];
const play = (events: TurnAction[]) => events.reduce(turnReducer, initialTurnState);

describe("Reasoning", () => {
  it("muestra los pasos con su estado y el texto de reasoning mientras el turno sigue", () => {
    const s = play(midTurn);
    render(<Reasoning steps={s.steps} reasoning={s.reasoning} streaming />);
    expect(screen.getByText("Entendiendo la pregunta")).toBeInTheDocument();
    expect(screen.getByText("(Listo)")).toBeInTheDocument();
    expect(screen.getByText("(Advertencia)")).toBeInTheDocument();
    expect(screen.getByText("(Error)")).toBeInTheDocument();
    expect(screen.getByText(/sin año/)).toBeInTheDocument();
    expect(screen.getByText("Métrica: ventas_netas, período: este mes")).toBeInTheDocument();
    expect(screen.getByRole("button", { expanded: true })).toBeInTheDocument();
  });

  it("anuncia los cambios con aria-live polite", () => {
    const s = play(midTurn);
    const { container } = render(<Reasoning steps={s.steps} reasoning={null} streaming />);
    expect(container.querySelector('[aria-live="polite"]')).toContainElement(
      screen.getByText("Consultando"),
    );
  });

  it("se pliega al terminar con un resumen de una línea y se puede reabrir", async () => {
    const s = play(finished);
    render(<Reasoning steps={s.steps} reasoning={s.reasoning} streaming={false} />);
    expect(screen.getByRole("button", { name: /Razonamiento: 3 pasos · 1 advertencia · 1 error/ }))
      .toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("Resolviendo el período")).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button"));
    expect(screen.getByText("Resolviendo el período")).toBeInTheDocument();
  });

  it("no pinta nada sin pasos ni razonamiento", () => {
    const { container } = render(<Reasoning steps={[]} reasoning={null} streaming />);
    expect(container).toBeEmptyDOMElement();
  });

  it("resume en singular", () => {
    expect(summarizeSteps([{ id: "a", label: "x", status: "done" }])).toBe("1 paso");
  });
});

describe("Clarification", () => {
  const clarification = play([
    started,
    {
      type: "clarification",
      data: { question: "¿Qué período?", options: ["Hoy", "Este mes", "Este año"], slot: "period" },
    },
  ]).clarification!;

  it("las flechas mueven el foco entre opciones y dan la vuelta", async () => {
    render(<Clarification {...clarification} onSelect={() => {}} />);
    const [hoy, mes, anio] = screen.getAllByRole("button");
    await userEvent.tab();
    expect(hoy).toHaveFocus();
    await userEvent.keyboard("{ArrowRight}");
    expect(mes).toHaveFocus();
    await userEvent.keyboard("{ArrowDown}");
    expect(anio).toHaveFocus();
    await userEvent.keyboard("{ArrowRight}");
    expect(hoy).toHaveFocus();
    await userEvent.keyboard("{ArrowLeft}");
    expect(anio).toHaveFocus();
    await userEvent.keyboard("{Home}");
    expect(hoy).toHaveFocus();
    await userEvent.keyboard("{End}");
    expect(anio).toHaveFocus();
  });

  it("elegir una opción con clic o Enter envía la respuesta", async () => {
    const onSelect = vi.fn();
    render(<Clarification {...clarification} onSelect={onSelect} />);
    await userEvent.click(screen.getByRole("button", { name: "Hoy" }));
    // Tras el clic el foco está en «Hoy»; la flecha pasa a la siguiente.
    await userEvent.keyboard("{ArrowRight}{Enter}");
    expect(onSelect.mock.calls).toEqual([["Hoy"], ["Este mes"]]);
  });
});
