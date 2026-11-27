#!/bin/sh
# Prueba de humo de la imagen única: arranca, responde, sirve la interfaz,
# crea la demo y conserva la llave de cifrado entre reinicios.
#
#   sh scripts/smoke-image.sh [imagen]      (por defecto chatiapp:local)
set -eu

IMAGE="${1:-chatiapp:local}"
NAME="chatiapp-smoke-$$"
VOLUME="chatiapp-smoke-$$"
PORT="${SMOKE_PORT:-18080}"
URL="http://127.0.0.1:$PORT"

cleanup() {
    docker rm -f "$NAME" > /dev/null 2>&1 || true
    docker volume rm "$VOLUME" > /dev/null 2>&1 || true
}
trap cleanup EXIT

fail() {
    echo "FALLA: $*" >&2
    docker logs "$NAME" >&2 || true
    exit 1
}

start() {
    docker run -d --name "$NAME" -p "$PORT:8080" -v "$VOLUME:/data" "$IMAGE" > /dev/null
    i=0
    until [ "$(docker inspect -f '{{.State.Health.Status}}' "$NAME")" = "healthy" ]; do
        i=$((i + 1))
        [ "$i" -le 60 ] || fail "el contenedor no quedó sano en 120 s"
        [ "$(docker inspect -f '{{.State.Running}}' "$NAME")" = "true" ] || fail "el contenedor se detuvo"
        sleep 2
    done
}

status() { curl -s -o /dev/null -w '%{http_code}' -X "${2:-GET}" "$URL$1"; }

expect() {
    got="$(status "$1" "${3:-GET}")"
    [ "$got" = "$2" ] || fail "${3:-GET} $1 devolvió $got, se esperaba $2"
    echo "ok  ${3:-GET} $1 → $got"
}

start
expect /api/v1/health 200
curl -s "$URL/api/v1/health" | grep -q '"status":"ok"' || fail "health sin status ok"
expect / 200
expect /chat 200
expect /modelo-semantico 200
curl -s "$URL/chat" | grep -qi '<div id="root">' || fail "/chat no devolvió index.html"
ASSET="$(curl -s "$URL/" | grep -o '/assets/[^"]*\.js' | head -n 1)"
[ -n "$ASSET" ] || fail "index.html no referencia ningún /assets/*.js"
expect "$ASSET" 200
expect /assets/no-existe.js 404
expect /embed/v1/chatiapp.js 200
expect /embed/v1/chatiapp-widget.js 200
expect /embed/v1/no-existe.js 404
expect /api/v1/no-existe 404
expect /api/v1/no-existe 404 POST
curl -s "$URL/api/v1/no-existe" | grep -q '"detail"' || fail "el 404 de la API no es JSON"

[ "$(docker exec "$NAME" id -u)" != "0" ] || fail "el proceso corre como root"
docker exec "$NAME" test -s /data/demo/ventas.db || fail "no se creó la demo"
docker exec "$NAME" test -s /data/chatiapp.db || fail "no se creó la base de la app"
[ "$(docker exec "$NAME" stat -c '%a' /data/secret.key)" = "600" ] || fail "secret.key sin permisos 600"
echo "ok  demo, base de la app y llave en /data, usuario sin root"

KEY="$(docker exec "$NAME" cat /data/secret.key)"
docker rm -f "$NAME" > /dev/null
start
[ "$(docker exec "$NAME" cat /data/secret.key)" = "$KEY" ] || fail "la llave cambió al reiniciar"
expect /api/v1/health 200
echo "ok  reinicio: misma llave, migraciones idempotentes"

echo "Prueba de humo superada: $IMAGE"
