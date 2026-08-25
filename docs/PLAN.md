# ZonePark — Plan de construcción

Sistema multitenant de administración de parqueaderos.
Frontend **Astro**, backend **FastAPI**, todo dockerizado con puertos parametrizados por `.env`.

---

## 1. Decisiones clave (tomadas por defecto, revisables)

| Tema | Decisión | Por qué |
|---|---|---|
| Aislamiento multitenant | **BD única + `tenant_id` en todas las tablas + Row Level Security de PostgreSQL** | Costo/operación bajo, backups simples, y RLS da una segunda barrera si un query olvida el filtro. Schema-por-tenant solo si aparece un cliente con exigencia regulatoria. |
| Base de datos | PostgreSQL 16 | RLS, tipos `numeric` exactos para dinero, `tstzrange` para vigencias de tarifas. |
| Dinero | `NUMERIC(14,2)` + `Decimal` en Python. Nunca `float`. | Los redondeos de tarifa deben ser exactos y auditables. |
| Auth | JWT de acceso corto (15 min) + refresh rotativo en cookie `httpOnly`, emitida por Astro como BFF | El token nunca toca `localStorage`; el móvil mantiene sesión larga sin riesgo de XSS. |
| Astro | Modo **SSR** (adapter Node) actuando como BFF/proxy hacia FastAPI | Permite cookies httpOnly, oculta la API del navegador y da HTML rápido en 3G. |
| Islas de UI | React 19 + Tailwind 4 | Solo se hidrata lo interactivo (formulario de ingreso, cronómetro, cobro). |
| Migraciones | Alembic | |
| Cache/colas | Redis (opcional desde fase 3) | Rate limiting, bloqueo de placa duplicada, jobs de cierre de caja. |

---

## 2. Arquitectura

```
              ┌──────────────── navegador móvil (PWA) ────────────────┐
              │  Astro SSR (islas React) — puerto ${WEB_PORT}         │
              │  · sesión en cookie httpOnly                          │
              │  · /api/* → proxy interno al backend                  │
              └───────────────────────┬───────────────────────────────┘
                                      │ red docker interna
              ┌───────────────────────▼───────────────────────────────┐
              │  FastAPI + SQLAlchemy 2 async — puerto ${API_PORT}    │
              │  · middleware de tenant  · RBAC  · motor de tarifas   │
              └──────────┬──────────────────────────┬─────────────────┘
                         │                          │
                 PostgreSQL ${DB_PORT}        Redis ${REDIS_PORT}
```

Un `proxy` (Caddy) opcional en `${PROXY_PORT}` para TLS y subdominios por tenant en producción.

---

## 3. Multitenancy

**Resolución del tenant** (en este orden):
1. Subdominio: `cliente.zonepark.app` → slug `cliente`.
2. Header `X-Tenant-Slug` (apps móviles / integraciones).
3. Claim `tid` del JWT — **siempre gana**: si no coincide con 1 o 2, se rechaza con 403.

**Aplicación del aislamiento**, en tres capas:
1. `TenantContext` (ContextVar) poblado por un middleware.
2. Cada request abre la sesión de BD ejecutando `SET LOCAL app.tenant_id = '<uuid>'`.
3. Políticas RLS en PostgreSQL: `USING (tenant_id = current_setting('app.tenant_id')::uuid)`.

Un usuario `superadmin` de plataforma usa un rol de BD con `BYPASSRLS`, y sus acciones quedan siempre en `audit_log`.

**Regla de oro:** ninguna consulta recibe `tenant_id` como parámetro desde el cliente. Se toma del contexto.

---

## 4. Modelo de datos

### Plataforma
- `tenants` — slug, razón social, NIT, moneda, zona horaria, estado, plan de suscripción.
- `users` — email, `password_hash` (argon2id), nombre, teléfono, MFA opcional. Un usuario puede pertenecer a varios tenants.
- `memberships` — `(user_id, tenant_id)`, estado, PIN corto para login rápido de operarios en móvil.
- `roles` — por tenant, con roles de sistema precargados.
- `permissions` — catálogo fijo (`ticket:create`, `rate:update`, `cash:close`, …).
- `role_permissions`, `membership_roles`.
- `audit_log` — actor, acción, entidad, `before`/`after` en JSONB, IP.

### Operación
- `parking_lots` (sedes) — dirección, zona horaria, capacidad, horario de atención, prefijo de consecutivo.
- `zones` / `spaces` — opcional (fase 5), para control de cupos por tipo de vehículo.
- `vehicle_types` — **parametrizable por tenant**: código, nombre, icono, `requires_plate`, `plate_pattern` (regex), cupos que ocupa, activo, orden de despliegue. Ejemplos: carro, moto, bicicleta, camioneta, patineta.
- `service_items` — **artículos/servicios parametrizables** cobrables aparte: casco, lavada, ticket perdido, candado. Precio fijo o por unidad.

### Tarifas
- `rate_plans` — nombre, sede(s) a las que aplica, `valid_from` / `valid_to`, estado (borrador/activo/archivado), `version`.
- `rate_rules` — **una por (plan, tipo de vehículo)**. Es el corazón del sistema; detalle en §5.
- `rate_tiers` — bloques escalonados de una regla (ver §5.3).
- `rate_schedules` — franjas de aplicación: días de semana, rango horario, festivo sí/no. Permite tarifa nocturna o de fin de semana.
- `holidays` — calendario por país/tenant.

### Movimiento
- `tickets` — consecutivo por sede, tipo de vehículo, placa, `entry_at`, `exit_at`, estado (`abierto|cerrado|anulado|cortesía`), operario de entrada y de salida, **`rate_snapshot` en JSONB**.
- `ticket_items` — artículos añadidos al ticket.
- `charges` — desglose línea a línea de lo calculado (`concepto, cantidad, unitario, subtotal`).
- `payments` — método (efectivo, tarjeta, QR, transferencia), monto, referencia.
- `subscriptions` (mensualidades) — cliente, tipo de vehículo, placa, vigencia, valor, estado de pago.
- `cash_shifts` — turno de caja: apertura, cierre, base, esperado vs. contado, diferencia.
- `cash_movements` — ingresos/egresos manuales del turno.

**`rate_snapshot` es innegociable:** al abrir el ticket se congela la regla tarifaria completa. Si mañana suben la tarifa, los tickets abiertos ayer se cobran con la de ayer y cualquier recálculo histórico es reproducible.

---

## 5. Motor de tarifas

Vive en `app/domain/pricing/` como **funciones puras** (sin BD, sin FastAPI). Entrada: snapshot de la regla + `entry_at` + `exit_at` + ítems. Salida: desglose de cargos. Esto es lo que se prueba exhaustivamente con `pytest`.

### 5.1 Modos de cobro (`billing_mode`)

| Modo | Fórmula | Uso típico |
|---|---|---|
| `PER_MINUTE` | `minutos × precio_minuto` | Parqueaderos de rotación alta. |
| `PER_BLOCK` | `ceil(minutos / block_minutes) × precio_bloque` | **"Hora o fracción"** con `block_minutes = 60`. También sirve para fracciones de 15 o 30 min. |
| `FIRST_THEN_PER_MINUTE` | `precio_primer_bloque + max(0, minutos − block_minutes) × precio_minuto` | Primera hora completa, luego prorrateo al minuto. |
| `TIERED` | Bloques escalonados, ver §5.3 | Primera hora cara, siguientes más baratas. |
| `FLAT` | Precio único por estadía | Eventos, tarifa plena. |
| `DAILY` | `ceil(horas / horas_día) × precio_día` | Estadías largas. |
| `SUBSCRIPTION` | Cubierto por mensualidad; excedentes al modo base | Mensualidades. |

`block_minutes` es un campo de la regla → "hora o fracción", "media hora o fracción" y "por minuto" salen todos del mismo motor cambiando un número. Sin código nuevo.

### 5.2 Modificadores (todos parametrizables por regla)

- `grace_minutes` — cortesía; por debajo de este umbral el ticket sale en $0.
- `min_charge` — cobro mínimo de la estadía.
- `max_daily_charge` — tope por cada 24 h (evita que 3 días cuesten una fortuna).
- `rounding_mode` + `rounding_step` — `up | down | nearest` a múltiplos de 50/100/500. Crítico para efectivo en COP.
- `time_rounding` — cómo se redondea la duración antes de facturar (`ceil` por defecto).
- `lost_ticket_fee` — cargo por ticket extraviado.
- `tax_mode` — precio incluye IVA o se suma; porcentaje configurable.

### 5.3 Escalones (`rate_tiers`)

Cada escalón: `desde_minuto`, `hasta_minuto` (nulo = infinito), `precio`, `unidad` (`bloque | minuto | fijo`).

Ejemplo real — "$3.000 la primera hora, $2.000 cada hora adicional, tope $20.000 al día":
```
tier 1:  0 → 60     3000  fijo
tier 2:  60 → null  2000  bloque(60)
max_daily_charge: 20000
```

### 5.4 Franjas horarias

Cuando la estadía cruza franjas (p. ej. tarifa nocturna 20:00–06:00), el motor **parte la estadía en segmentos** por franja y cobra cada uno con su regla, respetando el tope diario global. Toda la aritmética se hace en la zona horaria de la **sede**, no del servidor — con manejo explícito de cambios de horario.

### 5.5 Contrato de salida

```json
{
  "duration_minutes": 137,
  "billable_units": 3,
  "lines": [
    {"concept": "Hora o fracción (3 × $3.000)", "amount": "9000.00"},
    {"concept": "Casco", "amount": "1000.00"}
  ],
  "subtotal": "10000.00", "tax": "0.00",
  "rounding_adjustment": "0.00", "total": "10000.00",
  "applied_rule_id": "...", "rate_plan_version": 4
}
```

El endpoint `GET /tickets/{id}/quote` devuelve esto **sin cerrar el ticket** — el operario ve el valor antes de cobrar, y la app puede mostrar el acumulado en vivo.

---

## 6. Usuarios, roles y permisos

RBAC por tenant. Roles precargados, editables:

| Rol | Alcance |
|---|---|
| `platform_admin` | Global: crea tenants, ve métricas de plataforma. Fuera de RLS. |
| `tenant_admin` | Todo dentro de su tenant: sedes, tarifas, usuarios, reportes. |
| `manager` | Una o varias sedes: tarifas, cierres de caja, reportes. No gestiona usuarios. |
| `operator` | Registrar entradas/salidas, cobrar, su propio turno de caja. |
| `auditor` | Solo lectura, incluye `audit_log`. |

- Permisos como strings `recurso:acción`, verificados con una dependencia de FastAPI: `Depends(require("rate:update"))`.
- Alcance por sede: `membership_roles` puede limitarse a `parking_lot_id` específicos.
- Login de operario en móvil: email+contraseña la primera vez, luego **PIN de 6 dígitos** sobre el dispositivo ya registrado (rápido con guantes, en la caseta).
- Contraseñas con argon2id; bloqueo tras 5 intentos; todo cambio de rol o tarifa al `audit_log`.

---

## 7. API (borrador)

```
POST   /auth/login · /auth/refresh · /auth/logout · /auth/pin-login
GET    /me                                   → perfil, tenants, permisos

GET    /admin/tenants                        (platform_admin)
CRUD   /parking-lots
CRUD   /vehicle-types                        ← parametrizable
CRUD   /service-items                        ← parametrizable
CRUD   /rate-plans                           (+ POST /rate-plans/{id}/activate)
CRUD   /rate-plans/{id}/rules                ← modos, bloques, escalones
POST   /rate-plans/{id}/simulate             → prueba tarifas sin publicar
CRUD   /users · /roles

POST   /tickets                              → registrar ingreso
GET    /tickets?status=open&plate=ABC        → búsqueda rápida por placa
POST   /tickets/{id}/items                   → añadir casco, lavada…
GET    /tickets/{id}/quote                   → cotizar salida
POST   /tickets/{id}/checkout                → cerrar + cobrar (idempotente)
POST   /tickets/{id}/void                    → anular (requiere permiso + motivo)

CRUD   /subscriptions
POST   /cash-shifts/open · /cash-shifts/{id}/close
GET    /reports/occupancy · /reports/revenue · /reports/shift/{id}
GET    /audit-log
```

`POST /checkout` acepta `Idempotency-Key`: si el móvil pierde señal y reintenta, no se cobra dos veces.

---

## 8. Frontend Astro, orientado a móvil

**Principio:** el operario trabaja de pie, con una mano, bajo el sol, con conexión mala. Cada pantalla debe resolverse en 2 toques.

Pantallas:
1. **Login / PIN** — teclado numérico grande.
2. **Tablero de sede** — cupos libres por tipo de vehículo, tickets abiertos, botón flotante "Ingresar".
3. **Ingreso** — selector de tipo de vehículo en botones grandes con icono, teclado de placa, guardar. Menos de 5 segundos.
4. **Buscar / Salida** — búsqueda por placa incremental (últimos 3 dígitos), tarjeta con tiempo transcurrido y valor en vivo, botón "Cobrar".
5. **Cobro** — desglose, método de pago, cambio a devolver, imprimir/compartir recibo.
6. **Caja** — apertura, movimientos, cierre con conteo y diferencia.
7. **Configuración** (tablet/escritorio) — tipos de vehículo, planes tarifarios con simulador en vivo, usuarios y roles.

Detalles técnicos:
- Astro SSR: las pantallas de configuración y reportes son HTML puro; solo se hidratan las islas de ingreso, cotización y cobro.
- **PWA instalable** con service worker: cachea el shell y **encola ingresos hechos sin señal** para sincronizar (fase 5).
- Touch targets ≥ 48 px, `font-size` ≥ 16 px (evita el zoom de iOS), `inputmode="numeric"` en placas, modo alto contraste para pantalla al sol.
- Recibo: impresión térmica vía Web Bluetooth o compartir PDF/WhatsApp.

---

## 9. Docker y configuración

`docker-compose.yml` — servicios `db`, `redis`, `api`, `web`, `proxy` (perfil `prod`). Ningún puerto escrito a mano.

`.env.example`:
```dotenv
# ── Puertos (todos parametrizados) ──────────────
WEB_PORT=4321
API_PORT=8000
DB_PORT=5432
REDIS_PORT=6379
PROXY_PORT=8080

# ── Base de datos ───────────────────────────────
POSTGRES_USER=zonepark
POSTGRES_PASSWORD=changeme
POSTGRES_DB=zonepark
DATABASE_URL=postgresql+asyncpg://zonepark:changeme@db:5432/zonepark

# ── Seguridad ───────────────────────────────────
JWT_SECRET=changeme
ACCESS_TOKEN_MINUTES=15
REFRESH_TOKEN_DAYS=30
CORS_ORIGINS=http://localhost:4321

# ── Aplicación ──────────────────────────────────
APP_ENV=development
DEFAULT_TIMEZONE=America/Bogota
DEFAULT_CURRENCY=COP
DEFAULT_ROUNDING_STEP=50
PUBLIC_API_BASE_URL=http://localhost:8000   # navegador
INTERNAL_API_BASE_URL=http://api:8000       # SSR dentro de la red docker
```

Detalles:
- `api` y `web` con Dockerfile multi-stage: etapa `dev` con hot reload y volumen montado; etapa `prod` con imagen delgada y usuario no-root.
- Healthchecks en los cuatro servicios; `api` espera a que `db` esté sano.
- Las migraciones de Alembic corren al arrancar el contenedor `api` en dev, y como job aparte en prod.
- `Makefile`: `make up`, `make down`, `make migrate`, `make seed`, `make test`, `make logs`.

---

## 10. Estructura de carpetas

```
zonepark/
├─ docker-compose.yml · docker-compose.override.yml · .env.example · Makefile
├─ backend/
│  ├─ Dockerfile · pyproject.toml · alembic/
│  └─ app/
│     ├─ main.py · config.py · deps.py
│     ├─ core/            auth, security, rbac, tenancy, errors
│     ├─ domain/pricing/  engine.py, modes.py, rounding.py, schedules.py  ← puro
│     ├─ models/          SQLAlchemy
│     ├─ schemas/         Pydantic v2
│     ├─ api/v1/          routers
│     ├─ services/        casos de uso (checkout, cash_shift, …)
│     └─ tests/           unit (pricing) + integration (API)
└─ frontend/
   ├─ Dockerfile · astro.config.mjs · tailwind.config
   └─ src/
      ├─ pages/           rutas SSR + /api proxy (BFF)
      ├─ components/      islas React
      ├─ lib/             cliente API, sesión, formato de moneda
      └─ styles/
```

---

## 11. Roadmap

**Fase 0 — Andamiaje (2–3 días)**
Compose con los 5 servicios, puertos por `.env`, Astro y FastAPI hablándose, healthchecks, Alembic inicial, CI con lint + tests.

**Fase 1 — Tenancy, usuarios y roles (1 semana)**
Tablas de plataforma, RLS activo, JWT + refresh, RBAC, seed de roles, login móvil con PIN, `audit_log`. **Prueba de aceptación:** el tenant A no puede leer un solo registro del tenant B, ni siquiera forzando IDs.

**Fase 2 — Parametrización y motor de tarifas (1.5 semanas)**
CRUD de sedes, tipos de vehículo, artículos, planes y reglas. Motor de tarifas con los 7 modos, modificadores, escalones y franjas. Suite de pruebas con casos reales. Endpoint `simulate` + simulador en la UI. *Esta es la fase de mayor riesgo — se construye antes que la operación.*

**Fase 3 — Operación (1.5 semanas)**
Ingreso, búsqueda por placa, cotización en vivo, checkout idempotente, artículos, anulaciones, pagos, recibo. Pantallas móviles con las islas hidratadas.

**Fase 4 — Caja y reportes (1 semana)**
Turnos, arqueo, movimientos, reportes de ocupación e ingresos, exportar CSV/XLSX.

**Fase 5 — Extras (continuo)**
Mensualidades, control de cupos por zona, PWA offline con cola de sincronización, impresión térmica, lectura de placa por cámara (OCR), tablero para el dueño, integración con talanqueras.

---

## 12. Riesgos y puntos a decidir

1. **Complejidad tarifaria.** Es el 70% del valor y el 90% de los bugs potenciales. Mitigación: motor puro + batería de pruebas escritas *antes* del código, con tarifas reales de parqueaderos existentes.
2. **Zonas horarias y horario de verano.** Todo en UTC en BD, aritmética en la zona de la sede. Prueba explícita de una estadía que cruza medianoche y cambio de hora.
3. **Doble cobro por reintentos.** Resuelto con `Idempotency-Key` + transición de estado del ticket bajo bloqueo de fila.
4. **Fuga entre tenants.** Mitigada con RLS; prueba automatizada de aislamiento en CI, no manual.
5. **Placas duplicadas abiertas.** Definir política por tenant: bloquear, advertir o permitir.

**Decisiones que necesito de ti:**
- ¿Tenant por subdominio (`cliente.zonepark.app`) o por ruta (`/t/cliente`)? El subdominio necesita DNS wildcard.
- ¿El operario trabaja en su propio celular o en un dispositivo de la empresa? Cambia la política del PIN.
- ¿Hace falta facturación electrónica (DIAN u otro) desde el inicio?
- ¿Impresión de tickets con impresora térmica, o basta con el número en pantalla?
- ¿Mensualidades en fase 5, o son requisito de la primera versión?
