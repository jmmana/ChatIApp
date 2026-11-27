import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Pencil, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import type { FormEvent } from "react";
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
import { cn } from "@/lib/utils";
import { deleteConversation, listConversations, renameConversation } from "./api";
import type { ConversationSummary } from "./api";
import { groupConversations } from "./grouping";
import { CONVERSATIONS_KEY } from "./queryKeys";

interface Props {
  activeId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  /** Se llama tras borrar, para que el chat deje de mostrar la conversación eliminada. */
  onDeleted: (id: string) => void;
  /** `sheet`: dentro del menú de pantallas estrechas (siempre visible, a todo el ancho). */
  variant?: "fixed" | "sheet";
}

export function Sidebar({ activeId, onSelect, onNew, onDeleted, variant = "fixed" }: Props) {
  const client = useQueryClient();
  const conversations = useQuery({ queryKey: CONVERSATIONS_KEY, queryFn: listConversations });
  const [renaming, setRenaming] = useState<ConversationSummary | null>(null);
  const [title, setTitle] = useState("");
  const [deleting, setDeleting] = useState<ConversationSummary | null>(null);

  const rename = useMutation({
    mutationFn: (input: { id: string; title: string }) => renameConversation(input.id, input.title),
    onSuccess: () => {
      setRenaming(null);
      return client.invalidateQueries({ queryKey: CONVERSATIONS_KEY });
    },
  });
  const remove = useMutation({
    mutationFn: (id: string) => deleteConversation(id),
    onSuccess: (_data, id) => {
      setDeleting(null);
      onDeleted(id);
      return client.invalidateQueries({ queryKey: CONVERSATIONS_KEY });
    },
  });

  const groups = groupConversations(conversations.data ?? []);

  function submitRename(event: FormEvent) {
    event.preventDefault();
    const next = title.trim();
    if (renaming && next) rename.mutate({ id: renaming.id, title: next });
  }

  return (
    <aside
      aria-label="Conversaciones"
      className={cn(
        "flex-col gap-3 overflow-y-auto bg-card p-3",
        variant === "fixed" ? "hidden w-60 shrink-0 border-r lg:flex" : "flex min-h-0 flex-1",
      )}
    >
      <Button variant="outline" size="sm" className="justify-start" onClick={onNew}>
        <Plus aria-hidden /> Nueva conversación
        <kbd className="ml-auto text-xs text-muted-foreground">Ctrl/⌘+K</kbd>
      </Button>

      {conversations.isError && (
        <p role="alert" className="text-sm text-destructive">
          No se pudieron cargar las conversaciones.
        </p>
      )}
      {conversations.isSuccess && groups.length === 0 && (
        <p className="text-sm text-muted-foreground">Aún no hay conversaciones.</p>
      )}

      {groups.map((group) => (
        <section key={group.label} aria-label={group.label} className="flex flex-col gap-1">
          <h2 className="px-2 text-xs font-medium uppercase text-muted-foreground">
            {group.label}
          </h2>
          <ul className="flex flex-col gap-0.5">
            {group.items.map((item) => (
              <li
                key={item.id}
                className={cn(
                  "group flex items-center rounded-md hover:bg-muted",
                  item.id === activeId && "bg-accent text-accent-foreground",
                )}
              >
                <button
                  type="button"
                  className="min-w-0 flex-1 truncate px-2 py-1.5 text-left text-sm"
                  aria-current={item.id === activeId ? "true" : undefined}
                  onClick={() => onSelect(item.id)}
                >
                  {item.title}
                </button>
                <Button
                  variant="ghost"
                  size="icon"
                  className="size-7 shrink-0"
                  aria-label={`Renombrar ${item.title}`}
                  onClick={() => {
                    setTitle(item.title);
                    rename.reset();
                    setRenaming(item);
                  }}
                >
                  <Pencil />
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  className="size-7 shrink-0"
                  aria-label={`Eliminar ${item.title}`}
                  onClick={() => {
                    remove.reset();
                    setDeleting(item);
                  }}
                >
                  <Trash2 />
                </Button>
              </li>
            ))}
          </ul>
        </section>
      ))}

      <Dialog open={renaming !== null} onOpenChange={(open) => !open && setRenaming(null)}>
        <DialogContent>
          <form onSubmit={submitRename} className="grid gap-4">
            <DialogHeader>
              <DialogTitle>Renombrar conversación</DialogTitle>
              <DialogDescription>Elige un título que te ayude a encontrarla.</DialogDescription>
            </DialogHeader>
            <Input
              aria-label="Título"
              value={title}
              maxLength={200}
              onChange={(event) => setTitle(event.target.value)}
            />
            {rename.isError && (
              <p role="alert" className="text-sm text-destructive">
                {rename.error.message}
              </p>
            )}
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setRenaming(null)}>
                Cancelar
              </Button>
              <Button type="submit" disabled={!title.trim() || rename.isPending}>
                Guardar
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog open={deleting !== null} onOpenChange={(open) => !open && setDeleting(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Eliminar conversación</DialogTitle>
            <DialogDescription>
              Se eliminará «{deleting?.title}» con todos sus mensajes. No se puede deshacer.
            </DialogDescription>
          </DialogHeader>
          {remove.isError && (
            <p role="alert" className="text-sm text-destructive">
              {remove.error.message}
            </p>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleting(null)}>
              Cancelar
            </Button>
            <Button
              variant="destructive"
              disabled={remove.isPending}
              onClick={() => deleting && remove.mutate(deleting.id)}
            >
              Eliminar
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </aside>
  );
}
