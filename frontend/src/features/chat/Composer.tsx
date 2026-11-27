import { useEffect, useState } from "react";
import type { KeyboardEvent } from "react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

interface Props {
  busy: boolean;
  disabled?: boolean;
  onSend: (message: string) => void;
  onCancel: () => void;
}

export function Composer({ busy, disabled = false, onSend, onCancel }: Props) {
  const [value, setValue] = useState("");

  // El campo está deshabilitado durante el turno y no recibe teclas: Esc se escucha en el documento.
  useEffect(() => {
    if (!busy) return;
    function onKey(event: globalThis.KeyboardEvent) {
      if (event.key === "Escape") onCancel();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [busy, onCancel]);

  function submit() {
    const message = value.trim();
    if (!message || busy || disabled) return;
    onSend(message);
    setValue("");
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      submit();
    }
  }

  return (
    <form
      className="flex items-end gap-2 border-t bg-background p-4"
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      <Textarea
        aria-label="Pregunta"
        placeholder="Pregunta sobre tus datos…"
        rows={1}
        className="min-h-10 flex-1 resize-none"
        value={value}
        disabled={busy || disabled}
        onChange={(event) => setValue(event.target.value)}
        onKeyDown={onKeyDown}
      />
      {busy ? (
        <Button type="button" variant="outline" onClick={onCancel}>
          Cancelar
        </Button>
      ) : (
        <Button type="submit" disabled={disabled || !value.trim()}>
          Enviar
        </Button>
      )}
    </form>
  );
}
