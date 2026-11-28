import type { CSSProperties, ReactElement } from "react";

export type GetToken = () => string | Promise<string>;

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
  style?: CSSProperties;
}

export function ChatIAppChat(props: ChatIAppChatProps): ReactElement;
