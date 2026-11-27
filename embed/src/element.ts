import { createElement } from "react";
import { createRoot } from "react-dom/client";
import type { Root } from "react-dom/client";
import { EmbeddedChat } from "./EmbeddedChat";
import { parseLang } from "./i18n";
import styles from "./styles.css?inline";
import type { GetToken } from "./tokens";

export const TAG_NAME = "chatiapp-chat";

const ATTRIBUTES = [
  "base-url",
  "lang",
  "theme",
  "show-sql",
  "show-reasoning",
  "suggested-questions",
] as const;

/** `true` salvo que el atributo diga expresamente `false`. */
function flag(value: string | null): boolean {
  return value === null || value.trim().toLowerCase() !== "false";
}

/** Lista JSON (`["a","b"]`) o separada por `|`. */
function parseList(value: string | null): string[] | undefined {
  if (!value?.trim()) return undefined;
  try {
    const parsed: unknown = JSON.parse(value);
    if (Array.isArray(parsed)) return parsed.filter((item) => typeof item === "string");
  } catch {
    // no es JSON: se separa por |
  }
  return value
    .split("|")
    .map((item) => item.trim())
    .filter(Boolean);
}

/**
 * `<chatiapp-chat>`: el chat en un Shadow DOM. La página no le cambia los estilos ni el chat lee
 * nada de la página; solo le llegan los atributos, `getToken` y las variables `--chatiapp-*`.
 */
export class ChatiappChatElement extends HTMLElement {
  static observedAttributes = ATTRIBUTES;

  private root: Root | null = null;
  private readonly mount: HTMLDivElement;
  private tokenProvider: GetToken | undefined;
  private questions: string[] | undefined;

  constructor() {
    super();
    const shadow = this.attachShadow({ mode: "open" });
    const style = document.createElement("style");
    style.textContent = styles;
    this.mount = document.createElement("div");
    this.mount.style.height = "100%";
    shadow.append(style, this.mount);
  }

  /** Función del anfitrión que devuelve un token de sesión; se llama otra vez al expirar. */
  get getToken(): GetToken | undefined {
    return this.tokenProvider;
  }

  set getToken(value: GetToken | undefined) {
    this.tokenProvider = value;
  }

  /** Preguntas iniciales propias; tiene prioridad sobre el atributo `suggested-questions`. */
  get suggestedQuestions(): string[] | undefined {
    return this.questions ?? parseList(this.getAttribute("suggested-questions"));
  }

  set suggestedQuestions(value: string[] | undefined) {
    this.questions = value;
    this.render();
  }

  connectedCallback(): void {
    // Propiedades asignadas antes de que el elemento se definiera (carga con `defer`).
    const self = this as unknown as Record<string, unknown>;
    for (const name of ["getToken", "suggestedQuestions"]) {
      if (Object.prototype.hasOwnProperty.call(self, name)) {
        const value = self[name];
        delete self[name];
        self[name] = value;
      }
    }
    this.root ??= createRoot(this.mount);
    this.render();
  }

  disconnectedCallback(): void {
    this.root?.unmount();
    this.root = null;
  }

  attributeChangedCallback(): void {
    this.render();
  }

  private emit<T>(name: string, detail: T): void {
    this.dispatchEvent(new CustomEvent(name, { detail, bubbles: true, composed: true }));
  }

  private render(): void {
    if (!this.root) return;
    this.root.render(
      createElement(EmbeddedChat, {
        baseUrl: this.getAttribute("base-url") ?? "",
        // Un solo getToken estable: el valor vigente se lee al pedir el token.
        getToken: () => {
          if (!this.tokenProvider) throw new Error("getToken no está definido");
          return this.tokenProvider();
        },
        lang: parseLang(this.getAttribute("lang")),
        showSql: flag(this.getAttribute("show-sql")),
        showReasoning: flag(this.getAttribute("show-reasoning")),
        suggestedQuestions: this.suggestedQuestions,
        onAnswer: (detail) => this.emit("chatiapp:answer", detail),
        onClarification: (detail) => this.emit("chatiapp:clarification", detail),
        onError: (detail) => this.emit("chatiapp:error", detail),
      }),
    );
  }
}

/** Registra `<chatiapp-chat>` una sola vez (cargar el script dos veces no falla). */
export function defineChatiappChat(): void {
  if (!customElements.get(TAG_NAME)) customElements.define(TAG_NAME, ChatiappChatElement);
}
