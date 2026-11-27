import { createElement, useEffect, useRef } from "react";
import type { CSSProperties } from "react";
import type { AnswerDetail, ClarificationDetail, ErrorDetail } from "../../src/EmbeddedChat";
import { ChatiappChatElement, defineChatiappChat, TAG_NAME } from "../../src/element";
import type { GetToken } from "../../src/tokens";

export type { AnswerDetail, ClarificationDetail, ErrorDetail, GetToken };

export interface ChatIAppChatProps {
  /** Origen de tu ChatIApp, p. ej. `https://chatiapp.tuempresa.com`. */
  baseUrl: string;
  /** Pide un token de sesión a tu backend; se vuelve a llamar cuando expira. */
  getToken: GetToken;
  lang?: "es" | "en";
  theme?: "auto" | "light" | "dark";
  showSql?: boolean;
  showReasoning?: boolean;
  suggestedQuestions?: string[];
  onAnswer?: (detail: AnswerDetail) => void;
  onClarification?: (detail: ClarificationDetail) => void;
  onError?: (detail: ErrorDetail) => void;
  className?: string;
  /** Tamaño y variables `--chatiapp-*`: `style={{ "--chatiapp-accent": "#0a7" }}`. */
  style?: CSSProperties;
}

/** `<chatiapp-chat>` como componente de React. */
export function ChatIAppChat({
  baseUrl,
  getToken,
  lang,
  theme,
  showSql,
  showReasoning,
  suggestedQuestions,
  onAnswer,
  onClarification,
  onError,
  className,
  style,
}: ChatIAppChatProps) {
  defineChatiappChat();
  const ref = useRef<ChatiappChatElement>(null);

  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    element.getToken = getToken;
    element.suggestedQuestions = suggestedQuestions;
  }, [getToken, suggestedQuestions]);

  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    const listeners: [string, ((detail: never) => void) | undefined][] = [
      ["chatiapp:answer", onAnswer],
      ["chatiapp:clarification", onClarification],
      ["chatiapp:error", onError],
    ];
    const bound = listeners.map(([name, handler]) => {
      const listener = (event: Event) => handler?.((event as CustomEvent).detail as never);
      element.addEventListener(name, listener);
      return () => element.removeEventListener(name, listener);
    });
    return () => bound.forEach((unbind) => unbind());
  }, [onAnswer, onClarification, onError]);

  return createElement(TAG_NAME, {
    ref,
    "base-url": baseUrl,
    lang,
    theme,
    "show-sql": showSql === undefined ? undefined : String(showSql),
    "show-reasoning": showReasoning === undefined ? undefined : String(showReasoning),
    className,
    style,
  });
}
