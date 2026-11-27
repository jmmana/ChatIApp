import { CheckCircle2, XCircle } from "lucide-react";
import type { ProbeResult } from "./api";
import { ERROR_HELP, formatLatency } from "./catalog";

export function TestResultView({ result }: { result: ProbeResult }) {
  if (result.ok) {
    return (
      <div role="status" className="flex items-start gap-2 text-sm">
        <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-emerald-600" aria-hidden />
        <p>
          <span className="font-medium">Conexión exitosa.</span> Latencia:{" "}
          {formatLatency(result.latency_ms)}
        </p>
      </div>
    );
  }
  const help = ERROR_HELP[result.error_kind ?? "provider_error"];
  return (
    <div role="alert" className="flex items-start gap-2 text-sm">
      <XCircle className="mt-0.5 size-4 shrink-0 text-destructive" aria-hidden />
      <div className="grid gap-1">
        <p className="font-medium">{help.title}</p>
        {result.message && <p className="text-muted-foreground">{result.message}</p>}
        <p>
          <span className="font-medium">Qué hacer:</span> {help.action}
        </p>
      </div>
    </div>
  );
}
