import { Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/utils";
import { describedBy, hasErrorsUnder, type FieldErrors } from "../errors";
import { FieldError } from "../FieldError";
import { selectClass } from "../styles";
import type { RoleFilter, SecurityRole, SemanticModel, SemanticSecurity } from "../types";
import { conditionProblem, summaryWarnings } from "./rules";
import { ViewAsPanel } from "./ViewAsPanel";

interface Props {
  datasourceId: string;
  model: SemanticModel;
  errors: FieldErrors;
  dirty: boolean;
  onChange: (model: SemanticModel) => void;
}

export function SecurityTab({ datasourceId, model, errors, dirty, onChange }: Props) {
  const security = model.security ?? {};
  const roles = security.roles ?? [];
  const tableNames = (model.tables ?? []).map((table) => table.name);
  const [selected, setSelected] = useState(0);
  const [newRole, setNewRole] = useState("");

  const index = selected < roles.length ? selected : 0;
  const role = roles[index] as SecurityRole | undefined;
  const at = `security.roles[${index}]`;
  const warnings = summaryWarnings(model);

  function patchSecurity(patch: Partial<SemanticSecurity>) {
    onChange({ ...model, security: { ...security, ...patch } });
  }

  function patchRole(patch: Partial<SecurityRole>) {
    patchSecurity({ roles: roles.map((r, i) => (i === index ? { ...r, ...patch } : r)) });
  }

  function rename(name: string) {
    const renamesDefault = role && security.default_role === role.name;
    patchSecurity({
      roles: roles.map((r, i) => (i === index ? { ...r, name } : r)),
      ...(renamesDefault ? { default_role: name } : {}),
    });
  }

  function addRole() {
    const name = newRole.trim();
    if (!name || roles.some((r) => r.name === name)) return;
    patchSecurity({ roles: [...roles, { name, filters: [], hidden_tables: [] }] });
    setSelected(roles.length);
    setNewRole("");
  }

  function removeRole() {
    if (!role) return;
    patchSecurity({
      roles: roles.filter((_, i) => i !== index),
      default_role: security.default_role === role.name ? null : security.default_role,
    });
    setSelected(0);
  }

  function patchFilter(filterIndex: number, patch: Partial<RoleFilter>) {
    patchRole({
      filters: (role?.filters ?? []).map((f, i) => (i === filterIndex ? { ...f, ...patch } : f)),
    });
  }

  function toggleHidden(table: string, hidden: boolean) {
    const current = role?.hidden_tables ?? [];
    patchRole({
      hidden_tables: hidden ? [...current, table] : current.filter((name) => name !== table),
    });
  }

  const duplicate = newRole.trim() !== "" && roles.some((r) => r.name === newRole.trim());

  return (
    <div className="flex flex-col gap-6">
      {warnings.length > 0 && (
        <div
          role="alert"
          aria-label="Advertencias de seguridad"
          className="flex flex-col gap-1 rounded-md border border-destructive p-3 text-sm"
        >
          <p className="font-medium">Tablas resumidas sin filtro</p>
          <ul className="list-disc pl-5">
            {warnings.map((warning) => (
              <li key={`${warning.role}|${warning.table}|${warning.summary}`}>
                «{warning.table}» está filtrada para el rol «{warning.role}», pero su tabla
                resumida «{warning.summary}» no tiene filtro para ese rol: ese rol no usará la
                resumida, o verá filas ajenas si se agrega sin filtro.
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="flex flex-col gap-1 md:max-w-sm">
        <label htmlFor="rol-por-defecto" className="text-sm font-medium">
          Rol por defecto
        </label>
        <select
          id="rol-por-defecto"
          className={selectClass}
          value={security.default_role ?? ""}
          aria-describedby={describedBy(errors, "security.default_role")}
          onChange={(event) => patchSecurity({ default_role: event.target.value || null })}
        >
          <option value="">(ninguno)</option>
          {roles.map((item) => (
            <option key={item.name} value={item.name}>
              {item.name}
            </option>
          ))}
        </select>
        <FieldError errors={errors} path="security.default_role" />
      </div>

      <div className="grid gap-6 md:grid-cols-[16rem_1fr]">
        <aside className="flex flex-col gap-3">
          <ul aria-label="Roles" className="flex flex-col gap-1">
            {roles.map((item, itemIndex) => (
              <li key={itemIndex}>
                <button
                  type="button"
                  aria-current={itemIndex === index ? "true" : undefined}
                  onClick={() => setSelected(itemIndex)}
                  className={cn(
                    "flex w-full items-center justify-between gap-2 rounded-md px-3 py-2 text-left text-sm",
                    itemIndex === index ? "bg-accent text-accent-foreground" : "hover:bg-muted",
                    hasErrorsUnder(errors, `security.roles[${itemIndex}]`) &&
                      "ring-1 ring-destructive",
                  )}
                >
                  <span className="truncate font-medium">{item.name}</span>
                  <span className="shrink-0 text-xs text-muted-foreground">
                    {(item.filters ?? []).length} filtros
                  </span>
                </button>
              </li>
            ))}
            {roles.length === 0 && (
              <li className="px-3 py-2 text-sm text-muted-foreground">
                Sin roles: todos ven todas las filas.
              </li>
            )}
          </ul>
          <form
            className="flex gap-2"
            onSubmit={(event) => {
              event.preventDefault();
              addRole();
            }}
          >
            <Input
              aria-label="Nombre del rol nuevo"
              placeholder="Nombre del rol"
              value={newRole}
              onChange={(event) => setNewRole(event.target.value)}
            />
            <Button type="submit" variant="outline" disabled={newRole.trim() === "" || duplicate}>
              <Plus aria-hidden /> Rol
            </Button>
          </form>
          {duplicate && <p className="text-xs text-destructive">Ya existe un rol con ese nombre.</p>}
        </aside>

        {role && (
          <section aria-label={`Rol ${role.name}`} className="flex min-w-0 flex-col gap-4">
            <div className="flex items-end gap-2">
              <div className="flex flex-1 flex-col gap-1">
                <label htmlFor="rol-nombre" className="text-sm font-medium">
                  Nombre del rol
                </label>
                <Input
                  id="rol-nombre"
                  value={role.name}
                  aria-describedby={describedBy(errors, `${at}.name`)}
                  onChange={(event) => rename(event.target.value)}
                />
                <FieldError errors={errors} path={`${at}.name`} />
              </div>
              <Button type="button" variant="outline" onClick={removeRole}>
                <Trash2 aria-hidden /> Quitar rol
              </Button>
            </div>

            <fieldset className="flex flex-col gap-3">
              <legend className="text-sm font-medium">Filtros por tabla</legend>
              {(role.filters ?? []).map((filter, filterIndex) => {
                const path = `${at}.filters[${filterIndex}]`;
                const problem = conditionProblem(filter.condition);
                return (
                  <div key={filterIndex} className="flex flex-col gap-1 rounded-lg border p-3">
                    <div className="grid gap-2 md:grid-cols-[12rem_1fr_auto]">
                      <select
                        aria-label={`Tabla del filtro ${filterIndex + 1}`}
                        className={selectClass}
                        value={filter.table}
                        aria-describedby={describedBy(errors, `${path}.table`)}
                        onChange={(event) => patchFilter(filterIndex, { table: event.target.value })}
                      >
                        {!tableNames.includes(filter.table) && (
                          <option value={filter.table}>{filter.table || "(elige una tabla)"}</option>
                        )}
                        {tableNames.map((name) => (
                          <option key={name} value={name}>
                            {name}
                          </option>
                        ))}
                      </select>
                      <Input
                        aria-label={`Condición del filtro ${filterIndex + 1}`}
                        className="font-mono"
                        placeholder="sucursal_id IN ({user.sucursales})"
                        value={filter.condition}
                        aria-invalid={problem !== null}
                        aria-describedby={
                          describedBy(errors, `${path}.condition`) ?? `condicion-${filterIndex}`
                        }
                        onChange={(event) =>
                          patchFilter(filterIndex, { condition: event.target.value })
                        }
                      />
                      <Button
                        type="button"
                        variant="outline"
                        aria-label={`Quitar filtro ${filterIndex + 1}`}
                        onClick={() =>
                          patchRole({ filters: (role.filters ?? []).filter((_, i) => i !== filterIndex) })
                        }
                      >
                        <Trash2 aria-hidden />
                      </Button>
                    </div>
                    <p
                      id={`condicion-${filterIndex}`}
                      className={cn("text-xs", problem ? "text-destructive" : "text-muted-foreground")}
                    >
                      {problem ?? "Condición válida. Se comprueba el SQL completo al publicar."}
                    </p>
                    <FieldError errors={errors} path={`${path}.table`} />
                    <FieldError errors={errors} path={`${path}.condition`} />
                  </div>
                );
              })}
              <div>
                <Button
                  type="button"
                  variant="outline"
                  disabled={tableNames.length === 0}
                  onClick={() =>
                    patchRole({
                      filters: [...(role.filters ?? []), { table: tableNames[0], condition: "" }],
                    })
                  }
                >
                  <Plus aria-hidden /> Agregar filtro
                </Button>
              </div>
            </fieldset>

            <fieldset className="flex flex-col gap-2">
              <legend className="text-sm font-medium">Tablas ocultas</legend>
              {tableNames.map((name) => (
                <label key={name} className="flex items-center gap-2 text-sm">
                  <Switch
                    aria-label={`Ocultar tabla ${name}`}
                    checked={(role.hidden_tables ?? []).includes(name)}
                    onCheckedChange={(hidden) => toggleHidden(name, hidden)}
                  />
                  {name}
                </label>
              ))}
            </fieldset>
          </section>
        )}
      </div>

      <ViewAsPanel datasourceId={datasourceId} model={model} dirty={dirty} />
    </div>
  );
}
