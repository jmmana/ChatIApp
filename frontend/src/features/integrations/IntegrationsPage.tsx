import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plug, Plus } from "lucide-react";
import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  createApiKey,
  listApiKeys,
  revokeApiKey,
  updateApiKey,
  type ApiKey,
  type ApiKeyCreated,
  type ApiKeyInput,
} from "./api";
import { CopyButton } from "./CopyButton";
import { KeyFormDialog } from "./KeyFormDialog";
import { backendSnippet, widgetSnippet } from "./snippets";

const none = "—";
const join = (items: string[]) => (items.length ? items.join(", ") : none);
const date = (value: string | null) => (value ? new Date(value).toLocaleString("es") : "Nunca");

function usageText(key: ApiKey): string {
  if (!key.usage) return none;
  const { turns, tokens, cost_usd } = key.usage;
  return `${turns} turnos · ${tokens} tokens · US$ ${cost_usd.toFixed(2)}`;
}

function errorText(error: unknown): string | null {
  return error instanceof Error ? error.message : null;
}

function SecretDialog({ created, onClose }: { created: ApiKeyCreated; onClose: () => void }) {
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>API key creada</DialogTitle>
          <DialogDescription>
            Cópiala ahora: no volverás a verla. Si la pierdes, crea otra.
          </DialogDescription>
        </DialogHeader>
        <code className="break-all rounded-md bg-muted p-3 font-mono text-sm">{created.secret}</code>
        <p role="note" className="text-sm text-destructive">
          Es una credencial de servidor: no la uses en el navegador, en una app móvil ni en un
          repositorio.
        </p>
        <DialogFooter>
          <CopyButton text={created.secret} label="Copiar secreto" />
          <Button onClick={onClose}>Listo</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function RevokeDialog({
  apiKey,
  pending,
  error,
  onConfirm,
  onClose,
}: {
  apiKey: ApiKey;
  pending: boolean;
  error: string | null;
  onConfirm: () => void;
  onClose: () => void;
}) {
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Revocar API key</DialogTitle>
          <DialogDescription>
            ¿Revocar «{apiKey.name}»? Dejará de funcionar al instante, junto con todos sus tokens de
            sesión. No se puede deshacer.
          </DialogDescription>
        </DialogHeader>
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancelar
          </Button>
          <Button variant="destructive" disabled={pending} onClick={onConfirm}>
            Confirmar revocación
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function Snippet({ title, code }: { title: string; code: string }) {
  return (
    <div className="grid gap-2">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium">{title}</h3>
        <CopyButton text={code} label={`Copiar ${title.toLowerCase()}`} />
      </div>
      <pre className="overflow-x-auto rounded-md bg-muted p-3 font-mono text-xs">{code}</pre>
    </div>
  );
}

export function IntegrationsPage() {
  const queryClient = useQueryClient();
  const keys = useQuery({ queryKey: ["api-keys"], queryFn: listApiKeys });
  const [form, setForm] = useState<{ key: ApiKey | null } | null>(null);
  const [created, setCreated] = useState<ApiKeyCreated | null>(null);
  const [revoking, setRevoking] = useState<ApiKey | null>(null);
  const baseUrl = window.location.origin;

  const refresh = () => queryClient.invalidateQueries({ queryKey: ["api-keys"] });

  const save = useMutation({
    mutationFn: (input: ApiKeyInput) =>
      form?.key ? updateApiKey(form.key.id, input) : createApiKey(input),
    onSuccess: (result) => {
      if ("secret" in result) setCreated(result as ApiKeyCreated);
      setForm(null);
      void refresh();
    },
  });

  const revoke = useMutation({
    mutationFn: (id: string) => revokeApiKey(id),
    onSuccess: () => {
      setRevoking(null);
      void refresh();
    },
  });

  return (
    <section className="mx-auto grid max-w-6xl gap-6">
      <div className="flex items-start justify-between gap-4">
        <div className="grid gap-1">
          <h1 className="flex items-center gap-2 text-2xl font-semibold tracking-tight">
            <Plug className="size-6" aria-hidden /> Integraciones
          </h1>
          <p className="text-muted-foreground">
            API keys de las aplicaciones que integran ChatIApp.
          </p>
        </div>
        <Button
          onClick={() => {
            save.reset();
            setForm({ key: null });
          }}
        >
          <Plus aria-hidden /> Nueva API key
        </Button>
      </div>

      {keys.isError && (
        <p role="alert" className="text-sm text-destructive">
          {errorText(keys.error) ?? "No se pudieron cargar las API keys."}
        </p>
      )}
      {keys.data?.length === 0 && (
        <p className="text-sm text-muted-foreground">Todavía no hay API keys.</p>
      )}
      {keys.data && keys.data.length > 0 && (
        <div className="overflow-x-auto rounded-lg border bg-card">
          <table className="w-full text-left text-sm">
            <thead className="border-b text-xs text-muted-foreground">
              <tr>
                {[
                  "Nombre",
                  "Prefijo",
                  "Alcances",
                  "Fuentes",
                  "Roles",
                  "Orígenes",
                  "Último uso",
                  "Consumo del mes",
                  "Acciones",
                ].map((h) => (
                  <th key={h} className="px-3 py-2 font-medium">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {keys.data.map((key) => (
                <tr key={key.id} className="border-b align-top last:border-0">
                  <td className="px-3 py-2 font-medium">
                    {key.name} {key.revoked_at && <Badge variant="destructive">Revocada</Badge>}
                  </td>
                  <td className="px-3 py-2 font-mono text-xs">{key.prefix}</td>
                  <td className="px-3 py-2">{join(key.scopes)}</td>
                  <td className="px-3 py-2">{join(key.datasources)}</td>
                  <td className="px-3 py-2">{join(key.allowed_roles)}</td>
                  <td className="px-3 py-2">{join(key.allowed_origins)}</td>
                  <td className="px-3 py-2">{date(key.last_used_at)}</td>
                  <td className="px-3 py-2">{usageText(key)}</td>
                  <td className="px-3 py-2">
                    {!key.revoked_at && (
                      <div className="flex gap-1">
                        <Button
                          variant="ghost"
                          size="sm"
                          aria-label={`Editar ${key.name}`}
                          onClick={() => {
                            save.reset();
                            setForm({ key });
                          }}
                        >
                          Editar
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          aria-label={`Revocar ${key.name}`}
                          onClick={() => {
                            revoke.reset();
                            setRevoking(key);
                          }}
                        >
                          Revocar
                        </Button>
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="grid gap-4 rounded-lg border bg-card p-4">
        <h2 className="text-lg font-semibold">Fragmentos para copiar</h2>
        <p className="text-sm text-muted-foreground">
          Con la URL de esta instalación: <code className="font-mono">{baseUrl}</code>
        </p>
        <Snippet title="Backend" code={backendSnippet(baseUrl)} />
        <Snippet title="Widget" code={widgetSnippet(baseUrl)} />
      </div>

      {form && (
        <KeyFormDialog
          key={form.key?.id ?? "nueva"}
          apiKey={form.key}
          pending={save.isPending}
          error={errorText(save.error)}
          onSubmit={(input) => save.mutate(input)}
          onClose={() => setForm(null)}
        />
      )}
      {created && <SecretDialog created={created} onClose={() => setCreated(null)} />}
      {revoking && (
        <RevokeDialog
          apiKey={revoking}
          pending={revoke.isPending}
          error={errorText(revoke.error)}
          onConfirm={() => revoke.mutate(revoking.id)}
          onClose={() => setRevoking(null)}
        />
      )}
    </section>
  );
}
