import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";
import type { UIEvent } from "react";
import { MessageSquare } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import { useAuth } from "@/features/auth/AuthProvider";
import { listDatasources } from "@/features/datasources/api";
import { listProviders } from "@/features/providers/api";
import { Clarification } from "./Clarification";
import { cancelTurnOnServer, getConversation, getFormatSettings, getMetrics, getRoles } from "./api";
import { Composer } from "./Composer";
import { messagesFromStored } from "./rebuild";
import type { Message } from "./rebuild";
import { CONVERSATIONS_KEY } from "./queryKeys";
import { Reasoning } from "./Reasoning";
import { ResultView } from "./results/ResultView";
import { Sidebar } from "./Sidebar";
import { SqlBlock } from "./SqlBlock";
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

const selectClass = "h-9 rounded-md border border-input bg-card px-2 text-sm";

export function ChatPage() {
  const { user } = useAuth();
  const isAdmin = user?.is_admin ?? false;
  const queryClient = useQueryClient();
  const { state, send, cancel, retry, reset } = useTurn();
  const [history, setHistory] = useState<Message[]>([]);
  const [question, setQuestion] = useState<string | null>(null);
  /** Conversación abierta desde la barra lateral (los turnos nuevos usan `state.conversationId`). */
  const [openedId, setOpenedId] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [datasourceId, setDatasourceId] = useState("");
  const [providerId, setProviderId] = useState("");
  const [role, setRole] = useState("");
  /** Menú de conversaciones en pantallas estrechas, donde la barra lateral no cabe. */
  const [historyOpen, setHistoryOpen] = useState(false);

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
        conversation_id: state.conversationId ?? openedId,
        datasource_id: selectedSource,
        message,
        provider_override: providerId || null,
        view_as: isAdmin && role ? { role } : null,
      });
    },
    [selectedSource, question, state, send, providerId, isAdmin, role, openedId],
  );

  const newConversation = useCallback(() => {
    reset();
    setHistory([]);
    setQuestion(null);
    setOpenedId(null);
    setLoadError(null);
  }, [reset]);

  const openConversation = useCallback(
    async (id: string) => {
      try {
        const detail = await getConversation(id);
        reset();
        setHistory(messagesFromStored(detail.messages));
        setQuestion(null);
        setOpenedId(id);
        setLoadError(null);
        setDatasourceId(detail.datasource_id);
      } catch (error) {
        setLoadError(error instanceof Error ? error.message : "No se pudo abrir la conversación.");
      }
    },
    [reset],
  );

  // Ctrl/⌘+K abre una conversación nueva.
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        newConversation();
      }
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [newConversation]);

  // Un turno terminado crea o actualiza la conversación: refresca la barra lateral.
  useEffect(() => {
    if (state.status === "completed" || state.status === "clarifying") {
      void queryClient.invalidateQueries({ queryKey: CONVERSATIONS_KEY });
    }
  }, [state.status, queryClient]);

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
    <div className="-m-4 flex h-[calc(100dvh-4rem)] min-h-0 md:-m-6 md:h-dvh">
      <Sidebar
        activeId={state.conversationId ?? openedId}
        onSelect={(id) => void openConversation(id)}
        onNew={newConversation}
        onDeleted={(id) => {
          if ((state.conversationId ?? openedId) === id) newConversation();
        }}
      />
      <div className="flex min-w-0 flex-1 flex-col">
      <h1 className="sr-only">Chat</h1>
      <header className="flex flex-wrap items-center gap-3 border-b px-4 py-2">
        <Sheet open={historyOpen} onOpenChange={setHistoryOpen}>
          <SheetTrigger asChild>
            <Button variant="outline" size="sm" className="lg:hidden">
              <MessageSquare aria-hidden /> Conversaciones
            </Button>
          </SheetTrigger>
          <SheetContent side="left" className="p-0 pt-12">
            <SheetTitle className="sr-only">Conversaciones</SheetTitle>
            <SheetDescription className="sr-only">
              Abre, renombra o elimina una conversación
            </SheetDescription>
            <Sidebar
              variant="sheet"
              activeId={state.conversationId ?? openedId}
              onSelect={(id) => {
                setHistoryOpen(false);
                void openConversation(id);
              }}
              onNew={() => {
                setHistoryOpen(false);
                newConversation();
              }}
              onDeleted={(id) => {
                if ((state.conversationId ?? openedId) === id) newConversation();
              }}
            />
          </SheetContent>
        </Sheet>
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

      {loadError && (
        <p role="alert" className="px-4 py-2 text-sm text-destructive">
          {loadError}
        </p>
      )}

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
              <Exchange
                question={question}
                turn={state}
                onOption={ask}
                onRetry={retry}
                format={format}
                live
              />
            )}
          </div>
        )}
      </div>

      <Composer busy={busy} disabled={!selectedSource} onSend={ask} onCancel={stop} />
      </div>
    </div>
  );
}

interface ExchangeProps {
  question: string;
  turn: TurnState;
  onOption?: (option: string) => void;
  onRetry?: () => void;
  format: ResultFormat;
  live?: boolean;
}

function Exchange({ question, turn, onOption, onRetry, format, live = false }: ExchangeProps) {
  const text = turn.answer || turn.clarification?.question || "";
  return (
    <article className="flex flex-col gap-3">
      <p className="self-end rounded-xl bg-accent px-3 py-2 text-accent-foreground">{question}</p>
      <Reasoning
        steps={turn.steps}
        reasoning={turn.reasoning}
        streaming={turn.status === "streaming"}
      />
      {turn.status === "streaming" && !text && turn.steps.length === 0 && (
        <p role="status" className="text-sm text-muted-foreground">
          Pensando…
        </p>
      )}
      {turn.sql && <SqlBlock sql={turn.sql} streaming={turn.status === "streaming"} />}
      {turn.result && <ResultView result={turn.result} sql={turn.sql} {...format} />}
      {text && <p className="whitespace-pre-wrap">{text}</p>}
      {live && turn.status === "clarifying" && turn.clarification && (
        <Clarification
          question={turn.clarification.question}
          options={turn.clarification.options}
          onSelect={(option) => onOption?.(option)}
        />
      )}
      {turn.status === "error" && turn.error && (
        <div className="flex flex-wrap items-center gap-3">
          <p role="alert" className="text-sm text-destructive">
            {turn.error.message}
          </p>
          {live && turn.error.recoverable && onRetry && (
            <Button variant="outline" size="sm" onClick={onRetry}>
              Reintentar
            </Button>
          )}
        </div>
      )}
    </article>
  );
}
