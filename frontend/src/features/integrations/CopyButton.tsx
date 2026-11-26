import { Check, Copy } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";

export function CopyButton({ text, label }: { text: string; label: string }) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }

  return (
    <Button type="button" variant="outline" size="sm" onClick={() => void copy()}>
      {copied ? <Check aria-hidden /> : <Copy aria-hidden />}
      {copied ? "Copiado" : label}
    </Button>
  );
}
