"""Configuración como código: carga y validación de `chatiapp.yaml`."""

import os
import re
from pathlib import Path
from typing import Annotated, Any, Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

_VAR = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")

Privacy = Literal["schema", "aggregates", "samples"]
Dialect = Literal[
    "postgres", "redshift", "tsql", "mysql", "oracle", "snowflake", "bigquery", "sqlite"
]


class ConfigError(Exception):
    """Error de configuración: cada línea es `ruta: motivo`."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("Configuración inválida:\n" + "\n".join(f"  - {e}" for e in errors))


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AppConfig(_Strict):
    public_url: str = "http://localhost:8080"
    language: str = "es"
    timezone: str = "UTC"


class ProviderConfig(_Strict):
    id: Annotated[str, Field(min_length=1, max_length=100)]
    kind: Annotated[str, Field(min_length=1, max_length=50)]
    model: Annotated[str, Field(min_length=1, max_length=255)]
    # Campos de conexión según el proveedor (docs/PROVEEDORES_IA.md).
    api_key: str | None = None
    api_base: str | None = None
    api_version: str | None = None
    organization: str | None = None
    aws_region: str | None = None
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    vertex_project: str | None = None
    vertex_location: str | None = None
    vertex_credentials: str | None = None


SECRET_PROVIDER_FIELDS = frozenset(
    {"api_key", "aws_access_key_id", "aws_secret_access_key", "vertex_credentials"}
)


class RoutingConfig(_Strict):
    planner: str | None = None
    sql: str | None = None
    answer: str | None = None
    suggest: str | None = None
    fallback: list[str] = Field(default_factory=list)


class AiConfig(_Strict):
    providers: list[ProviderConfig] = Field(default_factory=list)
    routing: RoutingConfig = Field(default_factory=RoutingConfig)
    privacy: Privacy = "schema"

    @model_validator(mode="after")
    def _enrutamiento_referencia_proveedores(self) -> Self:
        ids = [p.id for p in self.providers]
        duplicated = sorted({i for i in ids if ids.count(i) > 1})
        if duplicated:
            raise ValueError(f"ids de proveedor repetidos: {', '.join(duplicated)}")
        routing = self.routing
        used = [routing.planner, routing.sql, routing.answer, routing.suggest, *routing.fallback]
        unknown = sorted({u for u in used if u is not None and u not in ids})
        if unknown:
            raise ValueError(f"routing referencia proveedores no declarados: {', '.join(unknown)}")
        return self


class DatasourceConfig(_Strict):
    id: Annotated[str, Field(min_length=1, max_length=100)]
    name: Annotated[str, Field(min_length=1, max_length=255)]
    dialect: Dialect
    url: Annotated[str, Field(min_length=1)]
    execute: bool = False
    max_rows: Annotated[int, Field(ge=1, le=100_000)] = 1000
    timeout_seconds: Annotated[int, Field(ge=1, le=600)] = 30
    semantic_model: Path


class ProjectConfig(_Strict):
    version: Literal[1]
    app: AppConfig = Field(default_factory=AppConfig)
    ai: AiConfig = Field(default_factory=AiConfig)
    datasources: list[DatasourceConfig] = Field(default_factory=list)

    @model_validator(mode="after")
    def _ids_de_fuentes_unicos(self) -> Self:
        ids = [d.id for d in self.datasources]
        duplicated = sorted({i for i in ids if ids.count(i) > 1})
        if duplicated:
            raise ValueError(f"ids de fuente repetidos: {', '.join(duplicated)}")
        return self


def format_path(parts: tuple[str | int, ...] | list[str | int]) -> str:
    """`("ai", "providers", 0, "api_key")` → `ai.providers[0].api_key`."""
    out = ""
    for part in parts:
        if isinstance(part, int):
            out += f"[{part}]"
        else:
            out += f".{part}" if out else part
    return out or "(raíz)"


def _literal_secrets(raw: Any) -> list[str]:
    """Credenciales escritas en claro: deben ser exactamente `${VARIABLE}` (PROVEEDORES_IA.md)."""
    ai = raw.get("ai") if isinstance(raw, dict) else None
    providers = ai.get("providers") if isinstance(ai, dict) else None
    if not isinstance(providers, list):
        return []
    errors: list[str] = []
    for index, provider in enumerate(providers):
        if not isinstance(provider, dict):
            continue
        for field in sorted(SECRET_PROVIDER_FIELDS & set(provider)):
            value = provider[field]
            if value is None or (isinstance(value, str) and _VAR.fullmatch(value.strip())):
                continue
            errors.append(
                f"{format_path(['ai', 'providers', index, field])}: los secretos no se escriben "
                "en el archivo; usa ${VARIABLE} y defínela en el entorno"
            )
    return errors


def _interpolate(value: Any, path: list[str | int], env: dict[str, str], errors: list[str]) -> Any:
    if isinstance(value, dict):
        return {k: _interpolate(v, [*path, str(k)], env, errors) for k, v in value.items()}
    if isinstance(value, list):
        return [_interpolate(v, [*path, i], env, errors) for i, v in enumerate(value)]
    if isinstance(value, str):

        def replace(match: re.Match[str]) -> str:
            name = match.group(1)
            if name not in env:
                errors.append(f"{format_path(path)}: la variable {name} no está definida")
                return match.group(0)
            return env[name]

        return _VAR.sub(replace, value)
    return value


def parse_project_config(
    raw: Any, base_dir: Path, env: dict[str, str] | None = None
) -> ProjectConfig:
    """Interpola `${VAR}`, valida y resuelve rutas relativas a `base_dir`."""
    errors = _literal_secrets(raw)
    if errors:
        raise ConfigError(errors)
    data = _interpolate(raw, [], dict(os.environ) if env is None else env, errors)
    if errors:
        raise ConfigError(errors)
    if not isinstance(data, dict):
        raise ConfigError(["(raíz): el archivo debe ser un mapa YAML"])
    try:
        config = ProjectConfig.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(
            [f"{format_path(e['loc'])}: {e['msg']}" for e in exc.errors(include_url=False)]
        ) from exc

    for index, datasource in enumerate(config.datasources):
        resolved = (base_dir / datasource.semantic_model).resolve()
        if not resolved.is_file():
            errors.append(
                f"{format_path(['datasources', index, 'semantic_model'])}: "
                f"no existe el archivo {resolved}"
            )
        datasource.semantic_model = resolved
    if errors:
        raise ConfigError(errors)
    return config


def load_project_config(path: Path, env: dict[str, str] | None = None) -> ProjectConfig:
    """Carga `chatiapp.yaml`; `semantic_model` se resuelve junto al archivo."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError([f"{path}: no se puede leer el archivo ({exc})"]) from exc
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError([f"{path}: YAML inválido ({exc})"]) from exc
    return parse_project_config(raw, path.resolve().parent, env)
