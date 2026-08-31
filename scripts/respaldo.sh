#!/usr/bin/env bash
# Copia de la base de datos.
#
# Se guarda comprimida y con la fecha en el nombre. Conserva las últimas
# 14: en una base de 12 MB eso no es nada y cubre dos semanas de errores
# que se descubren tarde.
set -euo pipefail

cd "$(dirname "$0")/.."
[ -f .env ] && set -a && . ./.env && set +a

DESTINO="respaldos"
mkdir -p "$DESTINO"
ARCHIVO="$DESTINO/zonepark-$(date +%Y%m%d-%H%M%S).sql.gz"

docker compose exec -T db pg_dump \
  --username "${POSTGRES_USER:-zonepark}" \
  --dbname "${POSTGRES_DB:-zonepark}" \
  --clean --if-exists \
  | gzip > "$ARCHIVO"

# Un dump vacío es peor que ninguno: parece que hay respaldo y no lo hay.
TAMANO=$(stat -c%s "$ARCHIVO")
if [ "$TAMANO" -lt 1024 ]; then
  echo "El respaldo salió vacío ($TAMANO bytes). Se descarta." >&2
  rm -f "$ARCHIVO"
  exit 1
fi

ls -1t "$DESTINO"/zonepark-*.sql.gz 2>/dev/null | tail -n +15 | xargs -r rm --

echo "Respaldo: $ARCHIVO ($(numfmt --to=iec "$TAMANO"))"
