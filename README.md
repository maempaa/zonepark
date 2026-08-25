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
| Estado del sistema | http://localhost:4321/estado |
| PostgreSQL | `localhost:55432` |

`/estado` muestra la cadena completa: si los tres renglones salen en
**OK**, el entorno está sano.

## Datos de prueba

```bash
make seed
```

Crea dos parqueaderos **a propósito**. Tener siempre un segundo cliente en
la base hace que una fuga de datos entre tenants se note enseguida, en vez
de aparecer el día que entra el segundo cliente real.

| Parqueadero | Usuario | Clave | Rol | Alcance |
|---|---|---|---|---|
| [central](http://localhost:4321/t/central) | `admin@central.com.co` | `central12345` | Administrador | Todas las sedes |
| central | `super@central.com.co` | `central12345` | Supervisor | S1 |
| central | `operario@central.com.co` | `central12345` (PIN `482913`) | Operario | S1 |
| [norte](http://localhost:4321/t/norte) | `admin@norte.com.co` | `norte12345` | Administrador | Todas las sedes |

## Cómo funciona el aislamiento entre clientes

El tenant viaja en la ruta: `/t/central/...`. La resolución vive aislada en
[`core/tenancy.py`](backend/app/core/tenancy.py), así que pasar a
subdominios más adelante es cambiar una función.

El aislamiento no depende de que las consultas recuerden filtrar. Son tres
capas:

1. `tenant_id` en todas las tablas del cliente.
2. Políticas **RLS** en Postgres sobre ese campo.
3. Un rol de base de datos sin privilegios de dueño (`zonepark_app`) que la
   aplicación adopta con `SET LOCAL ROLE` en cada transacción de tenant. El
   dueño esquiva RLS; ese rol no.

Si nadie fija `app.tenant_id`, la comparación da NULL y **no se ve ninguna
fila**: falla cerrado. Las operaciones que ocurren antes de saber el tenant
(el propio login) usan `system_scope()`, que sí corre como dueño y está
acotado a unos pocos sitios.

La sesión del navegador vive en cookies `httpOnly` que pone Astro: el
cliente nunca ve un token, y el proxy renueva el de acceso solo cuando
caduca.

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

- **Fase 0** — andamiaje dockerizado, verificado de punta a punta.
- **Fase 1** — tenancy con RLS, usuarios, roles, dispositivos y bitácora.
  36 pruebas contra Postgres real, incluido el criterio de aceptación:
  un tenant no lee ni un registro de otro ni forzando identificadores.

Sigue la **fase 2**: parametrización (tipos de vehículo, artículos) y el
motor de tarifas. Es la fase de mayor riesgo del proyecto y por eso se
construye antes que la operación.
