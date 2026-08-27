# ZonePark — Documento de producto

**Estado:** fases 0 a 4 en funcionamiento · 220 pruebas automatizadas
**Última revisión:** 2026-08-27

Este documento describe **lo que el producto hace hoy**. Para el detalle de
implementación está [`PLAN.md`](PLAN.md); para el historial de decisiones
cerradas, [`DECISIONES.md`](DECISIONES.md); para levantarlo, el
[`README`](../README.md).

---

## 1. Qué es

Un sistema para administrar parqueaderos, en la nube y multicliente: una
sola instalación atiende a varias empresas de parqueaderos sin que ninguna
pueda ver los datos de otra.

Está construido alrededor de una idea: **el operario de la caseta es el
usuario principal**, no el administrador. Trabaja de pie, con una mano,
bajo el sol y con conexión intermitente. Todo lo demás —tarifas, reportes,
usuarios— existe para que ese momento funcione.

## 2. A quién sirve

| Quién | Qué necesita | Dónde lo hace |
|---|---|---|
| **Operario** | Registrar un ingreso en segundos, encontrar un vehículo por la placa, cobrar sin equivocarse, cuadrar su caja | Celular o tablet en la caseta |
| **Supervisor** | Configurar tarifas, ver cómo va la sede, revisar turnos | Tablet o escritorio |
| **Dueño** | Saber cuánto entró, si la caja cuadra, qué operario descuadra | Escritorio |
| **Proveedor de la plataforma** | Dar de alta clientes nuevos sin tocar código | Administración |

## 3. El problema

Los parqueaderos pequeños y medianos llevan la operación en papel o en
hojas de cálculo. Eso produce tres problemas concretos:

1. **La tarifa se calcula a mano.** "Hora o fracción" con tope diario y
   tarifa nocturna es aritmética que un humano hace mal a las 11 de la
   noche. Cada error es plata perdida o un cliente molesto.
2. **La caja no se puede auditar.** Al final del turno hay un fajo de
   billetes y ninguna forma de saber si sobra o falta.
3. **Cambiar una tarifa es un evento.** Hay que avisar, imprimir, y confiar
   en que nadie siga cobrando la vieja.

## 4. Qué hace hoy

### 4.1 Tarifas parametrizables

Todo se configura desde la aplicación. Ningún cambio de precio, tipo de
vehículo o regla de cobro requiere tocar código ni desplegar.

**Siete modos de cobro:** por minuto · por bloque · primer bloque y luego
por minuto · escalonado · tarifa plena · por día · mensualidad *(declarado,
sin implementar)*.

El modo más usado —"hora o fracción"— es el mismo que "media hora o
fracción" y que "por minuto": cambia un número, no el código.

**Encima van modificadores**, todos por regla: minutos de cortesía, cobro
mínimo, tope por cada 24 horas, redondeo a múltiplos de efectivo, IVA
incluido o agregado, y escalones con tramos.

**Y franjas de aplicación:** tarifa nocturna, de fin de semana, de festivo.
Una estadía que cruza franjas se parte y cada tramo se cobra con su regla.

**Los tipos de vehículo y los artículos son catálogos del cliente**, no
listas fijas. Un parqueadero define carro, moto y bicicleta; otro añade
patineta y camioneta. Cada tipo decide si exige placa.

**Simulador:** antes de publicar una tarifa se puede cotizar contra ella
—incluso en borrador— con casos reales. Es la red de seguridad para que
nadie descubra un error cobrando.

### 4.2 Operación

- Registro de ingreso con tipo de vehículo en botones y placa
- Búsqueda por coincidencia parcial: se teclean los últimos dígitos
- Tiempo y valor actualizándose en vivo mientras el vehículo está adentro
- Artículos adicionales (casco, lavada) con su precio congelado al añadirlos
- Cobro en efectivo, tarjeta, QR o transferencia, con cálculo del cambio
- Recibo en pantalla, compartible por WhatsApp
- Anulación de tickets, con motivo y permiso aparte

### 4.3 Caja

- Apertura de turno con base para dar cambio
- Movimientos manuales de efectivo (entra y sale plata)
- Cierre con **conteo a ciegas** y cálculo de la diferencia
- Los cobros se atan solos al turno abierto del operario

### 4.4 Reportes

- Ocupación en tiempo real, por sede y tipo de vehículo
- Ingresos por día, forma de pago y tipo de vehículo, con rango de fechas
- Turnos que no cuadraron, del descuadre más grande al más pequeño
- Descarga en CSV

### 4.5 Usuarios y accesos

22 permisos agrupados en 4 roles de sistema, editables por cada cliente:

| Rol | Permisos | Alcance |
|---|---|---|
| `tenant_admin` | 22 | Todo dentro de su empresa |
| `manager` | 16 | Opera y configura tarifas; no gestiona usuarios |
| `operator` | 6 | Registra, cobra y maneja su turno |
| `auditor` | 10 | Solo lectura, incluida la bitácora |

Los roles se asignan **por sede**: un operario de la Sede Norte no ve los
tickets de la Sede Sur aunque sean de la misma empresa.

**Ingreso rápido con PIN** de seis dígitos sobre un dispositivo registrado,
con política configurable por sede: donde el dispositivo es de la empresa el
PIN dura semanas; donde es el celular del operario se exige contraseña en
cada turno. El administrador puede revocar un dispositivo en remoto.

Toda acción sensible queda en una bitácora de auditoría.

## 5. Reglas de negocio que no son obvias

Estas son las que sorprenden a quien llega nuevo, y cada una tiene su
prueba automatizada.

### El ticket congela su tarifa al abrirse

Cuando entra un vehículo se guarda una copia de las reglas tarifarias que
le aplican. Si el administrador sube el precio mientras el carro está
adentro, ese ticket se sigue cobrando con lo que se le prometió al cliente
al entrar. Lo mismo con el precio de cada artículo, congelado al añadirlo.

Al cerrar se guarda además el desglose completo del recibo. Es redundante
con lo que el sistema sabría recalcular, y es deliberado: el papel que se
le dio al cliente tiene que poder reproducirse años después.

### Cobrar dos veces es imposible

El operario en una caseta con mala señal pulsa "cobrar", no ve respuesta y
vuelve a pulsar. El sistema bloquea el ticket y, si ya estaba cerrado,
devuelve el mismo recibo en lugar de cobrar otra vez. No depende de que la
aplicación mande nada especial: es el comportamiento por defecto.

### Los modificadores salen de la regla de entrada

Aunque la estadía cruce de tarifa diurna a nocturna, la cortesía, el cobro
mínimo y el tope son los de la regla vigente **cuando entró**. Si
dependieran del tramo, bastaría con entrar justo antes de un cambio de
franja para elegir el más conveniente.

### Solo se parten por franja los modos por unidad de tiempo

El escalonado, la tarifa plena y "primera hora completa" se refieren a la
*posición* dentro de la estadía. Partirlos por franjas daría resultados que
nadie sabría explicarle a un cliente, así que usan la regla de entrada para
toda la estadía.

### Una placa repetida advierte, no bloquea

Si se registra una placa que ya está adentro, el sistema muestra el ticket
existente y desde cuándo, y ofrece tres salidas: es el mismo vehículo, son
dos distintos, o me equivoqué al digitar. Casi siempre es lo tercero, y
bloquear al operario por eso sería peor que el problema.

### El conteo de caja es a ciegas

Mientras el turno está abierto, el operario **no ve** cuánto debería haber
en el cajón. Si lo viera, teclearía ese número al cerrar y el arqueo no
mediría nada. Ve la base, cuántos tickets lleva y sus movimientos; la
diferencia aparece después de confirmar su conteo, que es cuando le sirve.
El supervisor sí lo ve siempre.

### El arqueo solo cuenta efectivo

Una tarjeta no llega al cajón. Incluirla haría que todos los turnos
aparecieran descuadrados. Se reporta aparte. Y de un cobro en efectivo se
suma el cobro, no lo que entregó el cliente: el cambio ya salió de la caja.

### El esperado se congela al cerrar el turno

Si se recalculara, una anulación posterior descuadraría un turno que ya
había cuadrado, sin que nadie hubiera tocado el cajón.

## 6. Aislamiento entre clientes

Es el requisito del que depende todo lo demás: **una empresa no puede ver
ni un solo registro de otra, ni forzando identificadores.**

No se confía en que las consultas recuerden filtrar. Son tres capas:

1. Cada tabla del cliente lleva su identificador de empresa.
2. Políticas de seguridad a nivel de fila en la base de datos.
3. Un rol de base de datos sin privilegios de dueño, que la aplicación
   adopta en cada transacción de cliente. El dueño de las tablas esquiva
   las políticas; ese rol no.

Si nadie fija la empresa activa, **no se ve ninguna fila**: falla cerrado,
no abierto. Hay pruebas automatizadas que lo verifican, incluida la de
intentar leer y escribir datos ajenos con el identificador exacto.

Efecto secundario deseable: unas credenciales válidas de una empresa
**no funcionan** en la dirección de otra. El usuario sencillamente no
existe desde ahí.

## 7. Qué no hace (fuera de alcance actual)

Decidido a propósito, no olvidado:

| No hace | Por qué |
|---|---|
| **Facturación electrónica (DIAN)** | D4. El modelo ya lleva los campos fiscales para conectarla sin migrar datos, pero es un proyecto en sí mismo. |
| **Mensualidades** | D2. Las tablas y el modo de cobro están contemplados; falta la interfaz y el cobro recurrente. |
| **Control de aforo** | D7. No lleva cuenta de cupos disponibles ni bloquea el ingreso por lleno. |
| **Impresión térmica** | D5. El recibo va en pantalla y se comparte; no imprime en papel. |
| **Celdas identificadas (A-01, B-14)** | No se asigna puesto concreto ni hay mapa de la sede. |
| **Operar sin señal** | Si se cae la conexión, no se puede registrar. No hay cola de sincronización. |
| **Lectura de placa por cámara** | La placa se digita. |
| **Devoluciones** | Un ticket cobrado no se anula; haría falta un flujo de devolución que no existe. |
| **Integración con talanqueras** | Nada de hardware. |

## 8. Modelo conceptual

En lenguaje de negocio, no de base de datos:

- Una **empresa** tiene una o más **sedes**.
- Cada sede define su **política de dispositivos** y su prefijo de tickets.
- Una **persona** puede pertenecer a varias empresas; en cada una tiene una
  **membresía** con sus **roles**, opcionalmente limitados a ciertas sedes.
- La empresa define sus **tipos de vehículo** y sus **artículos**.
- Un **plan tarifario** agrupa **reglas** —una por tipo de vehículo y franja
  horaria—, y las reglas escalonadas tienen **tramos**. Los planes se
  versionan: activar uno archiva el anterior.
- Un **ticket** nace al entrar un vehículo, congela las reglas que le
  aplican, puede acumular **artículos**, y al cerrarse genera **cargos**
  (el desglose) y un **pago**.
- Un **turno de caja** agrupa los pagos de un operario en una sede, más sus
  **movimientos** manuales de efectivo.
- Todo lo sensible queda en la **bitácora**.

## 9. Superficie técnica

- **Frontend:** Astro en modo servidor, actuando como intermediario. La
  sesión vive en cookies que el navegador no puede leer; los tokens nunca
  llegan al cliente.
- **Backend:** FastAPI con SQLAlchemy asíncrono.
- **Base de datos:** PostgreSQL 16, con seguridad a nivel de fila.
- **Todo en contenedores**, con los puertos configurables por archivo de
  entorno.
- 23 tablas · ~30 endpoints · 220 pruebas automatizadas.

El motor de tarifas vive aislado del resto: son funciones puras, sin base
de datos ni servidor, que se prueban solas. Es donde está el 70% del valor
del producto y el 90% de los errores posibles.

## 10. Cómo se sabe que funciona

Las 220 pruebas corren contra un PostgreSQL real, no contra un doble: lo
que más importa verificar —el aislamiento entre clientes— vive en la base
de datos.

Cubren, entre otras cosas:

- Que una empresa no lea ni escriba datos de otra, ni forzando identificadores
- La batería completa de tarifas, con casos reales de parqueaderos
- Que dos ingresos simultáneos no repitan consecutivo
- Que reintentar un cobro no cobre dos veces
- Que subir una tarifa no altere un ticket ya abierto
- La aritmética del arqueo, regla por regla
- Que el operario no vea el esperado antes de contar

## 11. Lo que sigue

En orden de valor, a mi juicio:

1. **Operar sin señal.** Es el problema más real de una caseta. Requiere
   convertir la aplicación en instalable y encolar los ingresos hechos sin
   conexión.
2. **Mensualidades.** Lo pide casi cualquier parqueadero con clientes fijos.
3. **Devoluciones.** Hoy un cobro equivocado no tiene salida limpia.
4. **Impresión térmica**, si el cliente la exige.
5. **Facturación electrónica**, cuando el volumen lo justifique.
