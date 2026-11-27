import { apiRequest } from "@/lib/api";
import type { ImportPreview, IntrospectResult } from "./types";

export function previewImport(datasourceId: string, file: File): Promise<ImportPreview> {
  const body = new FormData();
  body.append("file", file);
  return apiRequest<ImportPreview>(`/datasources/${datasourceId}/semantic/import`, {
    method: "POST",
    body,
  });
}

/**
 * Lee la base conectada y la pasa por la misma vista previa que un archivo: la lectura se
 * reenvía como modelo `.json` a `/import`, que calcula el diff contra el modelo vigente.
 */
export async function previewIntrospection(
  datasourceId: string,
  name: string,
): Promise<ImportPreview> {
  const found = await apiRequest<IntrospectResult>(
    `/datasources/${datasourceId}/semantic/introspect`,
    { method: "POST", body: {} },
  );
  const model = { version: 1, name, tables: found.tables, relationships: found.relationships };
  const file = new File([JSON.stringify(model)], "base-conectada.json", {
    type: "application/json",
  });
  const preview = await previewImport(datasourceId, file);
  return { ...preview, warnings: [...found.warnings, ...preview.warnings] };
}
