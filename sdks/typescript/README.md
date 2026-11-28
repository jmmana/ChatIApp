# @chatiapp/client

Cliente oficial de [ChatIApp](https://github.com/jmmana/ChatIApp) para tu backend (Node 18+): chat, streaming SSE tipado y tokens de sesión para el chat embebido.

```bash
npm install @chatiapp/client
```

```ts
import { ChatIApp } from "@chatiapp/client";

const client = new ChatIApp({ baseUrl: "https://chatiapp.tuempresa.com", apiKey: process.env.CHATIAPP_API_KEY! });
const user = { id: "u-123", role: "gerente_sucursal", attributes: { sucursales: [1, 2] } };

let turn = await client.chat({ datasource: "ventas", message: "¿Cuánto vendí?", user });
if (turn.status === "needs_clarification") {
  turn = await client.chat({ message: "Este mes", conversationId: turn.conversation_id, user });
}
```

Token de sesión para el widget (desde tu backend, nunca desde el navegador):

```ts
const { token } = await client.createEmbedSession({
  datasource: "ventas",
  origin: "https://portal.tuempresa.com",
  user,
});
```

- Los errores HTTP lanzan `ChatIAppError` (`status`, `code`, `message`).
- Una respuesta de aclaración recuerda la fuente: el segundo `chat()` no necesita `datasource`.
- `src/generated/types.ts` se genera desde `docs/openapi/v1.json` (`node sdks/scripts/generate.mjs`); no lo edites.

Desarrollo: `pnpm install`, `pnpm run lint`, `pnpm run test`, `pnpm run build`.

## Streaming

`chatStream` solo funciona con una sesión o un token de sesión del chat embebido, **no con una API key** (el servidor responde 401): desde tu servidor usa `chat()`. Con un token de sesión, pásalo como `apiKey`:

```ts
const browserClient = new ChatIApp({ baseUrl: "https://chatiapp.tuempresa.com", apiKey: sessionToken });
for await (const event of browserClient.chatStream({ datasource: "ventas", message: "¿Cuánto vendí este mes?", user })) {
  if (event.type === "answer.delta") process.stdout.write(event.data.text);
}
```
