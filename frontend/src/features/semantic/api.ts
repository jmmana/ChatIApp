import { ApiError, apiRequest } from "@/lib/api";
import type { Datasource, ModelIssue, SemanticModel, SemanticVersion, VersionInfo } from "./types";

export function listDatasources(): Promise<Datasource[]> {
  return apiRequest<Datasource[]>("/datasources");
}

/** Versión vigente; `null` si la fuente aún no tiene modelo. */
export async function getSemantic(datasourceId: string): Promise<SemanticVersion | null> {
  try {
    return await apiRequest<SemanticVersion>(`/datasources/${datasourceId}/semantic`);
  } catch (error) {
    if (error instanceof ApiError && error.code === "semantic_model_not_found") return null;
    throw error;
  }
}

export function listVersions(datasourceId: string): Promise<VersionInfo[]> {
  return apiRequest<VersionInfo[]>(`/datasources/${datasourceId}/semantic/versions`);
}

export function publishSemantic(
  datasourceId: string,
  baseVersion: number,
  model: SemanticModel,
): Promise<SemanticVersion> {
  return apiRequest<SemanticVersion>(`/datasources/${datasourceId}/semantic`, {
    method: "PUT",
    body: { base_version: baseVersion, model },
  });
}

/** Errores de validación de un 422 (`error.details.errors`). */
export function issuesFrom(error: ApiError): ModelIssue[] {
  const errors = error.details.errors;
  return Array.isArray(errors) ? (errors as ModelIssue[]) : [];
}
