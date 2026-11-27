import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import {
  createProvider,
  listModels,
  testSavedProvider,
  testUnsavedProvider,
  updateProvider,
  type CatalogEntry,
  type ProbeResult,
  type Provider,
  type ProviderInput,
} from "./api";
import { ProviderForm } from "./ProviderForm";

interface Props {
  spec: CatalogEntry;
  /** Si viene, edita ese proveedor; si no, crea uno del tipo de `spec`. */
  provider?: Provider;
  onTested: (id: string, result: ProbeResult) => void;
  onClose: () => void;
}

/** Panel lateral con el formulario generado desde el catálogo. */
export function ProviderSheet({ spec, provider, onTested, onClose }: Props) {
  const queryClient = useQueryClient();
  const [testResult, setTestResult] = useState<ProbeResult | null>(null);

  const save = useMutation({
    mutationFn: (input: ProviderInput) =>
      provider ? updateProvider(provider.id, input) : createProvider(spec.kind, input),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["providers"] });
      onClose();
    },
  });

  const test = useMutation({
    // Al editar se prueba lo guardado (los secretos no vuelven al navegador); al crear, lo escrito.
    mutationFn: (input: ProviderInput) =>
      provider
        ? testSavedProvider(provider.id)
        : testUnsavedProvider({
            kind: spec.kind,
            model: input.model,
            config: input.config,
            secrets: input.secrets,
          }),
    onSuccess: (result) => {
      setTestResult(result);
      if (provider) onTested(provider.id, result);
    },
    onError: (error) =>
      setTestResult({ ok: false, latency_ms: 0, error_kind: "provider_error", message: error.message }),
  });

  return (
    <Sheet open onOpenChange={(open) => !open && onClose()}>
      <SheetContent className="w-full max-w-lg overflow-y-auto">
        <SheetHeader>
          <SheetTitle>{provider ? `Editar ${provider.name}` : `Agregar ${spec.label}`}</SheetTitle>
          <SheetDescription>
            Los secretos se guardan cifrados y nunca se vuelven a mostrar completos.
          </SheetDescription>
        </SheetHeader>
        <ProviderForm
          spec={spec}
          provider={provider}
          saving={save.isPending}
          error={save.error?.message ?? null}
          testing={test.isPending}
          testResult={testResult}
          onSubmit={(input) => save.mutate(input)}
          onTest={(input) => test.mutate(input)}
          onLoadModels={provider ? () => listModels(provider.id) : undefined}
          onCancel={onClose}
        />
      </SheetContent>
    </Sheet>
  );
}
