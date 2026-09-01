# Producción

Este servidor es a la vez el de desarrollo y el de producción. La
instancia corre en modo producción; para volver a desarrollo hay que
bajarla y levantar el otro compose.

## Comandos

```bash
make deploy      # construye, migra y levanta producción
make prod-ps     # estado
make prod-logs   # logs
make respaldo    # copia de la base, comprimida y fechada
```

`make up` es el de **desarrollo** y no debe usarse aquí mientras
producción esté en pie: usan los mismos contenedores.

## Qué cambia respecto a desarrollo

| | Desarrollo | Producción |
|---|---|---|
| Imágenes | con herramientas y recarga | delgadas, usuario sin privilegios |
| `/docs` | abierto | 404 |
| Puertos al host | api, base, redis y web | solo web, en `127.0.0.1` |
| Cookies de sesión | sin marca `Secure` | `HttpOnly; Secure; SameSite=Lax` |
| Migraciones | al arrancar la API | paso aparte que debe terminar bien |
| Secretos | los de `.env.example` | propios, solo en `.env` |

**Nada de ZonePark escucha hacia internet.** El navegador nunca llama a
la API directamente —todo pasa por el BFF de Astro, en el mismo origen—
así que exponerla solo abriría superficie sin dar nada a cambio. Por lo
mismo, CORS va vacío: no hay peticiones entre orígenes que permitir.

Las migraciones corren como un servicio aparte que tiene que terminar
bien antes de que arranque la API. Si fallan, la versión anterior sigue
en pie en lugar de quedar a medias.

## Publicación: túnel de Cloudflare

El servidor ya tiene Traefik en 80 y 443 (Dokploy), así que ZonePark sale
por el túnel de Cloudflare en `/var/apps/cloudflared`.

La red `zonepark-publica` es el punto de encuentro entre los dos. Se creó
aparte a propósito: bajar el túnel no debe tumbar el parqueadero, ni al
revés.

Para conectarlos:

```bash
cd /var/apps/cloudflared && docker compose up -d
docker network connect zonepark-publica <contenedor-de-cloudflared>
```

Y en el panel de Cloudflare, en el túnel, añadir un *public hostname*:

| Campo | Valor |
|---|---|
| Subdomain / Domain | el que vayas a usar |
| Service | `HTTP` |
| URL | `zonepark-web-1:4321` |

Cloudflare pone el certificado, así que el navegador habla HTTPS aunque
por dentro del túnel viaje HTTP plano. Eso es lo que hace válidas las
cookies `Secure`.

> **Sin HTTPS la aplicación no funciona bien**, y no es un capricho:
> las cookies de sesión van marcadas `Secure` y el navegador las
> descarta sobre HTTP. Además `crypto.randomUUID` —la llave que evita
> cobrar dos veces— solo existe en contexto seguro.

## El dominio hay que declararlo

`DOMINIOS_PERMITIDOS` en `.env` lista los dominios desde los que se sirve
el sitio. No es opcional: Astro valida contra ella el `Host` de cada
petición y, si la lista está vacía, descarta el host real y arma toda url
como `http://localhost`. Su propio chequeo CSRF pasa entonces a rechazar
los POST y DELETE legítimos que van sin cuerpo — publicar una tarifa,
descartar un borrador, cerrar sesión — con un `403 Cross-site POST form
submissions are forbidden` que no menciona el host por ningún lado.

`localhost` y `127.0.0.1` se aceptan siempre. Para varios dominios,
sepáralos con comas.

**Se lee al compilar el front**, no al arrancarlo: si cambias el dominio,
`make deploy` (que reconstruye la imagen). Reiniciar el contenedor no
alcanza.

Para comprobarlo sin sesión, un POST con el `Origin` del sitio debe
responder `401` (llegó al backend y pide credenciales), nunca `403`:

```bash
curl -s -o /dev/null -w '%{http_code}\n' -X POST \
  https://zonepark.softutopic.com/api/v1/t/central/planes/x/activar \
  -H 'Origin: https://zonepark.softutopic.com'
```

## Respaldos

Diarios a las 3:15, por `cron`, con rutas absolutas. Se conservan los
últimos 14 en `respaldos/`, que no se versiona.

Un dump de menos de 1 KB se descarta en vez de guardarse: un respaldo
vacío es peor que ninguno, porque parece que hay copia y no la hay.

Restaurar:

```bash
gunzip -c respaldos/zonepark-AAAAMMDD-HHMMSS.sql.gz \
  | docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T db \
      psql -U zonepark -d zonepark
```

## Secretos

`scripts/preparar-produccion.sh` rota el secreto de firma y la contraseña
de la base. Importa: los valores de desarrollo están en `.env.example`,
que es público en el repositorio, y con ese secreto cualquiera podría
firmar tokens de acceso válidos.

Es idempotente y respalda la base y el `.env` antes de tocar nada. Los
valores nuevos quedan solo en `.env`, con permisos `600` y fuera del
control de versiones.

La contraseña de Postgres se cambia **dentro** de la base con `ALTER
USER`: la variable del contenedor solo se aplica al inicializar el
volumen, y aquí el volumen ya existía.

## Qué falta

- **Alertas.** Si un contenedor se cae de madrugada, nadie se entera.
- **Memoria.** El servidor está al límite: quedan unos 400 MB libres con
  Oracle ocupando 1,8 GB. No hay margen para una segunda instancia.
- **Sin entorno de pruebas.** Los cambios se prueban en el mismo sitio
  donde se cobra.
