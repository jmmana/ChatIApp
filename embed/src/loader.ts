// `chatiapp.js`: cargador mínimo que se incluye con un <script defer> clásico. Trae el widget
// (un módulo ES con partes que se descargan solo si hacen falta: gráficos y formato de SQL) desde
// la misma carpeta, es decir, desde la instancia de ChatIApp y no desde la página anfitriona.
const FILE = "chatiapp-widget.js";

const current = document.currentScript;
const own =
  current instanceof HTMLScriptElement && current.src
    ? current.src
    : (document.querySelector<HTMLScriptElement>('script[src*="chatiapp.js"]')?.src ?? "");

if (own) {
  import(/* @vite-ignore */ new URL(FILE, own).href).catch((error: unknown) => {
    console.error("ChatIApp: no se pudo cargar el widget", error);
  });
} else {
  console.error("ChatIApp: no se encontró la URL de chatiapp.js");
}
