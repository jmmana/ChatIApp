/* eslint-disable */
// Generado por sdks/scripts/generate.mjs desde docs/openapi/v1.json. No lo edites.

export const SPEC_VERSION = "0.1.0";

export interface ApiKeyCreate {
  allowed_origins?: Array<string>;
  allowed_roles?: Array<string>;
  datasources?: Array<string>;
  expires_at?: string | null;
  monthly_budget_usd?: number | string | null;
  name: string;
  rate_limit_per_minute?: number | null;
  scopes: Array<"chat" | "embed" | "sql:preview" | "semantic:read" | "semantic:write">;
}

export interface ApiKeyCreated {
  allowed_origins: Array<string>;
  allowed_roles: Array<string>;
  created_at: string;
  datasources: Array<string>;
  expires_at: string | null;
  id: string;
  last_used_at: string | null;
  monthly_budget_usd: string | null;
  name: string;
  prefix: string;
  rate_limit_per_minute: number | null;
  revoked_at: string | null;
  scopes: Array<string>;
  secret: string;
}

export interface ApiKeyOut {
  allowed_origins: Array<string>;
  allowed_roles: Array<string>;
  created_at: string;
  datasources: Array<string>;
  expires_at: string | null;
  id: string;
  last_used_at: string | null;
  monthly_budget_usd: string | null;
  name: string;
  prefix: string;
  rate_limit_per_minute: number | null;
  revoked_at: string | null;
  scopes: Array<string>;
}

/** Solo se cambian los campos enviados. */
export interface ApiKeyUpdate {
  allowed_origins?: Array<string> | null;
  allowed_roles?: Array<string> | null;
  datasources?: Array<string> | null;
  expires_at?: string | null;
  monthly_budget_usd?: number | string | null;
  name?: string | null;
  rate_limit_per_minute?: number | null;
  scopes?: Array<"chat" | "embed" | "sql:preview" | "semantic:read" | "semantic:write"> | null;
}

export interface AuditEntryOut {
  api_key_id: string | null;
  api_key_name: string | null;
  cost_usd: string | null;
  created_at: string;
  datasource: string | null;
  datasource_id: string | null;
  elapsed_ms: number | null;
  error_code: string | null;
  external_user_id: string | null;
  filters_applied: Record<string, unknown> | null;
  id: string;
  model: string | null;
  origin: string;
  plan: Record<string, unknown> | null;
  provider_kind: string | null;
  question: string | null;
  role: string | null;
  row_count: number | null;
  semantic_version: number | null;
  sql_candidate: string | null;
  sql_final: string | null;
  status: string;
  summary_table: string | null;
  tokens_in: number | null;
  tokens_out: number | null;
  user_email: string | null;
  user_id: string | null;
}

export interface AuditPage {
  items: Array<AuditEntryOut>;
  page: number;
  page_size: number;
  total: number;
}

export interface Body_import_semantic_api_v1_datasources__datasource_id__semantic_import_post {
  file: string;
}

export interface CancelOut {
  status: string;
  turn_id: string;
}

export interface ChatRequest {
  conversation_id?: string | null;
  datasource_id: string;
  message: string;
  provider_override?: string | null;
  user?: EndUser | null;
  view_as?: ViewAs | null;
}

export interface Column {
  description?: string | null;
  hidden?: boolean;
  name: string;
  role?: "time" | "measure" | "dimension" | "id" | "other";
  sample_values?: Array<string | number>;
  synonyms?: Array<string>;
  type?: string | null;
}

export interface ConversationDetail {
  created_at: string;
  datasource_id: string;
  id: string;
  messages: Array<MessageOut>;
  title: string;
}

export interface ConversationOut {
  created_at: string;
  datasource_id: string;
  id: string;
  title: string;
}

export interface ConversationUpdate {
  title: string;
}

export interface DatasourceCreate {
  dialect: "sqlite" | "postgres" | "mysql" | "tsql" | "oracle" | "snowflake" | "bigquery";
  execute?: boolean;
  max_rows?: number;
  name: string;
  privacy?: "schema" | "aggregates" | "samples";
  timeout_seconds?: number;
  url: string;
}

export interface DatasourceOut {
  dialect: string;
  execute: boolean;
  id: string;
  last_test_at?: string | null;
  last_test_error_kind?: "auth" | "network" | "driver_missing" | "unknown" | null;
  last_test_ok?: boolean | null;
  managed_by: string;
  max_rows: number;
  name: string;
  privacy: string;
  timeout_seconds: number;
  url: string;
}

/** Todos los campos son opcionales; ``url`` solo se reemplaza si se envía. */
export interface DatasourceUpdate {
  dialect?: "sqlite" | "postgres" | "mysql" | "tsql" | "oracle" | "snowflake" | "bigquery" | null;
  execute?: boolean | null;
  max_rows?: number | null;
  name?: string | null;
  privacy?: "schema" | "aggregates" | "samples" | null;
  timeout_seconds?: number | null;
  url?: string | null;
}

export interface EmbedSessionOut {
  expires_at: string;
  token: string;
}

export interface EmbedSessionRequest {
  datasource: string;
  origin: string;
  ttl_seconds?: number;
  user: EndUser;
}

/** Usuario final en cuyo nombre pregunta la app que integra. */
export interface EndUser {
  attributes?: Record<string, string | number | boolean | Array<string | number>>;
  id: string;
  role?: string | null;
}

export interface EvalProviderOut {
  id: string;
  kind: string;
  model: string;
  name: string;
}

export interface EvalRunCreate {
  max_calls?: number | null;
  provider_ids: Array<string>;
}

export interface EvalRunOut {
  cases_done: number;
  cases_total: number;
  created_at: string;
  error: string | null;
  id: string;
  providers: Array<EvalProviderOut>;
  report: Record<string, unknown> | null;
  status: "running" | "done" | "error";
}

/** Valor permitido (`select`) o alternativo (`url`) de un campo. */
export interface FieldOption {
  label: string;
  value: string;
}

export interface FilterApplied {
  source: string;
  text: string;
}

export interface FilterIn {
  field: string;
  op: string;
  value?: unknown;
}

export interface GrantIn {
  attributes?: Record<string, string | number | boolean | Array<string | number>>;
  datasource_id: string;
  role: string;
}

export interface GrantOut {
  attributes: Record<string, unknown>;
  datasource_id: string;
  role: string;
}

export interface GrantsIn {
  grants: Array<GrantIn>;
}

export interface GuardOut {
  allowed: boolean;
  sql: string | null;
  tables: Array<string>;
  violations: Array<ViolationOut>;
}

export interface HTTPValidationError {
  detail?: Array<ValidationError>;
}

export interface HealthResponse {
  status: string;
  version: string;
}

export interface ImportPreview {
  diff: Record<string, Array<Record<string, unknown>>>;
  model: Record<string, unknown>;
  warnings: Array<Record<string, string>>;
}

export interface IntrospectPreview {
  relationships: Array<Relationship>;
  schemas: Array<string>;
  tables: Array<Table>;
  warnings: Array<IssueOut>;
}

export interface IntrospectRequest {
  sample_values?: boolean;
  schemas?: Array<string> | null;
  table_pattern?: string | null;
}

export interface IssueOut {
  message: string;
  path: string;
}

export interface LoginRequest {
  email: string;
  password: string;
}

export interface MessageOut {
  content: string;
  created_at: string;
  events: Array<unknown> | null;
  id: string;
  role: string;
}

export interface MetricsOut {
  metrics: Array<SuggestedMetric>;
}

export interface ModelsResult {
  error_kind?: "auth" | "quota" | "model_not_found" | "timeout" | "network" | "provider_error" | null;
  message?: string | null;
  models?: Array<string>;
  supported: boolean;
}

export interface PeriodOut {
  end_exclusive: string;
  grain: string;
  is_current: boolean;
  label: string;
  start: string;
  text: string;
}

export interface PreviewOut {
  filters_applied: Array<FilterApplied>;
  guard: GuardOut;
  metric: string;
  period: PeriodOut | null;
  reason: string;
  role: string | null;
  sql: string;
  summary_table: string | null;
}

export interface PreviewRequest {
  dimensions?: Array<string>;
  filters?: Array<FilterIn>;
  granularity?: "day" | "week" | "month" | "quarter" | "year" | null;
  metric: string;
  period?: string | null;
  view_as?: ViewAs | null;
}

export interface ProbeResult {
  error_kind?: "auth" | "quota" | "model_not_found" | "timeout" | "network" | "provider_error" | null;
  latency_ms: number;
  message?: string | null;
  ok: boolean;
}

export interface ProviderCreate {
  config?: Record<string, unknown>;
  is_default?: boolean;
  kind: string;
  model: string;
  name: string;
  params?: Record<string, unknown>;
  secrets?: Record<string, string>;
  tasks?: Array<"planner" | "sql" | "answer" | "suggest">;
}

export interface ProviderField {
  default?: string | null;
  help?: string | null;
  label: string;
  name: string;
  options?: Array<FieldOption>;
  required?: boolean;
  type?: "text" | "secret" | "url" | "select" | "json";
}

export interface ProviderOut {
  config: Record<string, unknown>;
  id: string;
  is_default: boolean;
  kind: string;
  managed_by: string;
  model: string;
  name: string;
  params: Record<string, unknown>;
  secrets: Record<string, string>;
  tasks: Array<string>;
}

export interface ProviderSpec {
  category: "api" | "platform" | "chinese" | "local";
  docs_url: string;
  fields: Array<ProviderField>;
  kind: string;
  label: string;
  litellm_prefix: string;
  notes?: string | null;
  suggested_models?: Array<string>;
}

/** Configuración a probar sin guardarla. */
export interface ProviderTestIn {
  config?: Record<string, unknown>;
  kind: string;
  model: string;
  params?: Record<string, unknown>;
  secrets?: Record<string, string>;
}

export interface ProviderUpdate {
  config?: Record<string, unknown> | null;
  is_default?: boolean | null;
  model?: string | null;
  name?: string | null;
  params?: Record<string, unknown> | null;
  secrets?: Record<string, string> | null;
  tasks?: Array<"planner" | "sql" | "answer" | "suggest"> | null;
}

export interface PublishRequest {
  base_version: number;
  model: Record<string, unknown>;
}

export interface Relationship {
  from: string;
  to: string;
}

/** Tarea → id de proveedor, y cadena de respaldo en orden. */
export interface RoutingIn {
  fallback?: Array<string>;
  tasks?: Record<string, string>;
}

export interface SuggestRequest {
  tables?: Array<string> | null;
}

export interface SuggestedMetric {
  default_period: string | null;
  description: string | null;
  dimensions: Array<string>;
  label: string;
  name: string;
  requires_period: boolean;
}

/** Una propuesta: `path` es `tabla` o `tabla.columna`; `value` es texto o lista (sinónimos). */
export interface Suggestion {
  confidence: number;
  field: "description" | "synonyms" | "role";
  path: string;
  value: string | Array<string>;
}

export interface Table {
  columns?: Array<Column>;
  description?: string | null;
  name: string;
  primary_key?: Array<string>;
  synonyms?: Array<string>;
  time_column?: string | null;
}

export interface TestError {
  kind: "auth" | "network" | "driver_missing" | "unknown";
  message: string;
}

export interface TestResult {
  error?: TestError | null;
  latency_ms?: number | null;
  ok: boolean;
  server_version?: string | null;
}

export interface TokenResponse {
  access_token: string;
  expires_in: number;
  token_type?: string;
  user: UserInfo;
}

export interface UserCreate {
  email: string;
  is_admin?: boolean;
  password: string;
}

export interface UserInfo {
  email: string;
  id: string;
  is_admin: boolean;
}

export interface UserOut {
  email: string;
  grants: Array<GrantOut>;
  id: string;
  is_admin: boolean;
}

export interface UserUpdate {
  email?: string | null;
  is_admin?: boolean | null;
  password?: string | null;
}

export interface ValidateSqlOut {
  allowed: boolean;
  role: string | null;
  sql: string | null;
  tables: Array<string>;
  violations: Array<ViolationOut>;
}

export interface ValidateSqlRequest {
  sql: string;
  view_as?: ViewAs | null;
}

export interface ValidationError {
  ctx?: Record<string, unknown>;
  input?: unknown;
  loc: Array<string | number>;
  msg: string;
  type: string;
}

export interface VersionInfo {
  created_at: string;
  created_by: string | null;
  version: number;
}

export interface VersionOut {
  created_at: string;
  created_by: string | null;
  model: Record<string, unknown>;
  version: number;
}

/** Rol y atributos con los que un administrador prueba los permisos. */
export interface ViewAs {
  attributes?: Record<string, string | number | boolean | Array<string | number>>;
  role?: string | null;
}

export interface ViolationOut {
  code: string;
  message: string;
}
