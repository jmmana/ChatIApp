export type ColumnRole = "time" | "measure" | "dimension" | "id" | "other";
export type Weekday =
  | "monday"
  | "tuesday"
  | "wednesday"
  | "thursday"
  | "friday"
  | "saturday"
  | "sunday";

export interface SemanticColumn {
  name: string;
  type?: string | null;
  description?: string | null;
  synonyms?: string[];
  role?: ColumnRole;
  hidden?: boolean;
  sample_values?: (string | number)[];
}

export interface SemanticTable {
  name: string;
  description?: string | null;
  synonyms?: string[];
  columns?: SemanticColumn[];
}

export interface SemanticRelationship {
  from: string;
  to: string;
}

export interface SemanticSettings {
  timezone?: string;
  currency?: string | null;
  locale?: string | null;
  fiscal_year_start_month?: number;
  week_starts_on?: Weekday;
}

export interface SemanticMetric {
  name: string;
  label: string;
  table: string;
  [other: string]: unknown;
}

export interface SemanticSummaryTable {
  table: string;
  metrics?: Record<string, string>;
  [other: string]: unknown;
}

export interface RoleFilter {
  table: string;
  condition: string;
}

export interface SecurityRole {
  name: string;
  description?: string | null;
  filters?: RoleFilter[];
  hidden_tables?: string[];
}

export interface SemanticSecurity {
  default_role?: string | null;
  roles?: SecurityRole[];
}

/** Modelo semántico (docs/MODELO_SEMANTICO.md). Los campos que la pantalla no edita se conservan. */
export interface SemanticModel {
  version: 1;
  name: string;
  business_context?: string;
  settings?: SemanticSettings;
  tables?: SemanticTable[];
  relationships?: SemanticRelationship[];
  metrics?: SemanticMetric[];
  summary_tables?: SemanticSummaryTable[];
  security?: SemanticSecurity;
  [other: string]: unknown;
}

export interface VersionInfo {
  version: number;
  created_by: string | null;
  created_at: string;
}

export interface SemanticVersion extends VersionInfo {
  model: SemanticModel;
}

export interface Datasource {
  id: string;
  name: string;
  dialect: string;
}

export interface ModelIssue {
  path: string;
  message: string;
}
