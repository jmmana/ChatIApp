// Los ejemplos de docs/INTEGRACION.md contra una instancia real con la demo.
// Se omite si no hay instancia: levanta ChatIApp con la demo y el proveedor simulado, crea una
// API key con alcance `chat` para la fuente `ventas` y exporta CHATIAPP_DEMO_URL y
// CHATIAPP_DEMO_API_KEY (y CHATIAPP_DEMO_ROLE si la key permite varios roles).
import { describe, expect, it } from "vitest";
import { ChatIApp } from "../src/index.js";

const url = process.env.CHATIAPP_DEMO_URL;
const apiKey = process.env.CHATIAPP_DEMO_API_KEY;
const user = { id: "u-123", role: process.env.CHATIAPP_DEMO_ROLE };

describe.skipIf(!url || !apiKey)("contra la demo", () => {
  it("chat con aclaración", async () => {
    const client = new ChatIApp({ baseUrl: url!, apiKey: apiKey! });
    let turn = await client.chat({ message: "¿Cuánto vendí?", datasource: "ventas", user });
    if (turn.status === "needs_clarification") {
      turn = await client.chat({ message: "Este mes", conversationId: turn.conversation_id, user });
    }
    expect(["answered", "rejected"]).toContain(turn.status);
  });

  it("streaming", async () => {
    const client = new ChatIApp({ baseUrl: url!, apiKey: apiKey! });
    const types: string[] = [];
    for await (const event of client.chatStream({
      datasource: "ventas",
      message: "¿Cuánto vendí este mes?",
      user,
    })) {
      types.push(event.type);
    }
    expect(types.at(-1) === "turn.completed" || types.includes("error")).toBe(true);
  });
});
