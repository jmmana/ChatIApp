#!/bin/sh
# Prepara la integración de ejemplo DENTRO de la imagen de ChatIApp: crea la API key de la app
# anfitriona (solo la primera vez) y deja la llave y el id de la fuente de la demo en
# /data/integracion/, que la app anfitriona monta en solo lectura.
#
# Es un atajo para el ejemplo. En producción crea la key con `chatiapp keys create` o desde
# Integraciones, y entrégala a tu backend con tu gestor de secretos.
set -eu

DIR="${CHATIAPP_DATA_DIR:-/data}/integracion"
ORIGIN="${HOST_ORIGIN:-http://localhost:8000}"
mkdir -p "$DIR"

if [ -s "$DIR/api_key" ] && [ -s "$DIR/datasource" ]; then
    echo "integración: la key ya existe" >&2
    exit 0
fi

DATASOURCE="$(python - <<'PY'
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Datasource
from app.db.session import get_engine
from app.demo.bootstrap import DEMO_NAME

with Session(get_engine()) as session:
    print(session.scalar(select(Datasource.id).where(Datasource.name == DEMO_NAME)) or "")
PY
)"
[ -n "$DATASOURCE" ] || { echo "integración: no existe la fuente de la demo (CHATIAPP_DEMO)" >&2; exit 1; }

KEY="$(chatiapp keys create --name "App anfitriona de ejemplo" --scopes embed \
    --datasource "$DATASOURCE" --roles gerente_sucursal --origin "$ORIGIN")"

# Legibles por el usuario de la otra imagen; los datos del ejemplo no son sensibles.
umask 022
printf '%s' "$DATASOURCE" > "$DIR/datasource"
printf '%s' "$KEY" > "$DIR/api_key.tmp"
mv "$DIR/api_key.tmp" "$DIR/api_key"
echo "integración: key creada para $ORIGIN" >&2
