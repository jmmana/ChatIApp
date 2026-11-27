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

export type MetricFormat = "currency" | "integer" | "number" | "percent";
export type Grain = "day" | "week" | "month" | "quarter" | "year";

export interface SemanticMetric {
  name: string;
  label: string;
  description?: string | null;
  synonyms?: string[];
  table: string;
  expression: string;
  time_column: string;
  filters?: string[];
  dimensions?: string[];
  format?: MetricFormat | null;
  requires_period?: boolean;
  default_period?: string | null;
  additive?: boolean;
}

export interface SummaryTable {
  table: string;
  grain: Grain;
  time_column: string;
  includes_current_period?: boolean;
  metrics?: Record<string, string>;
  dimensions?: Record<string, string>;
}

export interface PreviewFilter {
  field: string;
  op: string;
  value: unknown;
}

export interface PreviewRequest {
  metric: string;
  period?: string;
  dimensions?: string[];
  filters?: PreviewFilter[];
}

export interface PreviewResult {
  sql: string;
  metric: string;
  role: string | null;
  summary_table: string | null;
  reason: string;
  period: { text: string; label: string; start: string; end_exclusive: string } | null;
  filters_applied: { source: string; text: string }[];
  guard: {
    allowed: boolean;
    sql: string | null;
    tables: string[];
    violations: { code: string; message: string }[];
  };
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
  summary_tables?: SummaryTable[];
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
