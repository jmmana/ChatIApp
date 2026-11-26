import { CheckCircle2, XCircle } from "lucide-react";
import { ERROR_HELP } from "./catalog";
import type { TestResult } from "./api";

export function TestResultView({ result }: { result: TestResult }) {
  if (result.ok) {
    return (
      <div role="status" className="flex items-start gap-2 text-sm">
        <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-emerald-600" aria-hidden />
        <p>
          <span className="font-medium">Conexión exitosa.</span> Latencia: {result.latency_ms ?? "?"}{" "}
          ms · Versión del servidor: {result.server_version ?? "desconocida"}
        </p>
      </div>
    );
  }
  const kind = result.error?.kind ?? "unknown";
  const help = ERROR_HELP[kind];
  return (
    <div role="alert" className="flex items-start gap-2 text-sm">
      <XCircle className="mt-0.5 size-4 shrink-0 text-destructive" aria-hidden />
      <div className="grid gap-1">
        <p className="font-medium">{help.title}</p>
        {result.error && <p className="text-muted-foreground">{result.error.message}</p>}
        <p>
          <span className="font-medium">Qué hacer:</span> {help.action}
        </p>
      </div>
    </div>
  );
}
