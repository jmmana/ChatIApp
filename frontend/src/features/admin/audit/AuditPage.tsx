import { useMutation, useQuery } from "@tanstack/react-query";
import { Download, ScrollText } from "lucide-react";
import { useState, type ReactNode } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { listDatasources } from "@/features/datasources/api";
import { listApiKeys } from "@/features/integrations/api";
import {
  PAGE_SIZE,
  emptyFilters,
  exportAudit,
  listAudit,
  type AuditEntry,
  type AuditFilters,
  type AuditStatus,
} from "./api";

const none = "—";
const STATUS_LABELS: Record<AuditStatus, string> = {
  ok: "Correcto",
  rejected: "Rechazado",
  error: "Error",
};
const selectClass =
  "flex h-9 w-full rounded-md border border-input bg-card px-3 py-1 text-sm disabled:opacity-50";

const dateTime = (value: string) => new Date(value).toLocaleString("es");
const text = (value: string | number | null | undefined) =>
  value === null || value === undefined || value === "" ? none : String(value);

function who(entry: AuditEntry): string {
  if (entry.external_user_id) return `${entry.external_user_id} (vía ${text(entry.api_key_name)})`;
  return entry.user_email ?? none;
}

function errorText(error: unknown): string | null {
  return error instanceof Error ? error.message : null;
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="grid gap-1 text-xs font-medium text-muted-foreground">
      {label}
      {children}
    </label>
  );
}

function StatusBadge({ status }: { status: AuditStatus }) {
  return (
    <Badge variant={status === "ok" ? "secondary" : "destructive"}>{STATUS_LABELS[status]}</Badge>
  );
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div className="grid gap-0.5">
      <dt className="text-xs font-medium text-muted-foreground">{label}</dt>
      <dd className="text-sm">{value}</dd>
    </div>
  );
}

function Code({ title, code }: { title: string; code: string | null }) {
  return (
    <div className="grid gap-1">
      <h3 className="text-sm font-medium">{title}</h3>
      <pre className="overflow-x-auto whitespace-pre-wrap rounded-md bg-muted p-3 font-mono text-xs">
        {code ?? none}
      </pre>
    </div>
  );
}

function EntryDialog({ entry, onClose }: { entry: AuditEntry; onClose: () => void }) {
  const filters = entry.filters_applied
    ? Object.entries(entry.filters_applied)
        .flatMap(([kind, items]) => items.map((item) => `${kind}: ${item}`))
        .join("\n")
    : "";
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Detalle del turno</DialogTitle>
          <DialogDescription>{dateTime(entry.created_at)}</DialogDescription>
        </DialogHeader>
        <dl className="grid grid-cols-2 gap-3">
          <Detail label="Resultado" value={STATUS_LABELS[entry.status]} />
          <Detail label="Código de error" value={text(entry.error_code)} />
          <Detail label="Usuario" value={text(entry.user_email)} />
          <Detail label="Usuario final" value={text(entry.external_user_id)} />
          <Detail label="API key" value={text(entry.api_key_name)} />
          <Detail label="Rol" value={text(entry.role)} />
          <Detail label="Fuente" value={text(entry.datasource)} />
          <Detail label="Versión del modelo semántico" value={text(entry.semantic_version)} />
          <Detail label="Proveedor" value={text(entry.provider_kind)} />
          <Detail label="Modelo" value={text(entry.model)} />
          <Detail
            label="Tokens (entrada / salida)"
            value={`${text(entry.tokens_in)} / ${text(entry.tokens_out)}`}
          />
          <Detail
            label="Costo"
            value={entry.cost_usd === null ? none : `US$ ${Number(entry.cost_usd).toFixed(4)}`}
          />
          <Detail label="Duración" value={entry.elapsed_ms === null ? none : `${entry.elapsed_ms} ms`} />
          <Detail label="Filas devueltas" value={text(entry.row_count)} />
          <Detail label="Origen del SQL" value={entry.origin === "llm" ? "IA" : "Catálogo"} />
          <Detail label="Tabla resumida" value={text(entry.summary_table)} />
        </dl>
        <Code title="Pregunta" code={entry.question} />
        <Code title="Plan" code={entry.plan ? JSON.stringify(entry.plan, null, 2) : null} />
        <Code title="SQL candidato" code={entry.sql_candidate} />
        <Code title="SQL final" code={entry.sql_final} />
        <Code title="Filtros aplicados" code={filters || null} />
      </DialogContent>
    </Dialog>
  );
}

export function AuditPage() {
  const [draft, setDraft] = useState<AuditFilters>(emptyFilters);
  const [filters, setFilters] = useState<AuditFilters>(emptyFilters);
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<AuditEntry | null>(null);

  const audit = useQuery({
    queryKey: ["audit", filters, page],
    queryFn: () => listAudit(filters, page),
  });
  const datasources = useQuery({ queryKey: ["datasources"], queryFn: listDatasources });
  const keys = useQuery({ queryKey: ["api-keys"], queryFn: listApiKeys });

  const download = useMutation({
    mutationFn: async () => {
      const blob = await exportAudit(filters);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "auditoria.csv";
      link.click();
      URL.revokeObjectURL(url);
    },
  });

  const set = (field: keyof AuditFilters) => (value: string) =>
    setDraft((current) => ({ ...current, [field]: value }));
  const total = audit.data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <section className="mx-auto grid max-w-6xl gap-6">
      <div className="flex items-start justify-between gap-4">
        <div className="grid gap-1">
          <h1 className="flex items-center gap-2 text-2xl font-semibold tracking-tight">
            <ScrollText className="size-6" aria-hidden /> Auditoría
          </h1>
          <p className="text-muted-foreground">
            Quién preguntó qué, qué SQL se ejecutó, con qué filtros y cuánto costó.
          </p>
        </div>
        <Button variant="outline" disabled={download.isPending} onClick={() => download.mutate()}>
          <Download aria-hidden /> Exportar CSV
        </Button>
      </div>

      <form
        className="grid gap-3 rounded-lg border bg-card p-4 sm:grid-cols-2 lg:grid-cols-4"
        onSubmit={(event) => {
          event.preventDefault();
          setPage(1);
          setFilters(draft);
        }}
      >
        <Field label="Usuario (ID)">
          <Input value={draft.user_id} onChange={(e) => set("user_id")(e.target.value)} />
        </Field>
        <Field label="Usuario final">
          <Input
            value={draft.external_user_id}
            onChange={(e) => set("external_user_id")(e.target.value)}
          />
        </Field>
        <Field label="Fuente">
          <select
            className={selectClass}
            value={draft.datasource_id}
            onChange={(e) => set("datasource_id")(e.target.value)}
          >
            <option value="">Todas</option>
            {datasources.data?.map((d) => (
              <option key={d.id} value={d.id}>
                {d.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="API key">
          <select
            className={selectClass}
            value={draft.api_key_id}
            onChange={(e) => set("api_key_id")(e.target.value)}
          >
            <option value="">Todas</option>
            {keys.data?.map((k) => (
              <option key={k.id} value={k.id}>
                {k.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Estado">
          <select
            className={selectClass}
            value={draft.status}
            onChange={(e) => set("status")(e.target.value)}
          >
            <option value="">Todos</option>
            {(Object.keys(STATUS_LABELS) as AuditStatus[]).map((s) => (
              <option key={s} value={s}>
                {STATUS_LABELS[s]}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Desde">
          <Input
            type="date"
            value={draft.date_from}
            onChange={(e) => set("date_from")(e.target.value)}
          />
        </Field>
        <Field label="Hasta">
          <Input
            type="date"
            value={draft.date_to}
            onChange={(e) => set("date_to")(e.target.value)}
          />
        </Field>
        <div className="flex items-end gap-2">
          <Button type="submit">Filtrar</Button>
          <Button
            type="button"
            variant="ghost"
            onClick={() => {
              setDraft(emptyFilters);
              setFilters(emptyFilters);
              setPage(1);
            }}
          >
            Limpiar
          </Button>
        </div>
      </form>

      {(audit.isError || download.isError) && (
        <p role="alert" className="text-sm text-destructive">
          {errorText(audit.error) ?? errorText(download.error) ?? "No se pudo completar la operación."}
        </p>
      )}
      {audit.data?.items.length === 0 && (
        <p className="text-sm text-muted-foreground">No hay turnos con esos filtros.</p>
      )}
      {audit.data && audit.data.items.length > 0 && (
        <div className="overflow-x-auto rounded-lg border bg-card">
          <table className="w-full text-left text-sm">
            <thead className="border-b text-xs text-muted-foreground">
              <tr>
                {["Fecha", "Quién", "Fuente", "Pregunta", "Resultado", "Filas", "Costo", ""].map(
                  (h) => (
                    <th key={h || "acciones"} className="px-3 py-2 font-medium">
                      {h}
                    </th>
                  ),
                )}
              </tr>
            </thead>
            <tbody>
              {audit.data.items.map((entry) => (
                <tr key={entry.id} className="border-b align-top last:border-0">
                  <td className="px-3 py-2">{dateTime(entry.created_at)}</td>
                  <td className="px-3 py-2">{who(entry)}</td>
                  <td className="px-3 py-2">{text(entry.datasource)}</td>
                  <td className="max-w-xs truncate px-3 py-2">{text(entry.question)}</td>
                  <td className="px-3 py-2">
                    <StatusBadge status={entry.status} />
                  </td>
                  <td className="px-3 py-2">{text(entry.row_count)}</td>
                  <td className="px-3 py-2">
                    {entry.cost_usd === null ? none : `US$ ${Number(entry.cost_usd).toFixed(4)}`}
                  </td>
                  <td className="px-3 py-2">
                    <Button
                      variant="ghost"
                      size="sm"
                      aria-label={`Ver detalle de ${text(entry.question)}`}
                      onClick={() => setSelected(entry)}
                    >
                      Ver detalle
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="flex items-center justify-between text-sm text-muted-foreground">
        <span>
          {total} {total === 1 ? "turno" : "turnos"} · página {page} de {pages}
        </span>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>
            Anterior
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={page >= pages}
            onClick={() => setPage(page + 1)}
          >
            Siguiente
          </Button>
        </div>
      </div>

      {selected && <EntryDialog entry={selected} onClose={() => setSelected(null)} />}
    </section>
  );
}
