"""Exporta la especificación OpenAPI de `v1` a `docs/openapi/v1.json`.

    uv run python -m app.api.openapi          # escribe docs/openapi/v1.json
    uv run python -m app.api.openapi --check  # falla si el archivo difiere de la app

Es el mismo documento que sirve `GET /api/v1/openapi.json`.
"""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from fastapi import FastAPI

SPEC_PATH = Path(__file__).resolve().parents[3] / "docs" / "openapi" / "v1.json"


def render_spec(application: FastAPI) -> str:
    """Serialización estable (claves ordenadas, sangría de 2, salto de línea final)."""
    return json.dumps(application.openapi(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.api.openapi")
    parser.add_argument("--check", action="store_true", help="No escribe; falla si difiere")
    parser.add_argument("--output", type=Path, default=SPEC_PATH)
    args = parser.parse_args(argv)

    from app.main import create_app

    rendered = render_spec(create_app())
    if args.check:
        current = args.output.read_text(encoding="utf-8") if args.output.exists() else None
        if current != rendered:
            print(
                f"{args.output} no coincide con la API. Regenéralo con "
                "`uv run python -m app.api.openapi`.",
                file=sys.stderr,
            )
            return 1
        return 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
