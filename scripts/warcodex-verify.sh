#!/bin/sh
# Verificación que WarCodex ejecuta dentro de su contenedor al terminar cada tarea (test_command).
#
# Ese contenedor tiene Node 22 y pnpm, y solo descarga paquetes de npm: NO tiene Python ni uv.
# Por eso aquí se verifica el frontend (y el chat embebible) y el backend lo verifica el CI de
# GitHub (.github/workflows/ci.yml). Si WARCODEX_CHANGED_FILES existe, solo se verifica lo tocado.
set -eu

changed="${WARCODEX_CHANGED_FILES:-}"

touches() {
  # Sin lista de cambios se verifica todo.
  if [ -z "$changed" ] || [ ! -f "$changed" ]; then return 0; fi
  grep -qE "$1" "$changed"
}

pnpm_cmd() {
  if command -v pnpm >/dev/null 2>&1; then pnpm "$@"; else corepack pnpm "$@"; fi
}

verify_node_package() {
  dir="$1"
  echo "== $dir: install, lint, test, build"
  (
    cd "$dir"
    pnpm_cmd install --frozen-lockfile
    pnpm_cmd run lint
    pnpm_cmd run test
    pnpm_cmd run build
  )
}

status=0

for dir in frontend embed; do
  if [ -f "$dir/package.json" ] && touches "^$dir/"; then
    verify_node_package "$dir" || status=1
  fi
done

if [ -f backend/pyproject.toml ] && touches '^backend/'; then
  echo "== backend: este contenedor no tiene Python; ruff, mypy y pytest corren en el CI de GitHub."
fi

exit "$status"
