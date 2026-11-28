export type Lang = "es" | "en";

export interface Messages {
  heading: string;
  hint: string;
  suggestionsLabel: string;
  thinking: string;
  question: string;
  placeholder: string;
  send: string;
  cancel: string;
  defaultSuggestion: string;
  noToken: string;
  locale: string;
}

export const MESSAGES: Record<Lang, Messages> = {
  es: {
    heading: "¿Qué quieres saber?",
    hint: "Pregunta sobre tus datos en lenguaje natural.",
    suggestionsLabel: "Preguntas sugeridas",
    thinking: "Pensando…",
    question: "Pregunta",
    placeholder: "Pregunta sobre tus datos…",
    send: "Enviar",
    cancel: "Cancelar",
    defaultSuggestion: "¿Qué puedo preguntar sobre mis datos?",
    noToken: "No se pudo obtener la sesión del chat.",
    locale: "es-CO",
  },
  en: {
    heading: "What do you want to know?",
    hint: "Ask about your data in plain language.",
    suggestionsLabel: "Suggested questions",
    thinking: "Thinking…",
    question: "Question",
    placeholder: "Ask about your data…",
    send: "Send",
    cancel: "Cancel",
    defaultSuggestion: "What can I ask about my data?",
    noToken: "Could not get the chat session.",
    locale: "en-US",
  },
};

export function parseLang(value: string | null | undefined): Lang {
  return value === "en" ? "en" : "es";
}
