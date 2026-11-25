#!/bin/sh
# Prepara el volumen de datos, aplica las migraciones y arranca el comando del
# contenedor (docs/adr/0008-imagen-unica-con-sqlite.md).
set -eu

DATA_DIR="${CHATIAPP_DATA_DIR:-/data}"
mkdir -p "$DATA_DIR"

# Llave de cifrado de credenciales. Si no viene del entorno, se genera una vez
# y se guarda en el volumen, para que las credenciales sobrevivan a reinicios.
if [ -z "${CHATIAPP_SECRET_KEY:-}" ]; then
    KEY_FILE="$DATA_DIR/secret.key"
    if [ ! -s "$KEY_FILE" ]; then
        (
            umask 077
            python -c "import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())" \
                > "$KEY_FILE.tmp"
        )
        mv "$KEY_FILE.tmp" "$KEY_FILE"
        echo "chatiapp: se generó la llave de cifrado en $KEY_FILE." \
            "En producción define CHATIAPP_SECRET_KEY desde tu gestor de secretos." >&2
    fi
    CHATIAPP_SECRET_KEY="$(cat "$KEY_FILE")"
    export CHATIAPP_SECRET_KEY
fi

alembic upgrade head

# Base de demostración «Ventas», solo la primera vez.
DEMO_DB="$DATA_DIR/demo/ventas.db"
if [ "${CHATIAPP_DEMO:-true}" = "true" ] && [ ! -f "$DEMO_DB" ]; then
    mkdir -p "$DATA_DIR/demo"
    python -m app.demo.seed --out "$DEMO_DB.tmp" > /dev/null
    mv "$DEMO_DB.tmp" "$DEMO_DB"
    echo "chatiapp: base de demostración creada en $DEMO_DB" >&2
fi

exec "$@"
