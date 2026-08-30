import { useState } from 'react';

/**
 * Clientes de la plataforma.
 *
 * Tabla, no tarjetas: esto se mira en un escritorio y lo que importa es
 * comparar filas de un vistazo, no leer una a una.
 *
 * Crear un cliente pide de golpe todo lo que hace falta para que opere
 * —identificador, sede y un administrador— porque el backend lo crea en
 * una sola transacción. Un cliente a medias no serviría de nada.
 */

interface Cliente {
  id: string;
  slug: string;
  nombre: string;
  status: string;
  sedes: number;
  usuarios: number;
  adentro: number;
}

const VACIO = {
  slug: '',
  nombre: '',
  razon_social: '',
  nit: '',
  sede_codigo: 'S1',
  sede_nombre: 'Sede principal',
  admin_email: '',
  admin_nombre: '',
  admin_password: '',
};

const CAMPO =
  'w-full rounded-zp border-2 border-outline bg-surface-container-lowest px-3 py-2 ' +
  'text-zp-body text-on-surface';

function Icono({ d }: { d: string }) {
  return (
    <svg viewBox="0 0 24 24" className="h-5 w-5 shrink-0" fill="none" stroke="currentColor"
         strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {d.split('|').map((p, i) => <path key={i} d={p} />)}
    </svg>
  );
}
const ALERTA = 'M12 7v6|M12 16.5v.01';
const CHECK = 'm4 12 6 6L20 6';

export default function PanelClientes({ iniciales }: { iniciales: Cliente[] }) {
  const [clientes, setClientes] = useState(iniciales);
  const [creando, setCreando] = useState(false);
  const [datos, setDatos] = useState({ ...VACIO });
  const [error, setError] = useState('');
  const [aviso, setAviso] = useState('');
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

  async function recargar() {
    const lista = await pedir('/tenants');
    if (lista) setClientes(lista);
  }

  async function crear(e: React.FormEvent) {
    e.preventDefault();
    setAviso('');
    const cuerpo = Object.fromEntries(
      Object.entries(datos).filter(([, v]) => v !== ''),
    );
    const creado = await pedir('/tenants', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(cuerpo),
    });
    if (creado) {
      await recargar();
      setCreando(false);
      setDatos({ ...VACIO });
      setAviso(`Cliente "${creado.nombre}" creado. Su administrador ya puede entrar.`);
    }
  }

  async function alternarEstado(c: Cliente) {
    const nuevo = c.status === 'activo' ? 'suspendido' : 'activo';
    const ok = await pedir(`/tenants/${c.id}`, {
      method: 'PATCH',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ status: nuevo }),
    });
    if (ok) {
      setClientes((cs) => cs.map((x) => (x.id === c.id ? { ...x, status: nuevo } : x)));
      setAviso(
        nuevo === 'suspendido'
          ? `"${c.nombre}" queda suspendido: nadie de ese parqueadero podrá entrar.`
          : `"${c.nombre}" vuelve a estar activo.`,
      );
    }
  }

  return (
    <div className="space-y-6">
      {(error || aviso) && (
        <p role="alert"
           className={`flex items-start gap-3 rounded-zp border-2 bg-surface-container-lowest
                       px-4 py-3 text-zp-body font-semibold ${
                         error ? 'border-error text-error' : 'border-success text-success'
                       }`}>
          <Icono d={error ? ALERTA : CHECK} />
          <span>{error || aviso}</span>
        </p>
      )}

      <div className="flex flex-wrap items-center justify-between gap-4">
        <h2 className="text-zp-lg font-extrabold">
          {clientes.length} {clientes.length === 1 ? 'cliente' : 'clientes'}
        </h2>
        <button
          onClick={() => { setCreando(!creando); setError(''); setAviso(''); }}
          className="rounded-zp border-2 border-outline bg-primary px-5 py-2 text-zp-body
                     font-extrabold uppercase tracking-wide text-on-primary
                     active:bg-primary-container"
        >
          {creando ? 'Cancelar' : 'Nuevo cliente'}
        </button>
      </div>

      {creando && (
        <form onSubmit={crear}
              className="space-y-5 rounded-zp border-2 border-outline
                         bg-surface-container-lowest p-6">
          <div>
            <h3 className="text-zp-body font-extrabold">Datos del parqueadero</h3>
            <p className="mt-1 text-zp-caption text-on-surface-variant">
              El identificador va en la dirección: <code>/t/identificador</code>. Minúsculas,
              sin espacios, y no se puede cambiar después.
            </p>
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            <Campo etiqueta="Identificador" requerido valor={datos.slug}
                   onChange={(v) => setDatos({ ...datos, slug: v.toLowerCase().replace(/[^a-z0-9-]/g, '') })}
                   ayuda="por ejemplo: lacalera" />
            <Campo etiqueta="Nombre" requerido valor={datos.nombre}
                   onChange={(v) => setDatos({ ...datos, nombre: v })} />
            <Campo etiqueta="Razón social" valor={datos.razon_social}
                   onChange={(v) => setDatos({ ...datos, razon_social: v })} />
            <Campo etiqueta="NIT" valor={datos.nit}
                   onChange={(v) => setDatos({ ...datos, nit: v })} />
          </div>

          <div className="border-t-2 border-outline-variant pt-5">
            <h3 className="text-zp-body font-extrabold">Primera sede</h3>
            <div className="mt-4 grid gap-4 md:grid-cols-2">
              <Campo etiqueta="Código" requerido valor={datos.sede_codigo}
                     onChange={(v) => setDatos({ ...datos, sede_codigo: v.toUpperCase() })}
                     ayuda="prefijo de los tickets: S1-000042" />
              <Campo etiqueta="Nombre de la sede" requerido valor={datos.sede_nombre}
                     onChange={(v) => setDatos({ ...datos, sede_nombre: v })} />
            </div>
          </div>

          <div className="border-t-2 border-outline-variant pt-5">
            <h3 className="text-zp-body font-extrabold">Administrador del cliente</h3>
            <p className="mt-1 text-zp-caption text-on-surface-variant">
              Esta cuenta puede cambiar tarifas y ver la caja, así que la contraseña pide
              al menos 12 caracteres.
            </p>
            <div className="mt-4 grid gap-4 md:grid-cols-3">
              <Campo etiqueta="Nombre" requerido valor={datos.admin_nombre}
                     onChange={(v) => setDatos({ ...datos, admin_nombre: v })} />
              <Campo etiqueta="Correo" tipo="email" requerido valor={datos.admin_email}
                     onChange={(v) => setDatos({ ...datos, admin_email: v })} />
              <Campo etiqueta="Contraseña" tipo="text" requerido valor={datos.admin_password}
                     onChange={(v) => setDatos({ ...datos, admin_password: v })}
                     ayuda="mínimo 12 caracteres" />
            </div>
          </div>

          <button
            type="submit" disabled={ocupado}
            className="rounded-zp border-2 border-outline bg-primary px-6 py-3 text-zp-body
                       font-extrabold uppercase tracking-wide text-on-primary
                       disabled:border-outline-variant disabled:bg-surface-container-high
                       disabled:text-on-surface-variant"
          >
            {ocupado ? 'Creando…' : 'Crear cliente'}
          </button>
        </form>
      )}

      <div className="overflow-x-auto rounded-zp border-2 border-outline
                      bg-surface-container-lowest">
        <table className="w-full min-w-max border-collapse text-left">
          <thead>
            <tr className="border-b-2 border-outline">
              {['Parqueadero', 'Identificador', 'Sedes', 'Usuarios', 'Adentro', 'Estado', ''].map(
                (h) => (
                  <th key={h} className="px-4 py-3 text-zp-caption font-bold uppercase
                                         tracking-wide text-on-surface-variant">
                    {h}
                  </th>
                ),
              )}
            </tr>
          </thead>
          <tbody>
            {clientes.map((c) => (
              <tr key={c.id} className="border-b border-outline-variant last:border-0">
                <td className="px-4 py-3">
                  <a href={`/admin/tenants/${c.id}`}
                     className="text-zp-body font-bold underline underline-offset-4">
                    {c.nombre}
                  </a>
                </td>
                <td className="px-4 py-3 text-zp-body text-on-surface-variant">
                  <code>{c.slug}</code>
                </td>
                <td className="px-4 py-3 text-zp-body tabular-nums">{c.sedes}</td>
                <td className="px-4 py-3 text-zp-body tabular-nums">{c.usuarios}</td>
                <td className="px-4 py-3 text-zp-body tabular-nums">{c.adentro}</td>
                <td className="px-4 py-3">
                  <span className={`rounded-zp border-2 border-outline px-2.5 py-0.5
                                    text-zp-caption font-bold uppercase tracking-wide ${
                                      c.status === 'activo'
                                        ? 'bg-primary text-on-primary'
                                        : 'bg-surface-container-high text-on-surface-variant'
                                    }`}>
                    {c.status}
                  </span>
                </td>
                <td className="px-4 py-3 text-right">
                  <button
                    onClick={() => alternarEstado(c)}
                    disabled={ocupado}
                    className={`rounded-zp border-2 px-3 py-1.5 text-zp-caption font-bold
                                uppercase tracking-wide ${
                                  c.status === 'activo'
                                    ? 'border-error text-error'
                                    : 'border-outline bg-surface-container-lowest'
                                }`}
                  >
                    {c.status === 'activo' ? 'Suspender' : 'Reactivar'}
                  </button>
                </td>
              </tr>
            ))}
            {clientes.length === 0 && (
              <tr>
                <td colSpan={7} className="px-4 py-10 text-center text-zp-body
                                           text-on-surface-variant">
                  Todavía no hay clientes.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Campo({
  etiqueta, valor, onChange, requerido = false, tipo = 'text', ayuda,
}: {
  etiqueta: string;
  valor: string;
  onChange: (v: string) => void;
  requerido?: boolean;
  tipo?: string;
  ayuda?: string;
}) {
  return (
    <label className="block space-y-1.5">
      <span className="text-zp-caption font-bold uppercase tracking-wide text-on-surface-variant">
        {etiqueta}
      </span>
      <input
        type={tipo} required={requerido} value={valor}
        onChange={(e) => onChange(e.target.value)} className={CAMPO}
      />
      {ayuda && <span className="block text-zp-caption text-on-surface-variant">{ayuda}</span>}
    </label>
  );
}
