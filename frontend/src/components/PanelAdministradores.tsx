import { useState } from 'react';

/**
 * Administradores de la plataforma.
 *
 * Estas cuentas ven los datos de todos los clientes, así que la lista se
 * mantiene corta a propósito y quitar la marca es explícito.
 */

interface Admin {
  id: string;
  email: string;
  nombre: string;
  is_active: boolean;
  last_login_at: string | null;
}

const CAMPO =
  'w-full rounded-zp border-2 border-outline bg-surface-container-lowest px-3 py-2 ' +
  'text-zp-body text-on-surface';

export default function PanelAdministradores({
  iniciales, yo,
}: { iniciales: Admin[]; yo: string }) {
  const [admins, setAdmins] = useState(iniciales);
  const [creando, setCreando] = useState(false);
  const [datos, setDatos] = useState({ email: '', nombre: '', password: '' });
  const [error, setError] = useState('');
  const [ocupado, setOcupado] = useState(false);

  async function pedir(ruta: string, opciones?: RequestInit) {
    setOcupado(true);
    setError('');
    try {
      const res = await fetch(`/api/v1/admin${ruta}`, opciones);
      const cuerpo = res.status === 204 ? null : await res.json();
      if (!res.ok) {
        const d = cuerpo?.detail;
        setError(typeof d === 'string' ? d : (d?.[0]?.msg ?? 'No se pudo completar'));
        return null;
      }
      return cuerpo ?? true;
    } catch {
      setError('Sin conexión con el servidor');
      return null;
    } finally {
      setOcupado(false);
    }
  }

  async function crear(e: React.FormEvent) {
    e.preventDefault();
    const creado = await pedir('/usuarios', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(datos),
    });
    if (creado) {
      setAdmins([...admins, creado]);
      setDatos({ email: '', nombre: '', password: '' });
      setCreando(false);
    }
  }

  async function quitar(a: Admin) {
    const ok = await pedir(`/usuarios/${a.id}`, { method: 'DELETE' });
    if (ok) setAdmins(admins.filter((x) => x.id !== a.id));
  }

  return (
    <div className="space-y-5">
      <p className="rounded-zp border-2 border-warning bg-surface-container-lowest px-4 py-3
                    text-zp-body">
        Estas cuentas ven y modifican los datos de <strong>todos</strong> los clientes.
        Conviene que sean las menos posibles.
      </p>

      <div className="flex flex-wrap items-center justify-between gap-4">
        <h2 className="text-zp-lg font-extrabold">
          {admins.length} {admins.length === 1 ? 'administrador' : 'administradores'}
        </h2>
        <button
          onClick={() => { setCreando(!creando); setError(''); }}
          className="rounded-zp border-2 border-outline bg-primary px-5 py-2 text-zp-body
                     font-extrabold uppercase tracking-wide text-on-primary"
        >
          {creando ? 'Cancelar' : 'Nuevo administrador'}
        </button>
      </div>

      {creando && (
        <form onSubmit={crear}
              className="space-y-4 rounded-zp border-2 border-outline
                         bg-surface-container-lowest p-5">
          <div className="grid gap-4 md:grid-cols-3">
            {([
              ['Nombre', 'nombre', 'text'],
              ['Correo', 'email', 'email'],
              ['Contraseña', 'password', 'text'],
            ] as const).map(([etiqueta, clave, tipo]) => (
              <label key={clave} className="block space-y-1.5">
                <span className="text-zp-caption font-bold uppercase tracking-wide
                                 text-on-surface-variant">{etiqueta}</span>
                <input
                  type={tipo} required value={datos[clave]}
                  onChange={(e) => setDatos({ ...datos, [clave]: e.target.value })}
                  className={CAMPO}
                />
              </label>
            ))}
          </div>
          <p className="text-zp-caption text-on-surface-variant">
            Si el correo ya pertenece a un usuario de algún parqueadero, se le añade la
            marca de plataforma en vez de duplicar la persona.
          </p>
          {error && (
            <p role="alert" className="rounded-zp border-2 border-error px-4 py-3 text-zp-body
                                       font-semibold text-error">{error}</p>
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

      {error && !creando && (
        <p role="alert" className="rounded-zp border-2 border-error bg-surface-container-lowest
                                   px-4 py-3 text-zp-body font-semibold text-error">{error}</p>
      )}

      <div className="overflow-x-auto rounded-zp border-2 border-outline
                      bg-surface-container-lowest">
        <table className="w-full min-w-max border-collapse text-left">
          <thead>
            <tr className="border-b-2 border-outline">
              {['Nombre', 'Correo', 'Último ingreso', ''].map((h) => (
                <th key={h} className="px-4 py-3 text-zp-caption font-bold uppercase
                                       tracking-wide text-on-surface-variant">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {admins.map((a) => (
              <tr key={a.id} className="border-b border-outline-variant last:border-0">
                <td className="px-4 py-3 text-zp-body font-bold">
                  {a.nombre}
                  {a.id === yo && (
                    <span className="ml-2 rounded-zp border-2 border-outline-variant px-2
                                     py-0.5 text-zp-caption font-bold">tú</span>
                  )}
                </td>
                <td className="px-4 py-3 text-zp-body text-on-surface-variant">{a.email}</td>
                <td className="px-4 py-3 text-zp-body text-on-surface-variant">
                  {a.last_login_at
                    ? new Date(a.last_login_at).toLocaleString('es-CO')
                    : 'nunca'}
                </td>
                <td className="px-4 py-3 text-right">
                  {a.id !== yo && (
                    <button
                      onClick={() => quitar(a)}
                      disabled={ocupado}
                      className="rounded-zp border-2 border-error px-3 py-1.5 text-zp-caption
                                 font-bold uppercase tracking-wide text-error"
                    >
                      Quitar
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
