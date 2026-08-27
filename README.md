# ZonePark

Administración multitenant de parqueaderos. Astro (SSR) al frente, FastAPI
detrás, PostgreSQL y Redis, todo en docker con los puertos parametrizados.

- **Qué hace y por qué:** [`docs/PRD.md`](docs/PRD.md)
- **Plan técnico:** [`docs/PLAN.md`](docs/PLAN.md)
- **Decisiones cerradas:** [`DECISIONES.md`](docs/DECISIONES.md)

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

## Tarifas

Todo es parametrizable desde la base, sin desplegar nada: los tipos de
vehículo y los artículos son tablas por tenant, no enums.

El motor vive en [`domain/pricing`](backend/app/domain/pricing) como
funciones puras. Siete modos de cobro, y el que más se usa —"hora o
fracción"— es el mismo que "media hora o fracción" y que "por minuto"
cambiando un número: `bloque_minutos`. No hay código nuevo por variante.

Encima van los modificadores: cortesía, cobro mínimo, tope por cada 24 h,
redondeo a múltiplos de efectivo, IVA incluido o agregado, escalones y
franjas horarias (nocturna, fin de semana, festivo).

Dos decisiones que conviene conocer antes de configurar una tarifa:

- **Los modificadores salen de la regla vigente a la entrada**, aunque la
  estadía cruce franjas. Si dependieran del tramo, bastaría con entrar
  justo antes de un cambio de franja para elegir el más conveniente.
- **Solo se segmentan por franja los modos que cobran por unidad de
  tiempo.** Los demás se refieren a la posición dentro de la estadía —la
  primera hora, los escalones, el precio único— y partirlos daría
  resultados que nadie sabría explicarle a un cliente.

Al abrir un ticket se congela el JSON de las reglas que le aplican. A
partir de ahí ese ticket ya no depende de la tabla: si suben la tarifa, o
alguien archiva el plan, se sigue cotizando con lo que se le prometió al
cliente al entrar.

El **simulador** (`/t/{slug}/config/tarifas`) cotiza contra cualquier plan,
incluidos los borradores. Es la red de seguridad para probar una tarifa
antes de que alguien la esté pagando.

## Operación

El operario trabaja de pie, con una mano y con mala señal. Las pantallas
salen de ahí:

| Pantalla | Qué resuelve |
|---|---|
| `/t/{slug}` | Cuántos vehículos hay adentro y dos botones grandes |
| `/t/{slug}/ingresar` | Tipo de vehículo en botones, placa, listo |
| `/t/{slug}/buscar` | Se teclean los últimos dígitos de la placa |
| `/t/{slug}/tickets/{id}` | Tiempo y valor en vivo, artículos, cobro y recibo |
| `/t/{slug}/caja` | Abrir turno, movimientos y cierre con conteo a ciegas |
| `/t/{slug}/reportes` | Ocupación, ingresos y turnos descuadrados |

Tres cosas del cobro que evitan cobrar de más, de menos o dos veces:

- **Es idempotente.** Bloquea la fila del ticket y, si ya estaba cerrado,
  devuelve lo que se cobró la primera vez. Pulsar dos veces sin señal no
  cobra dos veces. `Idempotency-Key` es la segunda red.
- **Usa un único instante** para cotizar y para registrar la salida, para
  que el importe cobrado y el registrado no puedan discrepar.
- **Lo que se cobra sale del snapshot del ticket**, no de las tablas,
  aunque el administrador cambie las tarifas con el carro adentro.

Una placa que ya está adentro **advierte, no bloquea** (D6): la API
responde 409 con el ticket existente y el operario decide si fue un error
de digitación o son dos vehículos.

## Caja y reportes

El arqueo responde una sola pregunta: **¿cuadra el cajón?** Cuatro
decisiones hacen que ese número signifique algo:

- **Solo cuenta efectivo.** Una tarjeta no llega al cajón; sumarla haría
  que todos los turnos aparecieran descuadrados. Se reporta aparte.
- **Suma el cobro, no lo que entregó el cliente.** Los $50.000 con los que
  paga un servicio de $9.000 dejan $9.000 en la caja: el resto salió como
  cambio.
- **`esperado` se congela al cerrar.** Si se recalculara, una anulación
  posterior descuadraría un turno que ya había cuadrado.
- **El conteo es a ciegas.** Mientras el turno está abierto, el operario no
  ve cuánto debería haber. Si lo viera, teclearía ese número al cerrar y el
  arqueo no mediría nada. Quien tiene `cash:read` sí lo ve siempre, y el
  operario ve la diferencia después de confirmar su conteo.

Cobrar sin turno abierto **no se bloquea** —sería dejar tirado al operario
a mitad de jornada— pero el pago queda sin turno y el resumen lo señala
aparte, para que el dueño lo vea en vez de que desaparezca.

Los reportes (`/t/{slug}/reportes`) agregan en SQL y agrupan por la hora de
la sede: un turno que termina a la 1 de la mañana pertenece al día anterior
para quien lo trabajó. Hay export CSV.

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
- **Fase 2** — catálogos parametrizables, motor de tarifas y simulador.
- **Fase 3** — ingreso, búsqueda por placa, cobro idempotente y recibo.
- **Fase 4** — turnos de caja, arqueo a ciegas y reportes.

220 pruebas, la mayoría contra Postgres real. Incluyen el criterio de
aceptación de la fase 1 —un tenant no lee ni un registro de otro ni
forzando identificadores—, la batería de tarifas del motor, el cobro
concurrente y la aritmética del arqueo.

Sigue la **fase 5**: mensualidades, PWA con cola de sincronización para
trabajar sin señal, e impresión térmica.
