#!/bin/sh
# Aplica las migraciones y luego arranca el comando del contenedor.
set -e
alembic upgrade head
exec "$@"
