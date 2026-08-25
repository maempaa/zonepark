# Decisiones tomadas

Registro de las decisiones de diseño ya cerradas. Reemplazan lo que diga
[`PLAN.md`](PLAN.md) §12. Si alguna cambia, se anota aquí con la fecha y el motivo.

| # | Decisión | Consecuencia en el código |
|---|---|---|
| D1 | **Tenant por ruta**: `/t/{slug}` | El resolvedor vive aislado en `app/core/tenancy.py` como una sola función. Cambiar a subdominios después es tocar esa función, no refactorizar. Sin DNS wildcard, sin certificado wildcard, funciona en `localhost` desde el día uno. |
| D2 | **Mensualidades en fase 5** | Las tablas `subscriptions` y el modo `SUBSCRIPTION` del motor de tarifas quedan contemplados en el diseño pero **no se implementan** en la v1. El motor se escribe con el enum completo para que agregarlas no altere migraciones existentes. |
| D3 | **Política de dispositivo configurable por sede** | `parking_lots.device_policy` = `pin_persistente` \| `login_por_turno`. Se añade tabla `devices` (dispositivo registrado, huella, última actividad) y revocación remota desde el panel de administrador. |
| D4 | **Sin facturación electrónica (DIAN)** | Recibo interno con consecutivo propio por sede. El modelo de `tenants`, `tickets` y `payments` incluye los campos fiscales (NIT, régimen, resolución) desde el inicio para que conectar un proveedor después no exija migrar datos. |
| D5 | **Recibo en pantalla + compartir** | Número de ticket grande, desglose y botón de compartir (PDF/imagen vía Web Share API). Sin Web Bluetooth ni ESC/POS en la v1. |
| D6 | **Placa repetida: advertir y continuar** | Al registrar un ingreso, si hay un ticket abierto con esa placa en la sede, la API responde `409` con el ticket existente; el operario confirma con `?force=true`. No se bloquea. |
| D7 | **Sin control de aforo** | Se eliminan `zones`, `spaces` y los contadores de capacidad del modelo v1. El tablero muestra **tickets abiertos**, no "cupos disponibles". `vehicle_types` pierde el campo de cupos que ocupa. |

## Efecto neto sobre el roadmap

- **Fase 1** suma la tabla `devices` y la política por sede (D3): ~1 día extra.
- **Fase 3** se aligera: sin impresión térmica (D5) ni validación de aforo (D7).
- **Fase 5** conserva mensualidades (D2) y podría recuperar celdas identificadas si el negocio lo pide.
