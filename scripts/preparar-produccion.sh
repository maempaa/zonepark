#!/usr/bin/env bash
# Deja este servidor en configuración de producción.
#
# Rota los secretos que venían del entorno de desarrollo. Importa: la
# contraseña de la base y el secreto de firma están en .env.example, que
# es público en el repositorio. Cualquiera podría firmar tokens válidos
# contra un despliegue que se quedara con ellos.
#
# Es idempotente: si ya se corrió, no vuelve a rotar nada.
set -euo pipefail

cd "$(dirname "$0")/.."

EJEMPLO_JWT="dev_secret_cambiar_en_produccion"
EJEMPLO_CLAVE="zonepark_dev"

if [ ! -f .env ]; then
  echo "No hay .env. Copia .env.example y vuelve a intentarlo." >&2
  exit 1
fi

. ./.env

if [ "${JWT_SECRET}" != "$EJEMPLO_JWT" ] && [ "${APP_ENV}" = "production" ]; then
  echo "Ya está en producción con secretos propios. No se toca nada."
  exit 0
fi

echo "→ Respaldando la base antes de tocar nada"
./scripts/respaldo.sh

cp .env ".env.antes-de-produccion-$(date +%Y%m%d-%H%M%S)"

JWT_NUEVO="$(openssl rand -hex 32)"
CLAVE_NUEVA="$(openssl rand -base64 24 | tr -d '/+=' | head -c 32)"

# La contraseña del contenedor de postgres solo se aplica al inicializar
# el volumen. Como la base ya existe, hay que cambiarla dentro.
echo "→ Cambiando la contraseña de la base"
docker compose exec -T db psql -v ON_ERROR_STOP=1 \
  --username "${POSTGRES_USER}" --dbname "${POSTGRES_DB}" \
  -c "ALTER USER ${POSTGRES_USER} WITH PASSWORD '${CLAVE_NUEVA}';" >/dev/null

echo "→ Escribiendo .env de producción"
python3 - "$JWT_NUEVO" "$CLAVE_NUEVA" <<'PY'
import pathlib, sys, re
jwt, clave = sys.argv[1], sys.argv[2]
p = pathlib.Path('.env'); t = p.read_text()

def poner(texto, clave_env, valor):
    patron = re.compile(rf'^{clave_env}=.*$', re.M)
    linea = f'{clave_env}={valor}'
    return patron.sub(linea, texto) if patron.search(texto) else texto + f'\n{linea}\n'

t = poner(t, 'APP_ENV', 'production')
t = poner(t, 'JWT_SECRET', jwt)
t = poner(t, 'POSTGRES_PASSWORD', clave)
# El navegador nunca llama a la API directamente: todo pasa por el BFF de
# Astro, mismo origen. Sin peticiones entre orígenes, CORS sobra.
t = poner(t, 'CORS_ORIGINS', '')
p.write_text(t)
PY

chmod 600 .env
echo
echo "Listo. Los secretos nuevos están solo en .env (que no se versiona)."
echo "Ahora: make deploy"
