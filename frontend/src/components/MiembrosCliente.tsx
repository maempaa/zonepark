import { useState } from 'react';

/** Personas de un cliente, vistas desde la plataforma. */

interface Miembro {
  user_id: string;
  membership_id: string;
  email: string;
  nombre: string;
  roles: string[];
  activo: boolean;
}

const ROLES: Array<[string, string]> = [
  ['tenant_admin', 'Administrador'],
  ['manager', 'Supervisor'],
  ['operator', 'Operario'],
  ['auditor', 'Auditor'],
];

const CAMPO =
  'w-full rounded-zp border-2 border-outline bg-surface-container-lowest px-3 py-2 ' +
  'text-zp-body text-on-surface';

export default function MiembrosCliente({
  tenantId, iniciales,
}: { tenantId: string; iniciales: Miembro[] }) {
  const [miembros, setMiembros] = useState(iniciales);
  const [creando, setCreando] = useState(false);
  const [datos, setDatos] = useState({
    email: '', nombre: '', password: '', rol: 'operator',
  });
  const [error, setError] = useState('');
  const [ocupado, setOcupado] = useState(false);

  async function crear(e: React.FormEvent) {
    e.preventDefault();
    setOcupado(true);
    setError('');
    try {
      const res = await fetch(`/api/v1/admin/tenants/${tenantId}/usuarios`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(datos),
      });
      const cuerpo = await res.json();
      if (!res.ok) {
        const d = cuerpo?.detail;
        setError(typeof d === 'string' ? d : (d?.[0]?.msg ?? 'No se pudo crear'));
        return;
      }
      setMiembros([...miembros, cuerpo]);
      setDatos({ email: '', nombre: '', password: '', rol: 'operator' });
      setCreando(false);
    } catch {
      setError('Sin conexión con el servidor');
    } finally {
      setOcupado(false);
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <h2 className="text-zp-lg font-extrabold">
          {miembros.length} {miembros.length === 1 ? 'persona' : 'personas'}
        </h2>
        <button
          onClick={() => { setCreando(!creando); setError(''); }}
          className="rounded-zp border-2 border-outline bg-primary px-5 py-2 text-zp-body
                     font-extrabold uppercase tracking-wide text-on-primary"
        >
          {creando ? 'Cancelar' : 'Agregar persona'}
        </button>
      </div>

      {creando && (
        <form onSubmit={crear}
              className="space-y-4 rounded-zp border-2 border-outline
                         bg-surface-container-lowest p-5">
          <div className="grid gap-4 md:grid-cols-4">
            <label className="block space-y-1.5">
              <span className="text-zp-caption font-bold uppercase tracking-wide
                               text-on-surface-variant">Nombre</span>
              <input required value={datos.nombre}
                     onChange={(e) => setDatos({ ...datos, nombre: e.target.value })}
                     className={CAMPO} />
            </label>
            <label className="block space-y-1.5">
              <span className="text-zp-caption font-bold uppercase tracking-wide
                               text-on-surface-variant">Correo</span>
              <input type="email" required value={datos.email}
                     onChange={(e) => setDatos({ ...datos, email: e.target.value })}
                     className={CAMPO} />
            </label>
            <label className="block space-y-1.5">
              <span className="text-zp-caption font-bold uppercase tracking-wide
                               text-on-surface-variant">Contraseña</span>
              <input required value={datos.password}
                     onChange={(e) => setDatos({ ...datos, password: e.target.value })}
                     className={CAMPO} />
              <span className="block text-zp-caption text-on-surface-variant">
                mínimo 12 caracteres
              </span>
            </label>
            <label className="block space-y-1.5">
              <span className="text-zp-caption font-bold uppercase tracking-wide
                               text-on-surface-variant">Rol</span>
              <select value={datos.rol}
                      onChange={(e) => setDatos({ ...datos, rol: e.target.value })}
                      className={CAMPO}>
                {ROLES.map(([valor, texto]) => (
                  <option key={valor} value={valor}>{texto}</option>
                ))}
              </select>
            </label>
          </div>

          {error && (
            <p role="alert" className="rounded-zp border-2 border-error px-4 py-3
                                       text-zp-body font-semibold text-error">
              {error}
            </p>
          )}

          <button type="submit" disabled={ocupado}
                  className="rounded-zp border-2 border-outline bg-primary px-6 py-2.5
                             text-zp-body font-extrabold uppercase tracking-wide
                             text-on-primary disabled:bg-surface-container-high
                             disabled:text-on-surface-variant">
            {ocupado ? 'Creando…' : 'Crear'}
          </button>
        </form>
      )}

      <div className="overflow-x-auto rounded-zp border-2 border-outline
                      bg-surface-container-lowest">
        <table className="w-full min-w-max border-collapse text-left">
          <thead>
            <tr className="border-b-2 border-outline">
              {['Nombre', 'Correo', 'Roles', 'Estado'].map((h) => (
                <th key={h} className="px-4 py-3 text-zp-caption font-bold uppercase
                                       tracking-wide text-on-surface-variant">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {miembros.map((m) => (
              <tr key={m.user_id} className="border-b border-outline-variant last:border-0">
                <td className="px-4 py-3 text-zp-body font-bold">{m.nombre}</td>
                <td className="px-4 py-3 text-zp-body text-on-surface-variant">{m.email}</td>
                <td className="px-4 py-3">
                  <div className="flex flex-wrap gap-1.5">
                    {m.roles.map((r) => (
                      <span key={r} className="rounded-zp border-2 border-outline-variant
                                               px-2 py-0.5 text-zp-caption font-bold">
                        {ROLES.find(([v]) => v === r)?.[1] ?? r}
                      </span>
                    ))}
                    {m.roles.length === 0 && (
                      <span className="text-zp-caption text-on-surface-variant">sin rol</span>
                    )}
                  </div>
                </td>
                <td className="px-4 py-3">
                  <span className={`rounded-zp border-2 px-2.5 py-0.5 text-zp-caption
                                    font-bold uppercase ${
                                      m.activo
                                        ? 'border-success text-success'
                                        : 'border-error text-error'
                                    }`}>
                    {m.activo ? 'activa' : 'inactiva'}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
