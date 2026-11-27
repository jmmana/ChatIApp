import type { SemanticModel } from "../types";

export interface DiffAdded {
  path: string;
  kind: string;
}

export interface DiffChanged {
  path: string;
  field: string;
  before: unknown;
  after: unknown;
}

export interface DiffSuggestion {
  path: string;
  field: string;
  current: unknown;
  suggested: unknown;
}

export interface ImportDiff {
  added: DiffAdded[];
  changed: DiffChanged[];
  missing: DiffAdded[];
  suggestions: DiffSuggestion[];
}

export interface ImportWarning {
  path: string;
  message: string;
}

/** Vista previa de `POST /semantic/import`: el modelo fusionado y lo que cambiaría. */
export interface ImportPreview {
  model: SemanticModel;
  diff: ImportDiff;
  warnings: ImportWarning[];
}

/** Vista previa de `POST /semantic/introspect` (sin diff). */
export interface IntrospectResult {
  schemas: string[];
  tables: NonNullable<SemanticModel["tables"]>;
  relationships: NonNullable<SemanticModel["relationships"]>;
  warnings: ImportWarning[];
}
