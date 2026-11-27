import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Users } from "lucide-react";
import { useState, type FormEvent } from "react";
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
import { Input } from "@/components/ui/input";
import { createUser, deleteUser, listUsers, putGrants, type ManagedUser, type UserInput } from "./api";
import { GrantsDialog } from "./GrantsDialog";

const errorText = (error: unknown) => (error instanceof Error ? error.message : null);

function CreateDialog({
  pending,
  error,
  onSubmit,
  onClose,
}: {
  pending: boolean;
  error: string | null;
  onSubmit: (input: UserInput) => void;
  onClose: () => void;
}) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [isAdmin, setIsAdmin] = useState(false);

  function submit(event: FormEvent) {
    event.preventDefault();
    onSubmit({ email: email.trim(), password, is_admin: isAdmin });
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Nuevo usuario</DialogTitle>
          <DialogDescription>
            Después de crearlo, asígnale un rol en cada fuente de datos.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="grid gap-3">
          <label className="grid gap-1 text-sm font-medium">
            Correo
            <Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
          </label>
          <label className="grid gap-1 text-sm font-medium">
            Contraseña
            <Input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={8}
              autoComplete="new-password"
            />
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={isAdmin} onChange={(e) => setIsAdmin(e.target.checked)} />
            Es administrador
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
            <Button type="submit" disabled={pending}>
              Crear usuario
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function UsersPage() {
  const queryClient = useQueryClient();
  const users = useQuery({ queryKey: ["users"], queryFn: listUsers });
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<ManagedUser | null>(null);
  const [removing, setRemoving] = useState<ManagedUser | null>(null);
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["users"] });

  const create = useMutation({
    mutationFn: createUser,
    onSuccess: () => {
      setCreating(false);
      void refresh();
    },
  });
  const grants = useMutation({
    mutationFn: ({ id, items }: { id: string; items: Parameters<typeof putGrants>[1] }) =>
      putGrants(id, items),
    onSuccess: () => {
      setEditing(null);
      void refresh();
    },
  });
  const remove = useMutation({
    mutationFn: (id: string) => deleteUser(id),
    onSuccess: () => {
      setRemoving(null);
      void refresh();
    },
  });

  return (
    <section className="mx-auto grid max-w-6xl gap-6">
      <div className="flex items-start justify-between gap-4">
        <div className="grid gap-1">
          <h1 className="flex items-center gap-2 text-2xl font-semibold tracking-tight">
            <Users className="size-6" aria-hidden /> Usuarios
          </h1>
          <p className="text-muted-foreground">
            Personas con acceso, su rol en cada fuente y los atributos de sus filtros.
          </p>
        </div>
        <Button
          onClick={() => {
            create.reset();
            setCreating(true);
          }}
        >
          <Plus aria-hidden /> Nuevo usuario
        </Button>
      </div>

      {users.isError && (
        <p role="alert" className="text-sm text-destructive">
          {errorText(users.error) ?? "No se pudieron cargar los usuarios."}
        </p>
      )}
      {users.data && users.data.length > 0 && (
        <div className="overflow-x-auto rounded-lg border bg-card">
          <table className="w-full text-left text-sm">
            <thead className="border-b text-xs text-muted-foreground">
              <tr>
                {["Correo", "Permisos", "Acciones"].map((h) => (
                  <th key={h} className="px-3 py-2 font-medium">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {users.data.map((user) => (
                <tr key={user.id} className="border-b align-top last:border-0">
                  <td className="px-3 py-2 font-medium">
                    {user.email} {user.is_admin && <Badge>Administrador</Badge>}
                  </td>
                  <td className="px-3 py-2">
                    {user.grants.length === 0 ? "Sin acceso a fuentes" : `${user.grants.length} fuente(s)`}
                  </td>
                  <td className="px-3 py-2">
                    <div className="flex gap-1">
                      <Button
                        variant="ghost"
                        size="sm"
                        aria-label={`Permisos de ${user.email}`}
                        onClick={() => {
                          grants.reset();
                          setEditing(user);
                        }}
                      >
                        Permisos
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        aria-label={`Eliminar ${user.email}`}
                        onClick={() => {
                          remove.reset();
                          setRemoving(user);
                        }}
                      >
                        Eliminar
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {creating && (
        <CreateDialog
          pending={create.isPending}
          error={errorText(create.error)}
          onSubmit={(input) => create.mutate(input)}
          onClose={() => setCreating(false)}
        />
      )}
      {editing && (
        <GrantsDialog
          key={editing.id}
          user={editing}
          pending={grants.isPending}
          error={errorText(grants.error)}
          onSubmit={(items) => grants.mutate({ id: editing.id, items })}
          onClose={() => setEditing(null)}
        />
      )}
      {removing && (
        <Dialog open onOpenChange={(open) => !open && setRemoving(null)}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Eliminar usuario</DialogTitle>
              <DialogDescription>
                ¿Eliminar a {removing.email}? Perderá el acceso y todos sus permisos.
              </DialogDescription>
            </DialogHeader>
            {remove.error && (
              <p role="alert" className="text-sm text-destructive">
                {errorText(remove.error)}
              </p>
            )}
            <DialogFooter>
              <Button variant="outline" onClick={() => setRemoving(null)}>
                Cancelar
              </Button>
              <Button
                variant="destructive"
                disabled={remove.isPending}
                onClick={() => remove.mutate(removing.id)}
              >
                Confirmar eliminación
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}
    </section>
  );
}
