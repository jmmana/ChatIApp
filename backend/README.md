# Backend

```bash
uv sync
uv run uvicorn app.main:app --reload   # http://localhost:8000/api/v1/docs
uv run ruff check . && uv run ruff format --check . && uv run mypy app && uv run pytest
```
