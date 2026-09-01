import { useState } from 'react';

import IconoVehiculo from './IconoVehiculo';

/**
 * Catálogo del parqueadero: tipos de vehículo y artículos.
 *
 * Es lo primero que hay que tener: sin tipos de vehículo no se puede
 * crear una tarifa, y sin tarifa no se puede registrar un ingreso.
 *
 * Los tipos vienen sembrados al crear el cliente porque no llevan precio.
 * Los artículos no: un precio inventado que alguien cobre sin darse
 * cuenta es peor que una lista vacía.
 */

interface Tipo {
  id: string;
  codigo: string;
  nombre: string;
  requiere_placa: boolean;
  activo: boolean;
  orden: number;
}
interface Articulo {
  id: string;
  codigo: string;
  nombre: string;
  precio: string;
  activo: boolean;
}

const CAMPO =
  'w-full rounded-zp border-2 border-outline bg-surface-container-lowest px-3 py-2 ' +
  'text-zp-body text-on-surface';

/** La base guarda "1000.00"; en pesos no hay centavos que mostrar. */
function sinCentavos(v: string | number): string {
  return String(v).replace(/\.00$/, '');
}

function pesos(v: string | number): string {
  return new Intl.NumberFormat('es-CO', {
    style: 'currency', currency: 'COP', maximumFractionDigits: 0,
  }).format(Number(v));
}

function codigoDesde(nombre: string): string {
  return nombre
    .toLowerCase()
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .slice(0, 32);
}

interface Props {
  tenant: string;
  tipos: Tipo[];
  articulos: Articulo[];
  puedeEditar: boolean;
}

export default function EditorCatalogo({
  tenant, tipos: tiposIniciales, articulos: articulosIniciales, puedeEditar,
}: Props) {
  const [tipos, setTipos] = useState(tiposIniciales);
  const [articulos, setArticulos] = useState(articulosIniciales);
  const [nuevoTipo, setNuevoTipo] = useState({ nombre: '', requiere_placa: true });
  const [nuevoArticulo, setNuevoArticulo] = useState({ nombre: '', precio: '' });
  const [error, setError] = useState('');
  const [ocupado, setOcupado] = useState(false);

  async function pedir(ruta: string, opciones?: RequestInit) {
    setOcupado(true);
    setError('');
    try {
      const res = await fetch(`/api/v1/t/${tenant}${ruta}`, opciones);
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

  async function cargarPredeterminados() {
    const lista = await pedir('/tipos-vehiculo/predeterminados', { method: 'POST' });
    if (lista) setTipos(lista);
  }

  async function crearTipo(e: React.FormEvent) {
    e.preventDefault();
    const creado = await pedir('/tipos-vehiculo', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        codigo: codigoDesde(nuevoTipo.nombre),
        nombre: nuevoTipo.nombre,
        requiere_placa: nuevoTipo.requiere_placa,
        orden: tipos.length + 1,
      }),
    });
    if (creado) {
      setTipos([...tipos, creado]);
      setNuevoTipo({ nombre: '', requiere_placa: true });
    }
  }

  async function alternarTipo(t: Tipo) {
    const act = await pedir(`/tipos-vehiculo/${t.id}`, {
      method: 'PATCH',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ activo: !t.activo }),
    });
    if (act) setTipos(tipos.map((x) => (x.id === t.id ? act : x)));
  }

  async function crearArticulo(e: React.FormEvent) {
    e.preventDefault();
    const creado = await pedir('/articulos', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        codigo: codigoDesde(nuevoArticulo.nombre),
        nombre: nuevoArticulo.nombre,
        precio: nuevoArticulo.precio,
        orden: articulos.length + 1,
      }),
    });
    if (creado) {
      setArticulos([...articulos, creado]);
      setNuevoArticulo({ nombre: '', precio: '' });
    }
  }

  async function guardarPrecio(a: Articulo, precio: string) {
    const act = await pedir(`/articulos/${a.id}`, {
      method: 'PATCH',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ precio }),
    });
    if (act) setArticulos(articulos.map((x) => (x.id === a.id ? act : x)));
  }

  async function alternarArticulo(a: Articulo) {
    const act = await pedir(`/articulos/${a.id}`, {
      method: 'PATCH',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ activo: !a.activo }),
    });
    if (act) setArticulos(articulos.map((x) => (x.id === a.id ? act : x)));
  }

  return (
    <div className="space-y-10">
      {error && (
        <p role="alert" className="rounded-zp border-2 border-error bg-surface-container-lowest
                                   px-4 py-3 text-zp-body font-semibold text-error">
          {error}
        </p>
      )}

      {/* ── Tipos de vehículo ──────────────────────────────────────────── */}
      <section className="space-y-4">
        <div>
          <h2 className="text-zp-lg font-extrabold">Tipos de vehículo</h2>
          <p className="mt-1 text-zp-body text-on-surface-variant">
            Lo que se puede recibir en el parqueadero. Cada tipo necesita su tarifa antes
            de poder registrar un ingreso.
          </p>
        </div>

        {tipos.length === 0 ? (
          <div className="rounded-zp border-2 border-dashed border-outline-variant p-8 text-center">
            <p className="text-zp-body">Todavía no hay tipos de vehículo.</p>
            {puedeEditar && (
              <button
                onClick={cargarPredeterminados}
                disabled={ocupado}
                className="mt-4 rounded-zp border-2 border-outline bg-primary px-5 py-3
                           text-zp-body font-extrabold uppercase tracking-wide text-on-primary"
              >
                Cargar carro, moto y bicicleta
              </button>
            )}
          </div>
        ) : (
          <ul className="grid gap-3 sm:grid-cols-2">
            {tipos.map((t) => (
              <li key={t.id}
                  className={`flex items-center gap-4 rounded-zp border-2 border-outline p-4 ${
                    t.activo ? 'bg-surface-container-lowest' : 'bg-surface-container-high'
                  }`}>
                <IconoVehiculo codigo={t.codigo} className="h-8 w-8 shrink-0" />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-zp-body font-bold">{t.nombre}</p>
                  <p className="text-zp-caption text-on-surface-variant">
                    {t.requiere_placa ? 'con placa' : 'sin placa'}
                    {!t.activo && ' · inactivo'}
                  </p>
                </div>
                {puedeEditar && (
                  <button
                    onClick={() => alternarTipo(t)}
                    disabled={ocupado}
                    className="shrink-0 rounded-zp border-2 border-outline px-3 py-1.5
                               text-zp-caption font-bold uppercase tracking-wide"
                  >
                    {t.activo ? 'Desactivar' : 'Activar'}
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}

        {puedeEditar && (
          <form onSubmit={crearTipo}
                className="flex flex-wrap items-end gap-4 rounded-zp border-2 border-outline
                           bg-surface-container-lowest p-4">
            <label className="min-w-48 flex-1 space-y-1.5">
              <span className="text-zp-caption font-bold uppercase tracking-wide
                               text-on-surface-variant">Nuevo tipo</span>
              <input
                required value={nuevoTipo.nombre} placeholder="Camioneta"
                onChange={(e) => setNuevoTipo({ ...nuevoTipo, nombre: e.target.value })}
                className={CAMPO}
              />
            </label>
            <label className="flex items-center gap-2.5 pb-2">
              <input
                type="checkbox" checked={nuevoTipo.requiere_placa}
                onChange={(e) => setNuevoTipo({ ...nuevoTipo, requiere_placa: e.target.checked })}
                className="h-5 w-5 shrink-0"
              />
              <span className="text-zp-body">Lleva placa</span>
            </label>
            <button type="submit" disabled={ocupado || !nuevoTipo.nombre.trim()}
                    className="rounded-zp border-2 border-outline bg-primary px-5 py-2
                               text-zp-body font-extrabold uppercase tracking-wide
                               text-on-primary disabled:bg-surface-container-high
                               disabled:text-on-surface-variant">
              Agregar
            </button>
          </form>
        )}
      </section>

      {/* ── Artículos ──────────────────────────────────────────────────── */}
      <section className="space-y-4">
        <div>
          <h2 className="text-zp-lg font-extrabold">Artículos y servicios</h2>
          <p className="mt-1 text-zp-body text-on-surface-variant">
            Lo que se cobra aparte del tiempo: un casco que se guarda, una lavada, el
            recargo por ticket perdido. No vienen cargados porque el precio lo pones tú.
          </p>
        </div>

        {articulos.length === 0 ? (
          <p className="rounded-zp border-2 border-dashed border-outline-variant p-8
                        text-center text-zp-body text-on-surface-variant">
            Todavía no hay artículos. Puedes operar sin ellos.
          </p>
        ) : (
          <ul className="overflow-hidden rounded-zp border-2 border-outline
                         bg-surface-container-lowest">
            {articulos.map((a) => (
              <li key={a.id}
                  className={`space-y-3 border-b border-outline-variant px-4 py-4
                              last:border-0 ${a.activo ? '' : 'opacity-70'}`}>
                {/* El nombre manda y va solo en su renglón: al compartir la
                    fila con el precio y el botón quedaba recortado justo en
                    los teléfonos, que es donde se usa esta pantalla. */}
                <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                  <p className="text-zp-body font-bold break-words">{a.nombre}</p>
                  {!a.activo && (
                    <span className="rounded-zp border-2 border-outline-variant px-2 py-0.5
                                     text-zp-caption font-bold uppercase tracking-wide
                                     text-on-surface-variant">
                      inactivo
                    </span>
                  )}
                </div>

                <div className="flex items-center justify-between gap-3">
                  {puedeEditar ? (
                    <div className="campo-moneda flex min-w-0 items-center rounded-zp
                                    border-2 border-outline bg-surface-container-lowest pl-3">
                      <span aria-hidden className="text-zp-body font-semibold
                                                   text-on-surface-variant">$</span>
                      <input
                        inputMode="numeric"
                        aria-label={`Precio de ${a.nombre}`}
                        defaultValue={sinCentavos(a.precio)}
                        onBlur={(e) => {
                          // Solo dígitos, como en el formulario de alta: el punto
                          // es separador de miles en Colombia y "1.000" tecleado
                          // aquí se habría guardado como un peso.
                          const v = e.target.value.replace(/\D/g, '');
                          if (v && v !== sinCentavos(a.precio)) void guardarPrecio(a, v);
                        }}
                        className="w-24 bg-transparent py-2 pr-3 text-right text-zp-body
                                   font-semibold tabular-nums outline-none"
                      />
                    </div>
                  ) : (
                    <span className="text-zp-body font-semibold tabular-nums">
                      {pesos(a.precio)}
                    </span>
                  )}

                  {puedeEditar && (
                    <button
                      onClick={() => alternarArticulo(a)}
                      disabled={ocupado}
                      className="shrink-0 rounded-zp border-2 border-outline px-4 py-2
                                 text-zp-caption font-bold"
                    >
                      {a.activo ? 'Desactivar' : 'Activar'}
                    </button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}

        {puedeEditar && (
          <form onSubmit={crearArticulo}
                className="space-y-4 rounded-zp border-2 border-outline
                           bg-surface-container-lowest p-4">
            <label className="block space-y-1.5">
              <span className="text-zp-caption font-bold uppercase tracking-wide
                               text-on-surface-variant">Nuevo artículo</span>
              <input
                required value={nuevoArticulo.nombre} placeholder="Guarda casco"
                onChange={(e) => setNuevoArticulo({ ...nuevoArticulo, nombre: e.target.value })}
                className={CAMPO}
              />
            </label>
            <div className="flex items-end justify-between gap-4">
              <label className="w-40 shrink space-y-1.5">
                <span className="text-zp-caption font-bold uppercase tracking-wide
                                 text-on-surface-variant">Precio</span>
                <input
                  required inputMode="numeric" value={nuevoArticulo.precio} placeholder="0"
                  onChange={(e) =>
                    setNuevoArticulo({ ...nuevoArticulo, precio: e.target.value.replace(/\D/g, '') })
                  }
                  className={`${CAMPO} text-right tabular-nums`}
                />
              </label>
              <button type="submit"
                      disabled={ocupado || !nuevoArticulo.nombre.trim() || !nuevoArticulo.precio}
                      className="shrink-0 rounded-zp border-2 border-outline bg-primary px-5 py-2
                                 text-zp-body font-extrabold uppercase tracking-wide
                                 text-on-primary disabled:bg-surface-container-high
                                 disabled:text-on-surface-variant">
                Agregar
              </button>
            </div>
          </form>
        )}
      </section>
    </div>
  );
}
