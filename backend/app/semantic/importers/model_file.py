"""Importador de modelos completos en YAML o JSON, validados con el esquema completo."""

import importlib
import json
from pathlib import Path

from app.semantic.schema import Issue, SemanticModel, SemanticModelError, parse_semantic_model


def parse_model_text(text: str, fmt: str) -> SemanticModel:
    """Valida un modelo en texto. `fmt` es `yaml` o `json`. Lanza `SemanticModelError`."""
    data: object
    if fmt == "json":
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise SemanticModelError(
                [Issue("", f"JSON no válido (línea {exc.lineno}, columna {exc.colno}): {exc.msg}")]
            ) from exc
    elif fmt == "yaml":
        yaml = importlib.import_module("yaml")
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise SemanticModelError([Issue("", f"YAML no válido: {exc}")]) from exc
    else:
        raise SemanticModelError([Issue("", f"Formato «{fmt}» no soportado: usa yaml o json")])
    if not isinstance(data, dict):
        raise SemanticModelError([Issue("", "El modelo debe ser un objeto con campos")])
    return parse_semantic_model(data)


def import_model_file(path: Path) -> SemanticModel:
    """Lee y valida un `.yaml`, `.yml` o `.json`."""
    suffix = path.suffix.lower()
    fmt = {".yaml": "yaml", ".yml": "yaml", ".json": "json"}.get(suffix)
    if fmt is None:
        message = f"Extensión «{suffix}» no soportada: usa .yaml o .json"
        raise SemanticModelError([Issue("", message)])
    return parse_model_text(path.read_text(encoding="utf-8"), fmt)
