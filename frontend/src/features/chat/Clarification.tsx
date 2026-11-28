import { useEffect, useRef, useState } from "react";
import type { KeyboardEvent } from "react";
import { Button } from "@/components/ui/button";

interface ClarificationProps {
  question: string;
  options: string[];
  onSelect: (option: string) => void;
}

/** Opciones de aclaración: un solo tab entra al grupo y las flechas mueven el foco. */
export function Clarification({ question, options, onSelect }: ClarificationProps) {
  const [active, setActive] = useState(0);
  const group = useRef<HTMLDivElement>(null);

  // El campo de pregunta se deshabilita durante el turno y pierde el foco: al aparecer las opciones
  // se lleva el foco a la primera, para poder elegir sin ratón.
  useEffect(() => {
    group.current?.querySelector("button")?.focus();
  }, []);

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    const buttons = Array.from(event.currentTarget.querySelectorAll("button"));
    if (buttons.length === 0) return;
    // En un Shadow DOM `document.activeElement` es el anfitrión: se pregunta a la raíz propia.
    const focused = (event.currentTarget.getRootNode() as Document | ShadowRoot).activeElement;
    const current = buttons.findIndex((el) => el === focused);
    const from = current === -1 ? active : current;
    let next: number;
    switch (event.key) {
      case "ArrowRight":
      case "ArrowDown":
        next = (from + 1) % buttons.length;
        break;
      case "ArrowLeft":
      case "ArrowUp":
        next = (from - 1 + buttons.length) % buttons.length;
        break;
      case "Home":
        next = 0;
        break;
      case "End":
        next = buttons.length - 1;
        break;
      default:
        return;
    }
    event.preventDefault();
    setActive(next);
    buttons[next]?.focus();
  }

  if (options.length === 0) return null;

  return (
    <div
      ref={group}
      role="group"
      aria-label={question || "Aclaración"}
      onKeyDown={onKeyDown}
      className="flex flex-wrap gap-2"
    >
      {options.map((option, index) => (
        <Button
          key={option}
          variant="outline"
          size="sm"
          tabIndex={index === active ? 0 : -1}
          onFocus={() => setActive(index)}
          onClick={() => onSelect(option)}
        >
          {option}
        </Button>
      ))}
    </div>
  );
}
