# Verificación local: reproduce lo mismo que .github/workflows/ci.yml.
.PHONY: check backend-check frontend-check embed-check

check: backend-check frontend-check embed-check

backend-check:
	@if [ -f backend/pyproject.toml ]; then \
		cd backend && uv sync --locked && uv run ruff check . && uv run ruff format --check . && uv run mypy app && uv run pytest; \
	else echo "backend: todavía no existe"; fi

frontend-check:
	@if [ -f frontend/package.json ]; then \
		cd frontend && pnpm install --frozen-lockfile && pnpm run lint && pnpm run test && pnpm run build; \
	else echo "frontend: todavía no existe"; fi

embed-check:
	@if [ -f embed/package.json ]; then \
		cd embed && pnpm install --frozen-lockfile && pnpm run lint && pnpm run test && pnpm run build; \
	else echo "embed: todavía no existe"; fi
