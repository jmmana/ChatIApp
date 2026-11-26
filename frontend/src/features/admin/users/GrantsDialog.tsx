import { useQueries, useQuery } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { listDatasources } from "@/features/datasources/api";
import { listRoles, type AttributeValue, type Grant, type ManagedUser } from "./api";

/** Cada fuente: rol elegido ("" = sin acceso) y atributos como texto separado por comas. */
type Draft = Record<string, { role: string; attributes: Record<string, string> }>;

const asText = (value: AttributeValue | undefined) =>
  Array.isArray(value) ? value.join(", ") : value === undefined ? "" : String(value);

function parseValue(text: string): AttributeValue {
  const items = text
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
  const parsed = items.map((item) => (/^-?\d+(\.\d+)?$/.test(item) ? Number(item) : item));
  return parsed;
}

interface Props {
  user: ManagedUser;
  pending: boolean;
  error: string | null;
  onSubmit: (grants: Grant[]) => void;
  onClose: () => void;
}

export function GrantsDialog({ user, pending, error, onSubmit, onClose }: Props) {
  const datasources = useQuery({ queryKey: ["datasources"], queryFn: listDatasources });
  const sources = datasources.data ?? [];
  const roles = useQueries({
    queries: sources.map((source) => ({
      queryKey: ["semantic-roles", source.id],
      queryFn: () => listRoles(source.id),
    })),
  });
  const [draft, setDraft] = useState<Draft>(() =>
    Object.fromEntries(
      user.grants.map((g) => [
        g.datasource_id,
        {
          role: g.role,
          attributes: Object.fromEntries(
            Object.entries(g.attributes).map(([key, value]) => [key, asText(value)]),
          ),
        },
      ]),
    ),
  );

  function update(id: string, patch: Partial<Draft[string]>) {
    setDraft((current) => ({
      ...current,
      [id]: { ...(current[id] ?? { role: "", attributes: {} }), ...patch },
    }));
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    const grants = Object.entries(draft)
      .filter(([, entry]) => entry.role)
      .map(([datasource_id, entry]) => ({
        datasource_id,
        role: entry.role,
        attributes: Object.fromEntries(
          Object.entries(entry.attributes)
            .filter(([, text]) => text.trim())
            .map(([key, text]) => [key, parseValue(text)]),
        ),
      }));
    onSubmit(grants);
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Permisos de {user.email}</DialogTitle>
          <DialogDescription>
            Elige el rol de la persona en cada fuente. Sin rol no puede consultarla.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="grid gap-4">
          {datasources.isSuccess && sources.length === 0 && (
            <p className="text-sm text-muted-foreground">Todavía no hay fuentes de datos.</p>
          )}
          {sources.map((source, index) => {
            const available = roles[index]?.data ?? [];
            const entry = draft[source.id];
            const selected = available.find((r) => r.name === entry?.role);
            return (
              <fieldset key={source.id} className="grid gap-2 rounded-md border p-3 text-sm">
                <legend className="px-1 font-medium">{source.name}</legend>
                <label className="grid gap-1">
                  Rol en {source.name}
                  <select
                    className="h-9 rounded-md border border-input bg-card px-3 text-sm"
                    value={entry?.role ?? ""}
                    onChange={(e) => update(source.id, { role: e.target.value })}
                  >
                    <option value="">Sin acceso</option>
                    {available.map((role) => (
                      <option key={role.name} value={role.name}>
                        {role.name}
                      </option>
                    ))}
                  </select>
                </label>
                {selected?.attributes.map((name) => (
                  <label key={name} className="grid gap-1">
                    Atributo «{name}» (separa varios valores con comas)
                    <Input
                      value={entry?.attributes[name] ?? ""}
                      onChange={(e) =>
                        update(source.id, {
                          attributes: { ...entry?.attributes, [name]: e.target.value },
                        })
                      }
                    />
                  </label>
                ))}
              </fieldset>
            );
          })}
          {error && (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          )}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              Cancelar
            </Button>
            <Button type="submit" disabled={pending}>
              Guardar permisos
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
