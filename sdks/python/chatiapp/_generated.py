"""Modelos generados por sdks/scripts/generate.mjs desde docs/openapi/v1.json. No lo edites."""

# ruff: noqa
# fmt: off
from __future__ import annotations

import datetime as _dt
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

SPEC_VERSION = "0.1.0"


class ApiKeyCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    allowed_origins: list[str] = Field(default_factory=lambda: [])
    allowed_roles: list[str] = Field(default_factory=lambda: [])
    datasources: list[str] = Field(default_factory=lambda: [])
    expires_at: _dt.datetime | None = None
    monthly_budget_usd: float | str | None = None
    name: str
    rate_limit_per_minute: int | None = None
    scopes: list[Literal["chat", "embed", "sql:preview", "semantic:read", "semantic:write"]]


class ApiKeyCreated(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    allowed_origins: list[str]
    allowed_roles: list[str]
    created_at: _dt.datetime
    datasources: list[str]
    expires_at: _dt.datetime | None
    id: str
    last_used_at: _dt.datetime | None
    monthly_budget_usd: str | None
    name: str
    prefix: str
    rate_limit_per_minute: int | None
    revoked_at: _dt.datetime | None
    scopes: list[str]
    secret: str


class ApiKeyOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    allowed_origins: list[str]
    allowed_roles: list[str]
    created_at: _dt.datetime
    datasources: list[str]
    expires_at: _dt.datetime | None
    id: str
    last_used_at: _dt.datetime | None
    monthly_budget_usd: str | None
    name: str
    prefix: str
    rate_limit_per_minute: int | None
    revoked_at: _dt.datetime | None
    scopes: list[str]


class ApiKeyUpdate(BaseModel):
    """Solo se cambian los campos enviados."""

    model_config = ConfigDict(populate_by_name=True)

    allowed_origins: list[str] | None = None
    allowed_roles: list[str] | None = None
    datasources: list[str] | None = None
    expires_at: _dt.datetime | None = None
    monthly_budget_usd: float | str | None = None
    name: str | None = None
    rate_limit_per_minute: int | None = None
    scopes: list[Literal["chat", "embed", "sql:preview", "semantic:read", "semantic:write"]] | None = None


class AuditEntryOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    api_key_id: str | None
    api_key_name: str | None
    cost_usd: str | None
    created_at: _dt.datetime
    datasource: str | None
    datasource_id: str | None
    elapsed_ms: int | None
    error_code: str | None
    external_user_id: str | None
    filters_applied: dict[str, Any] | None
    id: str
    model: str | None
    origin: str
    plan: dict[str, Any] | None
    provider_kind: str | None
    question: str | None
    role: str | None
    row_count: int | None
    semantic_version: int | None
    sql_candidate: str | None
    sql_final: str | None
    status: str
    summary_table: str | None
    tokens_in: int | None
    tokens_out: int | None
    user_email: str | None
    user_id: str | None


class AuditPage(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    items: list[AuditEntryOut]
    page: int
    page_size: int
    total: int


class Body_import_semantic_api_v1_datasources__datasource_id__semantic_import_post(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    file: str


class CancelOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    status: str
    turn_id: str


class EndUser(BaseModel):
    """Usuario final en cuyo nombre pregunta la app que integra."""

    model_config = ConfigDict(populate_by_name=True)

    attributes: dict[str, str | int | float | bool | list[str | int | float]] = Field(default_factory=lambda: {})
    id: str
    role: str | None = None


class ViewAs(BaseModel):
    """Rol y atributos con los que un administrador prueba los permisos."""

    model_config = ConfigDict(populate_by_name=True)

    attributes: dict[str, str | int | float | bool | list[str | int | float]] = Field(default_factory=lambda: {})
    role: str | None = None


class ChatRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    conversation_id: str | None = None
    datasource_id: str
    message: str
    provider_override: str | None = None
    user: EndUser | None = None
    view_as: ViewAs | None = None


class Column(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    description: str | None = None
    hidden: bool = False
    name: str
    role: Literal["time", "measure", "dimension", "id", "other"] = "other"
    sample_values: list[str | int | float] = Field(default_factory=lambda: [])
    synonyms: list[str] = Field(default_factory=lambda: [])
    type: str | None = None


class MessageOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    content: str
    created_at: _dt.datetime
    events: list[Any] | None
    id: str
    role: str


class ConversationDetail(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    created_at: _dt.datetime
    datasource_id: str
    id: str
    messages: list[MessageOut]
    title: str


class ConversationOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    created_at: _dt.datetime
    datasource_id: str
    id: str
    title: str


class ConversationUpdate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    title: str


class DatasourceCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    dialect: Literal["sqlite", "postgres", "mysql", "tsql", "oracle", "snowflake", "bigquery"]
    execute: bool = False
    max_rows: int = 1000
    name: str
    privacy: Literal["schema", "aggregates", "samples"] = "schema"
    timeout_seconds: int = 30
    url: str


class DatasourceOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    dialect: str
    execute: bool
    id: str
    last_test_at: _dt.datetime | None = None
    last_test_error_kind: Literal["auth", "network", "driver_missing", "unknown"] | None = None
    last_test_ok: bool | None = None
    managed_by: str
    max_rows: int
    name: str
    privacy: str
    timeout_seconds: int
    url: str


class DatasourceUpdate(BaseModel):
    """Todos los campos son opcionales; ``url`` solo se reemplaza si se envía."""

    model_config = ConfigDict(populate_by_name=True)

    dialect: Literal["sqlite", "postgres", "mysql", "tsql", "oracle", "snowflake", "bigquery"] | None = None
    execute: bool | None = None
    max_rows: int | None = None
    name: str | None = None
    privacy: Literal["schema", "aggregates", "samples"] | None = None
    timeout_seconds: int | None = None
    url: str | None = None


class EmbedSessionOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    expires_at: _dt.datetime
    token: str


class EmbedSessionRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    datasource: str
    origin: str
    ttl_seconds: int = 900
    user: EndUser


class EvalProviderOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    kind: str
    model: str
    name: str


class EvalRunCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    max_calls: int | None = None
    provider_ids: list[str]


class EvalRunOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    cases_done: int
    cases_total: int
    created_at: _dt.datetime
    error: str | None
    id: str
    providers: list[EvalProviderOut]
    report: dict[str, Any] | None
    status: Literal["running", "done", "error"]


class FieldOption(BaseModel):
    """Valor permitido (`select`) o alternativo (`url`) de un campo."""

    model_config = ConfigDict(populate_by_name=True)

    label: str
    value: str


class FilterApplied(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    source: str
    text: str


class FilterIn(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    field: str
    op: str
    value: Any | None = None


class GrantIn(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    attributes: dict[str, str | int | float | bool | list[str | int | float]] = Field(default_factory=lambda: {})
    datasource_id: str
    role: str


class GrantOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    attributes: dict[str, Any]
    datasource_id: str
    role: str


class GrantsIn(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    grants: list[GrantIn]


class ViolationOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    code: str
    message: str


class GuardOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    allowed: bool
    sql: str | None
    tables: list[str]
    violations: list[ViolationOut]


class ValidationError(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    ctx: dict[str, Any] | None = None
    input: Any | None = None
    loc: list[str | int]
    msg: str
    type: str


class HTTPValidationError(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    detail: list[ValidationError] | None = None


class HealthResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    status: str
    version: str


class ImportPreview(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    diff: dict[str, list[dict[str, Any]]]
    model: dict[str, Any]
    warnings: list[dict[str, str]]


class Relationship(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    from_: str = Field(alias="from")
    to: str


class Table(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    columns: list[Column] = Field(default_factory=lambda: [])
    description: str | None = None
    name: str
    primary_key: list[str] = Field(default_factory=lambda: [])
    synonyms: list[str] = Field(default_factory=lambda: [])
    time_column: str | None = None


class IssueOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    message: str
    path: str


class IntrospectPreview(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    relationships: list[Relationship]
    schemas: list[str]
    tables: list[Table]
    warnings: list[IssueOut]


class IntrospectRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    sample_values: bool = False
    schemas: list[str] | None = None
    table_pattern: str | None = None


class LoginRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    email: str
    password: str


class SuggestedMetric(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    default_period: str | None
    description: str | None
    dimensions: list[str]
    label: str
    name: str
    requires_period: bool


class MetricsOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    metrics: list[SuggestedMetric]


class ModelsResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    error_kind: Literal["auth", "quota", "model_not_found", "timeout", "network", "provider_error"] | None = None
    message: str | None = None
    models: list[str] | None = None
    supported: bool


class PeriodOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    end_exclusive: _dt.date
    grain: str
    is_current: bool
    label: str
    start: _dt.date
    text: str


class PreviewOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    filters_applied: list[FilterApplied]
    guard: GuardOut
    metric: str
    period: PeriodOut | None
    reason: str
    role: str | None
    sql: str
    summary_table: str | None


class PreviewRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    dimensions: list[str] = Field(default_factory=lambda: [])
    filters: list[FilterIn] = Field(default_factory=lambda: [])
    granularity: Literal["day", "week", "month", "quarter", "year"] | None = None
    metric: str
    period: str | None = None
    view_as: ViewAs | None = None


class ProbeResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    error_kind: Literal["auth", "quota", "model_not_found", "timeout", "network", "provider_error"] | None = None
    latency_ms: float
    message: str | None = None
    ok: bool


class ProviderCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    config: dict[str, Any] | None = None
    is_default: bool = False
    kind: str
    model: str
    name: str
    params: dict[str, Any] | None = None
    secrets: dict[str, str] | None = None
    tasks: list[Literal["planner", "sql", "answer", "suggest"]] | None = None


class ProviderField(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    default: str | None = None
    help: str | None = None
    label: str
    name: str
    options: list[FieldOption] = Field(default_factory=lambda: [])
    required: bool = True
    type: Literal["text", "secret", "url", "select", "json"] = "text"


class ProviderOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    config: dict[str, Any]
    id: str
    is_default: bool
    kind: str
    managed_by: str
    model: str
    name: str
    params: dict[str, Any]
    secrets: dict[str, str]
    tasks: list[str]


class ProviderSpec(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    category: Literal["api", "platform", "chinese", "local"]
    docs_url: str
    fields: list[ProviderField]
    kind: str
    label: str
    litellm_prefix: str
    notes: str | None = None
    suggested_models: list[str] = Field(default_factory=lambda: [])


class ProviderTestIn(BaseModel):
    """Configuración a probar sin guardarla."""

    model_config = ConfigDict(populate_by_name=True)

    config: dict[str, Any] | None = None
    kind: str
    model: str
    params: dict[str, Any] | None = None
    secrets: dict[str, str] | None = None


class ProviderUpdate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    config: dict[str, Any] | None = None
    is_default: bool | None = None
    model: str | None = None
    name: str | None = None
    params: dict[str, Any] | None = None
    secrets: dict[str, str] | None = None
    tasks: list[Literal["planner", "sql", "answer", "suggest"]] | None = None


class PublishRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    base_version: int
    model: dict[str, Any]


class RoutingIn(BaseModel):
    """Tarea → id de proveedor, y cadena de respaldo en orden."""

    model_config = ConfigDict(populate_by_name=True)

    fallback: list[str] | None = None
    tasks: dict[str, str] | None = None


class SuggestRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    tables: list[str] | None = None


class Suggestion(BaseModel):
    """Una propuesta: `path` es `tabla` o `tabla.columna`; `value` es texto o lista (sinónimos)."""

    model_config = ConfigDict(populate_by_name=True)

    confidence: float
    field: Literal["description", "synonyms", "role"]
    path: str
    value: str | list[str]


class TestError(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    kind: Literal["auth", "network", "driver_missing", "unknown"]
    message: str


class TestResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    error: TestError | None = None
    latency_ms: int | None = None
    ok: bool
    server_version: str | None = None


class UserInfo(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    email: str
    id: str
    is_admin: bool


class TokenResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    access_token: str
    expires_in: int
    token_type: str = "bearer"
    user: UserInfo


class UserCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    email: str
    is_admin: bool = False
    password: str


class UserOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    email: str
    grants: list[GrantOut]
    id: str
    is_admin: bool


class UserUpdate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    email: str | None = None
    is_admin: bool | None = None
    password: str | None = None


class ValidateSqlOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    allowed: bool
    role: str | None
    sql: str | None
    tables: list[str]
    violations: list[ViolationOut]


class ValidateSqlRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    sql: str
    view_as: ViewAs | None = None


class VersionInfo(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    created_at: _dt.datetime
    created_by: str | None
    version: int


class VersionOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    created_at: _dt.datetime
    created_by: str | None
    model: dict[str, Any]
    version: int



for _model in (ApiKeyCreate, ApiKeyCreated, ApiKeyOut, ApiKeyUpdate, AuditEntryOut, AuditPage, Body_import_semantic_api_v1_datasources__datasource_id__semantic_import_post, CancelOut, EndUser, ViewAs, ChatRequest, Column, MessageOut, ConversationDetail, ConversationOut, ConversationUpdate, DatasourceCreate, DatasourceOut, DatasourceUpdate, EmbedSessionOut, EmbedSessionRequest, EvalProviderOut, EvalRunCreate, EvalRunOut, FieldOption, FilterApplied, FilterIn, GrantIn, GrantOut, GrantsIn, ViolationOut, GuardOut, ValidationError, HTTPValidationError, HealthResponse, ImportPreview, Relationship, Table, IssueOut, IntrospectPreview, IntrospectRequest, LoginRequest, SuggestedMetric, MetricsOut, ModelsResult, PeriodOut, PreviewOut, PreviewRequest, ProbeResult, ProviderCreate, ProviderField, ProviderOut, ProviderSpec, ProviderTestIn, ProviderUpdate, PublishRequest, RoutingIn, SuggestRequest, Suggestion, TestError, TestResult, UserInfo, TokenResponse, UserCreate, UserOut, UserUpdate, ValidateSqlOut, ValidateSqlRequest, VersionInfo, VersionOut, ):
    _model.model_rebuild()

__all__ = [
    "SPEC_VERSION",
    "ApiKeyCreate",
    "ApiKeyCreated",
    "ApiKeyOut",
    "ApiKeyUpdate",
    "AuditEntryOut",
    "AuditPage",
    "Body_import_semantic_api_v1_datasources__datasource_id__semantic_import_post",
    "CancelOut",
    "ChatRequest",
    "Column",
    "ConversationDetail",
    "ConversationOut",
    "ConversationUpdate",
    "DatasourceCreate",
    "DatasourceOut",
    "DatasourceUpdate",
    "EmbedSessionOut",
    "EmbedSessionRequest",
    "EndUser",
    "EvalProviderOut",
    "EvalRunCreate",
    "EvalRunOut",
    "FieldOption",
    "FilterApplied",
    "FilterIn",
    "GrantIn",
    "GrantOut",
    "GrantsIn",
    "GuardOut",
    "HTTPValidationError",
    "HealthResponse",
    "ImportPreview",
    "IntrospectPreview",
    "IntrospectRequest",
    "IssueOut",
    "LoginRequest",
    "MessageOut",
    "MetricsOut",
    "ModelsResult",
    "PeriodOut",
    "PreviewOut",
    "PreviewRequest",
    "ProbeResult",
    "ProviderCreate",
    "ProviderField",
    "ProviderOut",
    "ProviderSpec",
    "ProviderTestIn",
    "ProviderUpdate",
    "PublishRequest",
    "Relationship",
    "RoutingIn",
    "SuggestRequest",
    "SuggestedMetric",
    "Suggestion",
    "Table",
    "TestError",
    "TestResult",
    "TokenResponse",
    "UserCreate",
    "UserInfo",
    "UserOut",
    "UserUpdate",
    "ValidateSqlOut",
    "ValidateSqlRequest",
    "ValidationError",
    "VersionInfo",
    "VersionOut",
    "ViewAs",
    "ViolationOut",
]
