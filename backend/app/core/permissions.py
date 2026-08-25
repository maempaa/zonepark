"""Catálogo de permisos de la plataforma.

Es fijo: el cliente no inventa permisos, solo combina los existentes en
roles. La forma es `recurso:acción`.

Los permisos de las fases 2 a 4 ya están declarados para que los roles de
sistema no tengan que reasignarse cuando esas funciones lleguen.
"""

from typing import NamedTuple


class Permiso(NamedTuple):
    codigo: str
    grupo: str
    descripcion: str


PERMISOS: list[Permiso] = [
    # Configuración del tenant
    Permiso("tenant:read", "tenant", "Ver la configuración del tenant"),
    Permiso("tenant:update", "tenant", "Editar la configuración del tenant"),
    # Sedes
    Permiso("lot:read", "sedes", "Ver las sedes"),
    Permiso("lot:manage", "sedes", "Crear, editar y desactivar sedes"),
    # Personas y accesos
    Permiso("user:read", "usuarios", "Ver los usuarios del tenant"),
    Permiso("user:manage", "usuarios", "Invitar, editar y desactivar usuarios"),
    Permiso("role:read", "usuarios", "Ver los roles"),
    Permiso("role:manage", "usuarios", "Crear y editar roles y sus permisos"),
    Permiso("device:read", "usuarios", "Ver los dispositivos registrados"),
    Permiso("device:revoke", "usuarios", "Revocar un dispositivo en remoto"),
    # Parametrización (fase 2)
    Permiso("vehicle_type:manage", "parametrizacion", "Definir tipos de vehículo"),
    Permiso("service_item:manage", "parametrizacion", "Definir artículos y servicios"),
    Permiso("rate:read", "tarifas", "Ver los planes tarifarios"),
    Permiso("rate:manage", "tarifas", "Crear, editar y activar planes tarifarios"),
    # Operación (fase 3)
    Permiso("ticket:read", "operacion", "Consultar tickets"),
    Permiso("ticket:create", "operacion", "Registrar el ingreso de un vehículo"),
    Permiso("ticket:checkout", "operacion", "Cerrar un ticket y cobrar"),
    Permiso("ticket:void", "operacion", "Anular un ticket"),
    # Caja (fase 4)
    Permiso("cash:operate", "caja", "Abrir y cerrar el propio turno de caja"),
    Permiso("cash:read", "caja", "Ver los turnos de caja de la sede"),
    # Transversal
    Permiso("report:read", "reportes", "Ver reportes"),
    Permiso("audit:read", "auditoria", "Ver la bitácora de auditoría"),
]

TODOS = [p.codigo for p in PERMISOS]


class RolSistema(NamedTuple):
    codigo: str
    nombre: str
    descripcion: str
    permisos: list[str]


ROLES_SISTEMA: list[RolSistema] = [
    RolSistema(
        "tenant_admin",
        "Administrador",
        "Control total dentro del tenant.",
        TODOS,
    ),
    RolSistema(
        "manager",
        "Supervisor",
        "Opera y configura tarifas de sus sedes, pero no gestiona usuarios.",
        [
            "tenant:read", "lot:read",
            "user:read", "role:read", "device:read",
            "vehicle_type:manage", "service_item:manage",
            "rate:read", "rate:manage",
            "ticket:read", "ticket:create", "ticket:checkout", "ticket:void",
            "cash:operate", "cash:read",
            "report:read",
        ],
    ),
    RolSistema(
        "operator",
        "Operario",
        "Registra entradas y salidas, cobra y maneja su turno de caja.",
        [
            "lot:read",
            "rate:read",
            "ticket:read", "ticket:create", "ticket:checkout",
            "cash:operate",
        ],
    ),
    RolSistema(
        "auditor",
        "Auditor",
        "Solo lectura, incluida la bitácora.",
        [
            "tenant:read", "lot:read", "user:read", "role:read", "device:read",
            "rate:read", "ticket:read", "cash:read", "report:read", "audit:read",
        ],
    ),
]

# Verificación en tiempo de importación: un permiso mal escrito en un rol
# es un fallo silencioso muy difícil de ver después.
_desconocidos = {
    p for rol in ROLES_SISTEMA for p in rol.permisos if p not in set(TODOS)
}
if _desconocidos:
    raise RuntimeError(f"Permisos inexistentes en ROLES_SISTEMA: {sorted(_desconocidos)}")
