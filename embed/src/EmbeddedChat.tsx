import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { UIEvent } from "react";
import { Button } from "@/components/ui/button";
import { Composer } from "@/features/chat/Composer";
import { Exchange } from "@/features/chat/Exchange";
import type { ResultFormat } from "@/features/chat/Exchange";
import type { TurnState } from "@/features/chat/turnReducer";
import { useTurn } from "@/features/chat/useTurn";
import { MESSAGES } from "./i18n";
import type { Lang } from "./i18n";
import { createTokenSource, TokenError } from "./tokens";
import type { GetToken } from "./tokens";

/** Distancia (px) al final desde la que se considera que la persona sigue «abajo». */
const STICK_THRESHOLD = 48;

export interface AnswerDetail {
  text: string;
  conversationId: string | null;
  sql: string | null;
  columns: string[];
  rows: unknown[][];
}

export interface ClarificationDetail {
  question: string;
  options: string[];
  conversationId: string | null;
}

export interface ErrorDetail {
  code: string;
  message: string;
  recoverable: boolean;
}

export interface EmbeddedChatProps {
  baseUrl: string;
  getToken?: GetToken;
  lang?: Lang;
  showSql?: boolean;
  showReasoning?: boolean;
  suggestedQuestions?: string[];
  onAnswer?: (detail: AnswerDetail) => void;
  onClarification?: (detail: ClarificationDetail) => void;
  onError?: (detail: ErrorDetail) => void;
}

interface Message {
  question: string;
  turn: TurnState;
}

const NO_FORMAT: Omit<ResultFormat, "locale"> = { metricLabels: {} };

/** El chat completo del widget: los mismos componentes de la interfaz, con el token del anfitrión. */
export function EmbeddedChat({
  baseUrl,
  getToken,
  lang = "es",
  showSql = true,
  showReasoning = true,
  suggestedQuestions,
  onAnswer,
  onClarification,
  onError,
}: EmbeddedChatProps) {
  const text = MESSAGES[lang];
  // El token vive en una ref: cambiar `getToken` no pierde el token ni la conversación.
  const getTokenRef = useRef(getToken);
  useEffect(() => {
    getTokenRef.current = getToken;
  });
  const tokens = useMemo(() => createTokenSource(() => getTokenRef.current), []);
  const authorize = useCallback((force: boolean) => tokens.get(force), [tokens]);

  const { state, send, cancel } = useTurn({ baseUrl: baseUrl.replace(/\/+$/, ""), authorize });
  const [history, setHistory] = useState<Message[]>([]);
  const [question, setQuestion] = useState<string | null>(null);
  const [localError, setLocalError] = useState<ErrorDetail | null>(null);

  // Los callbacks se leen en el momento del evento sin reiniciar el efecto.
  const handlers = useRef({ onAnswer, onClarification, onError });
  useEffect(() => {
    handlers.current = { onAnswer, onClarification, onError };
  });

  // Un evento DOM por turno, cuando el turno llega a un estado final.
  const notified = useRef<string | null>(null);
  useEffect(() => {
    const key = `${state.turnId}:${state.status}`;
    if (state.status === "streaming") notified.current = null;
    if (state.status === "idle" || state.status === "streaming" || notified.current === key) {
      return;
    }
    notified.current = key;
    if (state.status === "completed") {
      handlers.current.onAnswer?.({
        text: state.answer,
        conversationId: state.conversationId,
        sql: state.sql?.sql ?? null,
        columns: state.result?.columns ?? [],
        rows: state.result?.rows ?? [],
      });
    } else if (state.status === "clarifying" && state.clarification) {
      handlers.current.onClarification?.({
        question: state.clarification.question,
        options: state.clarification.options,
        conversationId: state.conversationId,
      });
    } else if (state.status === "error" && state.error) {
      handlers.current.onError?.(state.error);
    }
  }, [state]);

  const busy = state.status === "streaming";

  // Detiene el turno en el servidor (con el token) además de cortar el stream local.
  const stop = useCallback(() => {
    const turnId = state.turnId;
    if (turnId) {
      void (async () => {
        const token = await tokens.get(false);
        await fetch(`${baseUrl.replace(/\/+$/, "")}/api/v1/chat/${turnId}/cancel`, {
          method: "POST",
          credentials: "omit",
          headers: { Authorization: `Bearer ${token}` },
        });
      })().catch(() => undefined);
    }
    cancel();
  }, [state.turnId, tokens, baseUrl, cancel]);

  const format: ResultFormat = { ...NO_FORMAT, locale: text.locale };

  const ask = useCallback(
    (message: string) => {
      void (async () => {
        let datasourceId: string;
        try {
          datasourceId = await tokens.datasourceId();
        } catch (error) {
          const detail: ErrorDetail = {
            code: "token_error",
            message: error instanceof TokenError ? `${text.noToken} (${error.message})` : text.noToken,
            recoverable: true,
          };
          setLocalError(detail);
          handlers.current.onError?.(detail);
          return;
        }
        setLocalError(null);
        if (question !== null) setHistory((items) => [...items, { question, turn: state }]);
        setQuestion(message);
        void send({
          conversation_id: state.conversationId,
          datasource_id: datasourceId,
          message,
        });
      })();
    },
    [tokens, text.noToken, question, state, send],
  );

  const scroller = useRef<HTMLDivElement>(null);
  const stick = useRef(true);
  function onScroll(event: UIEvent<HTMLDivElement>) {
    const el = event.currentTarget;
    stick.current = el.scrollHeight - el.scrollTop - el.clientHeight <= STICK_THRESHOLD;
  }
  useEffect(() => {
    const el = scroller.current;
    if (el && stick.current) el.scrollTop = el.scrollHeight;
  }, [state, history, question]);

  const suggestions = suggestedQuestions?.length ? suggestedQuestions : [text.defaultSuggestion];
  const empty = question === null && history.length === 0;
  const exchangeProps = { format, showSql, showReasoning, thinkingLabel: text.thinking };

  return (
    <div className="chatiapp-root">
      <div ref={scroller} onScroll={onScroll} className="min-h-0 flex-1 overflow-y-auto p-4">
        {empty ? (
          <section className="mx-auto flex max-w-xl flex-col items-center gap-4 py-8 text-center">
            <h2 className="text-xl font-semibold tracking-tight">{text.heading}</h2>
            <p className="text-muted-foreground">{text.hint}</p>
            <ul className="flex flex-wrap justify-center gap-2" aria-label={text.suggestionsLabel}>
              {suggestions.map((suggestion) => (
                <li key={suggestion}>
                  <Button variant="outline" size="sm" disabled={busy} onClick={() => ask(suggestion)}>
                    {suggestion}
                  </Button>
                </li>
              ))}
            </ul>
          </section>
        ) : (
          <div className="flex flex-col gap-6">
            {history.map((message, index) => (
              <Exchange
                key={index}
                question={message.question}
                turn={message.turn}
                {...exchangeProps}
              />
            ))}
            {question !== null && (
              <Exchange question={question} turn={state} onOption={ask} live {...exchangeProps} />
            )}
          </div>
        )}
        {localError && (
          <p role="alert" className="mt-4 text-sm text-destructive">
            {localError.message}
          </p>
        )}
      </div>
      <Composer
        busy={busy}
        labels={{
          question: text.question,
          placeholder: text.placeholder,
          send: text.send,
          cancel: text.cancel,
        }}
        onSend={ask}
        onCancel={stop}
      />
    </div>
  );
}
