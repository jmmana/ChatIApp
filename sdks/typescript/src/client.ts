import { errorFromResponse } from "./errors.js";
import { parseSse } from "./events.js";
import type {
  ClarificationData,
  ErrorData,
  PeriodData,
  ResultData,
  SqlData,
  StreamEvent,
  UsageData,
} from "./events.js";
import type { CancelOut, EmbedSessionOut, EndUser } from "./generated/types.js";

const API_PREFIX = "/api/v1";

export interface ChatIAppOptions {
  baseUrl: string;
  /** Credencial de servidor: nunca la uses en un navegador ni en una app móvil. */
  apiKey: string;
  /** Fuente de datos por defecto. */
  datasource?: string;
  /** Para pruebas o entornos sin `fetch` global. */
  fetch?: typeof fetch;
}

export interface ChatParams {
  message: string;
  datasource?: string;
  user: EndUser;
  conversationId?: string;
  signal?: AbortSignal;
}

export type TurnStatus = "answered" | "needs_clarification" | "rejected" | "error";

/** Respuesta de `POST /api/v1/chat`. Si `status` es `needs_clarification`, responde en la misma conversación. */
export interface Turn {
  conversation_id: string;
  status: TurnStatus;
  reasoning?: string;
  clarification?: ClarificationData;
  period?: PeriodData | null;
  sql?: Omit<SqlData, "period">;
  result?: ResultData;
  answer?: string;
  usage?: UsageData;
  error?: ErrorData;
}

export interface EmbedSessionParams {
  datasource?: string;
  origin: string;
  user: EndUser;
  ttlSeconds?: number;
}

export class ChatIApp {
  private readonly baseUrl: string;
  private readonly apiKey: string;
  private readonly datasource: string | undefined;
  private readonly fetchImpl: typeof fetch;
  // Las respuestas siguientes de una conversación no repiten la fuente.
  private readonly conversations = new Map<string, string>();

  constructor(options: ChatIAppOptions) {
    this.baseUrl = options.baseUrl.replace(/\/+$/, "");
    this.apiKey = options.apiKey;
    this.datasource = options.datasource;
    this.fetchImpl = options.fetch ?? ((input, init) => fetch(input, init));
  }

  /** Un turno sin streaming. Si falta un dato, `status` es `needs_clarification`. */
  async chat(params: ChatParams): Promise<Turn> {
    const body = this.chatBody(params);
    const response = await this.post("/chat", body, params.signal);
    const turn = (await response.json()) as Turn;
    this.conversations.set(turn.conversation_id, body.datasource_id);
    return turn;
  }

  /** Un turno por SSE: emite los eventos tipados a medida que llegan. */
  async *chatStream(params: ChatParams): AsyncGenerator<StreamEvent> {
    const body = this.chatBody(params);
    const response = await this.post("/chat/stream", body, params.signal, {
      Accept: "text/event-stream",
    });
    if (!response.body) return;
    for await (const event of parseSse(response.body)) {
      if (event.type === "turn.started") {
        this.conversations.set(event.data.conversation_id, body.datasource_id);
      }
      yield event;
    }
  }

  /** Cancela un turno en curso (el de `turn.started`). */
  async cancel(turnId: string): Promise<CancelOut> {
    const response = await this.post(`/chat/${encodeURIComponent(turnId)}/cancel`);
    return (await response.json()) as CancelOut;
  }

  /**
   * Cambia la API key por un token de sesión de corta vida para el widget del navegador.
   * Llámalo desde tu backend y devuelve solo `token` al frontend.
   */
  async createEmbedSession(params: EmbedSessionParams): Promise<EmbedSessionOut> {
    const body: Record<string, unknown> = {
      datasource: this.resolveDatasource(params.datasource),
      origin: params.origin,
      user: params.user,
    };
    if (params.ttlSeconds !== undefined) body.ttl_seconds = params.ttlSeconds;
    const response = await this.post("/embed/sessions", body);
    return (await response.json()) as EmbedSessionOut;
  }

  private resolveDatasource(datasource?: string, conversationId?: string): string {
    const resolved =
      datasource ??
      (conversationId ? this.conversations.get(conversationId) : undefined) ??
      this.datasource;
    if (!resolved) throw new Error("Indica `datasource` (o configúralo en el constructor).");
    return resolved;
  }

  private chatBody(params: ChatParams): {
    datasource_id: string;
    message: string;
    user: EndUser;
    conversation_id?: string;
  } {
    return {
      datasource_id: this.resolveDatasource(params.datasource, params.conversationId),
      message: params.message,
      user: params.user,
      ...(params.conversationId ? { conversation_id: params.conversationId } : {}),
    };
  }

  private async post(
    path: string,
    body?: unknown,
    signal?: AbortSignal,
    headers: Record<string, string> = {},
  ): Promise<Response> {
    const response = await this.fetchImpl(`${this.baseUrl}${API_PREFIX}${path}`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${this.apiKey}`,
        ...(body === undefined ? {} : { "Content-Type": "application/json" }),
        ...headers,
      },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
    });
    if (!response.ok) throw await errorFromResponse(response);
    return response;
  }
}
