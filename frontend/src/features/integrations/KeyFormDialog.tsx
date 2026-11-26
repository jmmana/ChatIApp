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
import { SCOPES, type ApiKey, type ApiKeyInput, type Scope } from "./api";

const list = (text: string) =>
  text
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);

interface Props {
  apiKey: ApiKey | null; // null = crear
  pending: boolean;
  error: string | null;
  onSubmit: (input: ApiKeyInput) => void;
  onClose: () => void;
}

export function KeyFormDialog({ apiKey, pending, error, onSubmit, onClose }: Props) {
  const [name, setName] = useState(apiKey?.name ?? "");
  const [scopes, setScopes] = useState<Scope[]>(apiKey?.scopes ?? ["chat"]);
  const [datasources, setDatasources] = useState(apiKey?.datasources.join(", ") ?? "");
  const [roles, setRoles] = useState(apiKey?.allowed_roles.join(", ") ?? "");
  const [origins, setOrigins] = useState(apiKey?.allowed_origins.join(", ") ?? "");
  const [rate, setRate] = useState(apiKey?.rate_limit_per_minute?.toString() ?? "");
  const [budget, setBudget] = useState(apiKey?.monthly_budget_usd?.toString() ?? "");
  const [expires, setExpires] = useState(apiKey?.expires_at?.slice(0, 10) ?? "");

  function toggle(scope: Scope) {
    setScopes((current) =>
      current.includes(scope) ? current.filter((s) => s !== scope) : [...current, scope],
    );
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    onSubmit({
      name: name.trim(),
      scopes,
      datasources: list(datasources),
      allowed_roles: list(roles),
      allowed_origins: list(origins),
      rate_limit_per_minute: rate ? Number(rate) : null,
      monthly_budget_usd: budget ? Number(budget) : null,
      expires_at: expires ? `${expires}T23:59:59Z` : null,
    });
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{apiKey ? "Editar API key" : "Nueva API key"}</DialogTitle>
          <DialogDescription>
            Una API key identifica a tu aplicación, no a la persona que pregunta.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="grid gap-3">
          <label className="grid gap-1 text-sm font-medium">
            Nombre
            <Input value={name} onChange={(e) => setName(e.target.value)} required maxLength={255} />
          </label>
          <fieldset className="grid gap-1 text-sm">
            <legend className="font-medium">Alcances</legend>
            <div className="flex flex-wrap gap-3">
              {SCOPES.map((scope) => (
                <label key={scope} className="flex items-center gap-1.5">
                  <input
                    type="checkbox"
                    checked={scopes.includes(scope)}
                    onChange={() => toggle(scope)}
                  />
                  {scope}
                </label>
              ))}
            </div>
          </fieldset>
          <label className="grid gap-1 text-sm font-medium">
            Fuentes permitidas
            <Input
              value={datasources}
              onChange={(e) => setDatasources(e.target.value)}
              placeholder="ventas, finanzas"
            />
          </label>
          <label className="grid gap-1 text-sm font-medium">
            Roles permitidos
            <Input
              value={roles}
              onChange={(e) => setRoles(e.target.value)}
              placeholder="gerente_sucursal"
            />
            <span className="text-xs font-normal text-muted-foreground">
              Separados por comas. Son los roles que el backend que integra puede pedir; el rol fijo por key aún no está disponible.
            </span>
          </label>
          <label className="grid gap-1 text-sm font-medium">
            Orígenes permitidos
            <Input
              value={origins}
              onChange={(e) => setOrigins(e.target.value)}
              placeholder="https://portal.tuempresa.com"
            />
          </label>
          <div className="grid grid-cols-2 gap-3">
            <label className="grid gap-1 text-sm font-medium">
              Peticiones por minuto
              <Input type="number" min={1} value={rate} onChange={(e) => setRate(e.target.value)} />
            </label>
            <label className="grid gap-1 text-sm font-medium">
              Presupuesto mensual (USD)
              <Input
                type="number"
                min={0}
                step="0.01"
                value={budget}
                onChange={(e) => setBudget(e.target.value)}
              />
            </label>
          </div>
          <label className="grid gap-1 text-sm font-medium">
            Expira el
            <Input type="date" value={expires} onChange={(e) => setExpires(e.target.value)} />
          </label>
          {error && (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          )}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              Cancelar
            </Button>
            <Button type="submit" disabled={pending || !name.trim() || scopes.length === 0}>
              {apiKey ? "Guardar cambios" : "Crear key"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
