// Dos orígenes distintos para la prueba E2E:
//   · ChatIApp simulado (puerto 4101): sirve /embed/v1/* desde dist/ y un /api/v1/chat/stream falso.
//   · Página anfitriona (puerto 4102): otra app con sus propios estilos que embebe el widget.
import { createReadStream, existsSync } from "node:fs";
import { createServer } from "node:http";
import { extname, join, normalize } from "node:path";
import { fileURLToPath } from "node:url";

const dist = fileURLToPath(new URL("../dist/", import.meta.url));
export const CHATIAPP = "http://localhost:4101";
export const HOST = "http://localhost:4102";
const DATASOURCE = "11111111-1111-4111-8111-111111111111";

const b64 = (value) => Buffer.from(JSON.stringify(value)).toString("base64url");
const token = (n) =>
  `${b64({ alg: "HS256" })}.${b64({ ds: DATASOURCE, exp: 4_102_444_800, n })}.firma`;

/** Lo que el ChatIApp simulado vio: la prueba lo consulta en /__requests. */
const requests = [];
let tokensIssued = 0;

const sse = (events) =>
  events.map(([type, data]) => `event: ${type}\ndata: ${JSON.stringify(data)}\n\n`).join("");

const turn = (text) =>
  sse([
    ["turn.started", { turn_id: "t1", conversation_id: "c1" }],
    ["answer", { text }],
    ["turn.completed", { usage: { tokens_in: 1, tokens_out: 1, cost_usd: 0 }, elapsed_ms: 5 }],
  ]);

const MIME = { ".js": "text/javascript", ".css": "text/css" };

const chatiapp = createServer((req, res) => {
  const url = new URL(req.url ?? "/", CHATIAPP);
  const origin = req.headers.origin;
  if (origin) res.setHeader("Access-Control-Allow-Origin", origin === HOST ? origin : "null");
  res.setHeader("Access-Control-Allow-Headers", "Authorization, Content-Type");
  res.setHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
  if (req.method === "OPTIONS") return void res.writeHead(204).end();

  if (url.pathname === "/__requests") {
    res.setHeader("Content-Type", "application/json");
    return void res.end(JSON.stringify(requests));
  }
  if (url.pathname.startsWith("/embed/v1/")) {
    res.setHeader("Access-Control-Allow-Origin", "*");
    const file = normalize(join(dist, url.pathname.slice("/embed/v1/".length)));
    if (!file.startsWith(dist) || !existsSync(file)) return void res.writeHead(404).end();
    res.writeHead(200, { "Content-Type": MIME[extname(file)] ?? "application/octet-stream" });
    return void createReadStream(file).pipe(res);
  }
  if (url.pathname === "/api/v1/chat/stream" && req.method === "POST") {
    let body = "";
    req.on("data", (chunk) => (body += chunk));
    req.on("end", () => {
      requests.push({
        origin,
        authorization: req.headers.authorization,
        body: JSON.parse(body),
      });
      res.writeHead(200, { "Content-Type": "text/event-stream" });
      res.end(turn("Vendiste 10."));
    });
    return;
  }
  res.writeHead(404).end();
});

const PAGE = `<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <title>Tienda de ejemplo</title>
  <style>
    body { font-family: Georgia, serif; color: rgb(10, 20, 30); background: rgb(250, 245, 235); }
    h1 { font-size: 40px; color: rgb(0, 128, 0); }
    p, button, textarea, h2, ul, li, section, div { color: rgb(255, 0, 0) !important; }
    textarea { background: rgb(255, 255, 0) !important; border: 5px solid rgb(0, 0, 255) !important; }
    chatiapp-chat { height: 520px; --chatiapp-accent: rgb(200, 30, 90); --chatiapp-radius: 2px; }
  </style>
</head>
<body>
  <h1 id="titulo">Mi tienda</h1>
  <p id="parrafo">Texto de la página anfitriona.</p>
  <textarea id="fuera"></textarea>
  <chatiapp-chat base-url="${CHATIAPP}" lang="es" theme="light" show-sql="false"></chatiapp-chat>
  <script src="${CHATIAPP}/embed/v1/chatiapp.js" defer></script>
  <script>
    window.__events = [];
    const chat = document.querySelector("chatiapp-chat");
    chat.getToken = async () => {
      const r = await fetch("/chatiapp-token", { method: "POST", credentials: "include" });
      return (await r.json()).token;
    };
    for (const name of ["answer", "clarification", "error"]) {
      chat.addEventListener("chatiapp:" + name, (e) =>
        window.__events.push({ name, detail: e.detail }));
    }
  </script>
</body>
</html>`;

const host = createServer((req, res) => {
  if (req.url === "/chatiapp-token" && req.method === "POST") {
    res.setHeader("Content-Type", "application/json");
    return void res.end(JSON.stringify({ token: token(++tokensIssued) }));
  }
  res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" }).end(PAGE);
});

chatiapp.listen(4101, "127.0.0.1");
host.listen(4102, "127.0.0.1");
console.log(`ChatIApp simulado en ${CHATIAPP}, página anfitriona en ${HOST}`);
