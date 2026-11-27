import { useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";
import type { UIEvent } from "react";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/features/auth/AuthProvider";
import { listDatasources } from "@/features/datasources/api";
import { listProviders } from "@/features/providers/api";
import { cancelTurnOnServer, getFormatSettings, getMetrics, getRoles } from "./api";
import { Composer } from "./Composer";
import { ResultView } from "./results/ResultView";
import { buildSuggestions } from "./suggestions";
import type { TurnState } from "./turnReducer";
import { useTurn } from "./useTurn";

/** Distancia (px) al final desde la que se considera que la persona sigue «abajo». */
const STICK_THRESHOLD = 48;

interface ResultFormat {
  locale?: string;
  currency?: string;
  metricLabels: Record<string, string>;
}

interface Message {
  question: string;
  turn: TurnState;
}

const selectClass = "h-9 rounded-md border border-input bg-card px-2 text-sm";

export function ChatPage() {
  const { user } = useAuth();
  const isAdmin = user?.is_admin ?? false;
  const { state, send, cancel } = useTurn();
  const [history, setHistory] = useState<Message[]>([]);
  const [question, setQuestion] = useState<string | null>(null);
  const [datasourceId, setDatasourceId] = useState("");
  const [providerId, setProviderId] = useState("");
  const [role, setRole] = useState("");

  const datasources = useQuery({ queryKey: ["datasources"], queryFn: listDatasources });
  const providers = useQuery({ queryKey: ["providers"], queryFn: listProviders });
  const sources = Array.isArray(datasources.data) ? datasources.data : [];
  const models = Array.isArray(providers.data) ? providers.data : [];
  const selectedSource = datasourceId || sources[0]?.id || "";
  const metrics = useQuery({
    queryKey: ["chat-metrics", selectedSource],
    queryFn: () => getMetrics(selectedSource),
    enabled: selectedSource !== "",
  });
  const formatSettings = useQuery({
    queryKey: ["chat-format", selectedSource],
    queryFn: () => getFormatSettings(selectedSource),
    enabled: selectedSource !== "" && isAdmin,
  });
  const roles = useQuery({
    queryKey: ["chat-roles", selectedSource],
    queryFn: () => getRoles(selectedSource),
    enabled: selectedSource !== "" && isAdmin,
  });

  const busy = state.status === "streaming";
  const suggestions = buildSuggestions(metrics.data ?? []);
  const format: ResultFormat = {
    locale: formatSettings.data?.locale,
    currency: formatSettings.data?.currency,
    metricLabels: Object.fromEntries((metrics.data ?? []).map((m) => [m.name, m.label])),
  };

  const ask = useCallback(
    (message: string) => {
      if (!selectedSource) return;
      if (question !== null) setHistory((items) => [...items, { question, turn: state }]);
      setQuestion(message);
      void send({
        conversation_id: state.conversationId,
        datasource_id: selectedSource,
        message,
        provider_override: providerId || null,
        view_as: isAdmin && role ? { role } : null,
      });
    },
    [selectedSource, question, state, send, providerId, isAdmin, role],
  );

  const stop = useCallback(() => {
    if (state.turnId) void cancelTurnOnServer(state.turnId);
    cancel();
  }, [state.turnId, cancel]);

  // Desplazamiento automático: se detiene si la persona sube a leer y se reanuda al volver abajo.
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

  const empty = question === null && history.length === 0;

  return (
    <div className="-m-6 flex h-screen min-h-0 flex-col">
      <h1 className="sr-only">Chat</h1>
      <header className="flex flex-wrap items-center gap-3 border-b px-4 py-2">
        <select
          aria-label="Fuente de datos"
          className={selectClass}
          value={selectedSource}
          onChange={(event) => setDatasourceId(event.target.value)}
        >
          {sources.map((source) => (
            <option key={source.id} value={source.id}>
              {source.name}
            </option>
          ))}
        </select>
        <select
          aria-label="Modelo de IA"
          className={selectClass}
          value={providerId}
          onChange={(event) => setProviderId(event.target.value)}
        >
          <option value="">Modelo por defecto</option>
          {models.map((provider) => (
            <option key={provider.id} value={provider.id}>
              {provider.model}
            </option>
          ))}
        </select>
        {isAdmin && (
          <select
            aria-label="Rol"
            className={selectClass}
            value={role}
            onChange={(event) => setRole(event.target.value)}
          >
            <option value="">Rol: el mío</option>
            {(roles.data ?? []).map((name) => (
              <option key={name} value={name}>
                Rol: {name}
              </option>
            ))}
          </select>
        )}
      </header>

      <div ref={scroller} onScroll={onScroll} className="min-h-0 flex-1 overflow-y-auto p-4">
        {empty ? (
          <section className="mx-auto flex max-w-xl flex-col items-center gap-4 py-16 text-center">
            <h2 className="text-2xl font-semibold tracking-tight">¿Qué quieres saber?</h2>
            <p className="text-muted-foreground">
              Pregunta sobre tus datos en lenguaje natural. Algunas ideas:
            </p>
            <ul className="flex flex-wrap justify-center gap-2" aria-label="Preguntas sugeridas">
              {suggestions.map((text) => (
                <li key={text}>
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={!selectedSource || busy}
                    onClick={() => ask(text)}
                  >
                    {text}
                  </Button>
                </li>
              ))}
            </ul>
          </section>
        ) : (
          <div className="mx-auto flex max-w-3xl flex-col gap-6">
            {history.map((message, index) => (
              <Exchange
                key={index}
                question={message.question}
                turn={message.turn}
                format={format}
              />
            ))}
            {question !== null && (
              <Exchange question={question} turn={state} onOption={ask} format={format} live />
            )}
          </div>
        )}
      </div>

      <Composer busy={busy} disabled={!selectedSource} onSend={ask} onCancel={stop} />
    </div>
  );
}

interface ExchangeProps {
  question: string;
  turn: TurnState;
  onOption?: (option: string) => void;
  format: ResultFormat;
  live?: boolean;
}

function Exchange({ question, turn, onOption, format, live = false }: ExchangeProps) {
  const text = turn.answer || turn.clarification?.question || "";
  return (
    <article className="flex flex-col gap-3">
      <p className="self-end rounded-xl bg-accent px-3 py-2 text-accent-foreground">{question}</p>
      {turn.status === "streaming" && !text && (
        <p role="status" className="text-sm text-muted-foreground">
          {turn.steps.at(-1)?.label ?? "Pensando…"}
        </p>
      )}
      {turn.result && <ResultView result={turn.result} sql={turn.sql} {...format} />}
      {text && <p className="whitespace-pre-wrap">{text}</p>}
      {live && turn.status === "clarifying" && turn.clarification && (
        <div className="flex flex-wrap gap-2">
          {turn.clarification.options.map((option) => (
            <Button key={option} variant="outline" size="sm" onClick={() => onOption?.(option)}>
              {option}
            </Button>
          ))}
        </div>
      )}
      {turn.status === "error" && turn.error && (
        <p role="alert" className="text-sm text-destructive">
          {turn.error.message}
        </p>
      )}
    </article>
  );
}
