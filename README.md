# ZonePark

Administración multitenant de parqueaderos. Astro (SSR) al frente, FastAPI
detrás, PostgreSQL y Redis, todo en docker con los puertos parametrizados.

- **Plan completo:** [`docs/PLAN.md`](docs/PLAN.md)
- **Decisiones cerradas:** [`DECISIONES.md`](DECISIONES.md)

## Arrancar

```bash
make up
```

Eso copia `.env.example` a `.env` si hace falta, construye las imágenes,
levanta los cuatro servicios y aplica las migraciones.

| Servicio | URL por defecto |
|---|---|
| Aplicación web | http://localhost:4321 |
| API | http://localhost:8010 |
| Documentación de la API | http://localhost:8010/docs (solo fuera de producción) |
| PostgreSQL | `localhost:55432` |

La página de inicio muestra el estado de la cadena completa: si los tres
renglones salen en **OK**, el entorno está sano.

## Puertos

Todos salen de `.env`. `API_PORT` y `WEB_PORT` se aplican tanto en el host
como dentro del contenedor, así que basta cambiar el número. `DB_PORT` y
`REDIS_PORT` son solo del host: dentro de la red de docker, postgres siempre
escucha en 5432 y redis en 6379.

Los valores por defecto (`8010`, `55432`) están fuera de los puertos
habituales a propósito: en una máquina de desarrollo casi siempre hay ya un
postgres en 5432 y algo en 8000.

## Comandos

```bash
make help
```

| Comando | Qué hace |
|---|---|
| `make up` / `make down` | Levanta o baja el stack de desarrollo |
| `make reset` | Baja el stack y **borra la base de datos** |
| `make logs` / `make ps` | Logs en vivo / estado de los servicios |
| `make migrate` | Aplica migraciones pendientes |
| `make revision m="..."` | Genera una migración nueva |
| `make test` / `make lint` | Pruebas y estilo del backend |
| `make shell` / `make psql` | Shell en la API / psql en la base |

## Desarrollo

El código se monta por volumen y ambos lados recargan solos: `uvicorn --reload`
en el backend y el servidor de Astro en el frontend.

Las peticiones del navegador nunca van directo a FastAPI: pasan por
`/api/*` en Astro, que actúa como BFF ([`src/pages/api/[...path].ts`](frontend/src/pages/api/%5B...path%5D.ts)).
Ahí es donde en la fase 1 se leerá la cookie httpOnly de sesión.

## Producción

```bash
docker compose -f docker-compose.yml up -d --build
```

Omitir el override cambia a las etapas `prod`: imágenes delgadas, usuario sin
privilegios, sin recarga y sin `/docs` cuando `APP_ENV=production`.

Cada etapa lleva su propia etiqueta (`zonepark-api:dev` vs `zonepark-api:prod`)
para que construir una no sobrescriba la otra.

## Estado

Fase 0 completa: andamiaje verificado de punta a punta. Sigue la fase 1
(tenancy, usuarios y roles) según el roadmap del plan.
