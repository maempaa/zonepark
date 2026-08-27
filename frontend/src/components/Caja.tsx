import { useState } from 'react';

/**
 * Turno de caja.
 *
 * El conteo es **a ciegas**: mientras el turno está abierto, quien lo opera
 * no ve cuánto debería haber en el cajón. Si lo viera, teclearía ese número
 * al cerrar y el arqueo no mediría nada. La diferencia aparece después de
 * confirmar el conteo, que es cuando le sirve para cuadrar.
 *
 * El backend decide qué se oculta —viene en `conteo_a_ciegas`—; esta
 * pantalla solo lo respeta. Un supervisor con cash:read ve el esperado
 * siempre.
 */

interface Movimiento {
  id: string;
  tipo: string;
  concepto: string;
  monto: string;
  created_at: string;
}
interface Arqueo {
  base_inicial: string;
  efectivo_cobrado: string | null;
  ingresos_manuales: string;
  egresos_manuales: string;
  esperado: string | null;
  contado: string | null;
  diferencia: string | null;
  cuadra: boolean;
  tickets_cobrados: number;
  por_metodo: Record<string, string>;
  efectivo_sin_turno: string | null;
  conteo_a_ciegas: boolean;
}
interface Turno {
  id: string;
  estado: string;
  abierto_at: string;
  base_inicial: string;
}
interface Detalle {
  turno: Turno;
  arqueo: Arqueo;
  movimientos: Movimiento[];
}
interface Sede { id: string; nombre: string }

function pesos(v: string | number | null): string {
  if (v === null || v === '') return '—';
  return new Intl.NumberFormat('es-CO', {
    style: 'currency', currency: 'COP', maximumFractionDigits: 0,
  }).format(Number(v));
}

function hora(iso: string): string {
  return new Date(iso).toLocaleTimeString('es-CO', { hour: '2-digit', minute: '2-digit' });
}

function Icono({ d, className = 'h-6 w-6 shrink-0' }: { d: string; className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor"
         strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {d.split('|').map((p, i) => <path key={i} d={p} />)}
    </svg>
  );
}
const CHECK = 'm4 12 6 6L20 6';
const ALERTA = 'M12 7v6|M12 16.5v.01';

const CAMPO_GRANDE =
  'w-full rounded-zp border-2 border-outline bg-surface-container-lowest px-4 py-4 ' +
  'text-center text-zp-2xl font-extrabold tabular-nums text-on-surface';
const BOTON_PRIMARIO =
  'w-full rounded-zp border-2 border-outline bg-primary px-4 py-5 text-zp-xl font-extrabold ' +
  'uppercase tracking-wide text-on-primary active:bg-primary-container ' +
  'disabled:border-outline-variant disabled:bg-surface-container-high ' +
  'disabled:text-on-surface-variant';
const BOTON_LLANO =
  'w-full rounded-zp border-2 border-outline bg-surface-container-lowest px-4 py-4 ' +
  'text-zp-body font-bold active:bg-surface-container';

interface Props {
  tenant: string;
  sedes: Sede[];
  inicial: Detalle | null;
  sedeInicial: string;
}

export default function Caja({ tenant, sedes, inicial, sedeInicial }: Props) {
  const [sede, setSede] = useState(sedeInicial);
  const [detalle, setDetalle] = useState<Detalle | null>(inicial);
  const [base, setBase] = useState('');
  const [contado, setContado] = useState('');
  const [cerrando, setCerrando] = useState(false);
  const [movimiento, setMovimiento] =
    useState<{ tipo: string; concepto: string; monto: string } | null>(null);
  const [error, setError] = useState('');
  const [ocupado, setOcupado] = useState(false);

  async function pedir(ruta: string, opciones?: RequestInit): Promise<any | null> {
    setOcupado(true);
    setError('');
    try {
      const res = await fetch(`/api/v1/t/${tenant}${ruta}`, opciones);
      const datos = res.status === 204 ? null : await res.json();
      if (!res.ok) {
        const d = datos?.detail;
        setError(typeof d === 'string' ? d : (d?.detail ?? 'No se pudo completar la operación'));
        return null;
      }
      return datos;
    } catch {
      setError('Sin conexión con el servidor');
      return null;
    } finally {
      setOcupado(false);
    }
  }

  async function abrir() {
    const datos = await pedir('/caja/abrir', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ parking_lot_id: sede, base_inicial: base || '0' }),
    });
    if (datos) setDetalle(datos);
  }

  async function guardarMovimiento() {
    if (!detalle || !movimiento) return;
    const datos = await pedir(`/caja/${detalle.turno.id}/movimientos`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(movimiento),
    });
    if (datos) {
      setDetalle(datos);
      setMovimiento(null);
    }
  }

  async function cerrar() {
    if (!detalle) return;
    const datos = await pedir(`/caja/${detalle.turno.id}/cerrar`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ contado }),
    });
    if (datos) {
      setDetalle(datos);
      setCerrando(false);
    }
  }

  // ── Turno cerrado: el resultado del arqueo ────────────────────────────
  if (detalle && detalle.turno.estado === 'cerrado') {
    const { arqueo } = detalle;
    const cuadra = arqueo.cuadra;
    const falta = Number(arqueo.diferencia ?? 0) < 0;
    return (
      <div className="space-y-4">
        <div
          className={`rounded-zp border-2 bg-surface-container-lowest p-6 text-center ${
            cuadra ? 'border-success' : 'border-error'
          }`}
        >
          <p
            className={`flex items-center justify-center gap-2 text-zp-body font-bold
                        uppercase tracking-wide ${cuadra ? 'text-success' : 'text-error'}`}
          >
            <Icono d={cuadra ? CHECK : ALERTA} className="h-6 w-6" />
            {cuadra ? 'La caja cuadra' : falta ? 'Falta plata' : 'Sobra plata'}
          </p>
          {!cuadra && (
            <p className="mt-3 text-zp-3xl font-extrabold leading-none tabular-nums">
              {pesos(arqueo.diferencia)}
            </p>
          )}
        </div>

        <dl className="overflow-hidden rounded-zp border-2 border-outline
                       bg-surface-container-lowest">
          <Fila termino="Esperado" valor={pesos(arqueo.esperado)} />
          <Fila termino="Contado" valor={pesos(arqueo.contado)} destacado />
          <Fila termino="Base inicial" valor={pesos(arqueo.base_inicial)} />
          <Fila termino="Efectivo cobrado" valor={pesos(arqueo.efectivo_cobrado)} />
          <Fila termino="Ingresos manuales" valor={pesos(arqueo.ingresos_manuales)} />
          <Fila termino="Egresos manuales" valor={`−${pesos(arqueo.egresos_manuales)}`} />
          <Fila termino="Tickets cobrados" valor={String(arqueo.tickets_cobrados)} />
        </dl>

        {arqueo.efectivo_sin_turno !== null && Number(arqueo.efectivo_sin_turno) > 0 && (
          <p className="flex items-start gap-3 rounded-zp border-2 border-warning
                        bg-surface-container-lowest px-4 py-3 text-zp-body">
            <Icono d={ALERTA} />
            <span>
              Se cobraron <strong>{pesos(arqueo.efectivo_sin_turno)}</strong> en efectivo sin
              turno abierto. Ese dinero no entra en el esperado.
            </span>
          </p>
        )}

        <a href={`/t/${tenant}`} className={`${BOTON_PRIMARIO} block text-center`}>
          Volver al tablero
        </a>
      </div>
    );
  }

  // ── Cierre: conteo a ciegas ───────────────────────────────────────────
  if (detalle && cerrando) {
    return (
      <div className="space-y-5">
        <div className="rounded-zp border-2 border-outline bg-surface-container-lowest p-5
                        text-center">
          <p className="text-zp-body font-bold">Cuenta el efectivo del cajón</p>
          <p className="mt-2 text-zp-caption text-on-surface-variant">
            {detalle.arqueo.conteo_a_ciegas
              ? 'La diferencia aparece después de confirmar. Cuenta primero.'
              : 'La diferencia aparece al confirmar.'}
          </p>
        </div>

        <label className="block space-y-2">
          <span className="text-zp-caption font-bold uppercase tracking-wide
                           text-on-surface-variant">
            Total contado
          </span>
          <input
            inputMode="numeric"
            autoFocus
            value={contado}
            onChange={(e) => setContado(e.target.value.replace(/\D/g, ''))}
            placeholder="0"
            className={CAMPO_GRANDE}
          />
        </label>

        {error && (
          <p role="alert" className="flex items-start gap-3 rounded-zp border-2 border-error
                                     bg-surface-container-lowest px-4 py-3 text-zp-body
                                     font-semibold text-error">
            <Icono d={ALERTA} /> <span>{error}</span>
          </p>
        )}

        <button onClick={cerrar} disabled={ocupado || !contado} className={BOTON_PRIMARIO}>
          {ocupado ? 'Cerrando…' : 'Confirmar cierre'}
        </button>
        <button
          onClick={() => setCerrando(false)}
          className="w-full py-2 text-zp-caption font-bold uppercase tracking-wide
                     text-on-surface-variant"
        >
          Volver
        </button>
      </div>
    );
  }

  // ── Turno abierto ─────────────────────────────────────────────────────
  if (detalle) {
    const { arqueo, movimientos } = detalle;
    return (
      <div className="space-y-4">
        <div className="rounded-zp border-2 border-outline bg-surface-container-lowest p-6
                        text-center">
          <p className="text-zp-caption font-bold uppercase tracking-wide text-on-surface-variant">
            Turno abierto desde las {hora(detalle.turno.abierto_at)}
          </p>
          <p className="mt-4 text-zp-3xl font-extrabold leading-none tabular-nums">
            {arqueo.tickets_cobrados}
          </p>
          <p className="mt-1 text-zp-body text-on-surface-variant">
            {arqueo.tickets_cobrados === 1 ? 'ticket cobrado' : 'tickets cobrados'}
          </p>
        </div>

        <dl className="overflow-hidden rounded-zp border-2 border-outline
                       bg-surface-container-lowest">
          <Fila termino="Base inicial" valor={pesos(arqueo.base_inicial)} />
          <Fila termino="Ingresos manuales" valor={pesos(arqueo.ingresos_manuales)} />
          <Fila termino="Egresos manuales" valor={`−${pesos(arqueo.egresos_manuales)}`} />
          {!arqueo.conteo_a_ciegas && (
            <Fila termino="Esperado" valor={pesos(arqueo.esperado)} destacado />
          )}
        </dl>

        {arqueo.conteo_a_ciegas && (
          <p className="rounded-zp border-2 border-dashed border-outline-variant px-4 py-3
                        text-zp-caption text-on-surface-variant">
            No se muestra cuánto debería haber en el cajón: el conteo del cierre es a ciegas
            para que el arqueo signifique algo.
          </p>
        )}

        {movimientos.length > 0 && (
          <section className="space-y-3">
            <h2 className="text-zp-caption font-bold uppercase tracking-wide
                           text-on-surface-variant">
              Movimientos
            </h2>
            <ul className="overflow-hidden rounded-zp border-2 border-outline
                           bg-surface-container-lowest">
              {movimientos.map((m) => (
                <li key={m.id} className="flex items-baseline justify-between gap-3 border-b
                                          border-outline-variant px-4 py-3 last:border-0">
                  <div className="min-w-0">
                    <p className="truncate text-zp-body">{m.concepto}</p>
                    <p className="text-zp-caption text-on-surface-variant">
                      {hora(m.created_at)}
                    </p>
                  </div>
                  <p className={`shrink-0 text-zp-body font-bold tabular-nums ${
                    m.tipo === 'ingreso' ? 'text-success' : 'text-error'
                  }`}>
                    {m.tipo === 'ingreso' ? '+' : '−'}{pesos(m.monto)}
                  </p>
                </li>
              ))}
            </ul>
          </section>
        )}

        {movimiento ? (
          <div className="space-y-3 rounded-zp border-2 border-outline
                          bg-surface-container-lowest p-4">
            <p className="text-zp-body font-extrabold">
              {movimiento.tipo === 'ingreso' ? 'Entra plata' : 'Sale plata'}
            </p>
            <input
              value={movimiento.concepto}
              onChange={(e) => setMovimiento({ ...movimiento, concepto: e.target.value })}
              placeholder="¿En qué?"
              className="w-full rounded-zp border-2 border-outline bg-surface-container-lowest
                         px-4 py-3 text-zp-body"
            />
            <input
              inputMode="numeric"
              value={movimiento.monto}
              onChange={(e) =>
                setMovimiento({ ...movimiento, monto: e.target.value.replace(/\D/g, '') })
              }
              placeholder="0"
              className={CAMPO_GRANDE}
            />
            <div className="flex gap-3">
              <button
                onClick={guardarMovimiento}
                disabled={ocupado || !movimiento.concepto || !movimiento.monto}
                className="flex-1 rounded-zp border-2 border-outline bg-primary px-4 py-3
                           text-zp-body font-extrabold uppercase tracking-wide text-on-primary
                           disabled:border-outline-variant disabled:bg-surface-container-high
                           disabled:text-on-surface-variant"
              >
                Guardar
              </button>
              <button
                onClick={() => setMovimiento(null)}
                className="rounded-zp border-2 border-outline px-4 py-3 text-zp-body font-bold"
              >
                Cancelar
              </button>
            </div>
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-3">
            <button
              onClick={() => setMovimiento({ tipo: 'ingreso', concepto: '', monto: '' })}
              className={BOTON_LLANO}
            >
              + Entra plata
            </button>
            <button
              onClick={() => setMovimiento({ tipo: 'egreso', concepto: '', monto: '' })}
              className={BOTON_LLANO}
            >
              − Sale plata
            </button>
          </div>
        )}

        {error && (
          <p role="alert" className="flex items-start gap-3 rounded-zp border-2 border-error
                                     bg-surface-container-lowest px-4 py-3 text-zp-body
                                     font-semibold text-error">
            <Icono d={ALERTA} /> <span>{error}</span>
          </p>
        )}

        <button
          onClick={() => { setContado(''); setError(''); setCerrando(true); }}
          className={BOTON_PRIMARIO}
        >
          Cerrar turno
        </button>
      </div>
    );
  }

  // ── Sin turno: apertura ───────────────────────────────────────────────
  return (
    <div className="space-y-5">
      <p className="rounded-zp border-2 border-outline bg-surface-container-lowest px-4 py-4
                    text-zp-body">
        Abre el turno con la plata que dejas en el cajón para dar cambio.
      </p>

      {sedes.length > 1 && (
        <label className="block space-y-2">
          <span className="text-zp-caption font-bold uppercase tracking-wide
                           text-on-surface-variant">
            Sede
          </span>
          <select
            value={sede}
            onChange={(e) => setSede(e.target.value)}
            className="w-full rounded-zp border-2 border-outline bg-surface-container-lowest
                       px-4 py-3 text-zp-body font-semibold"
          >
            {sedes.map((s) => (
              <option key={s.id} value={s.id}>{s.nombre}</option>
            ))}
          </select>
        </label>
      )}

      <label className="block space-y-2">
        <span className="text-zp-caption font-bold uppercase tracking-wide text-on-surface-variant">
          Base inicial
        </span>
        <input
          inputMode="numeric"
          autoFocus
          value={base}
          onChange={(e) => setBase(e.target.value.replace(/\D/g, ''))}
          placeholder="0"
          className={CAMPO_GRANDE}
        />
      </label>

      {error && (
        <p role="alert" className="flex items-start gap-3 rounded-zp border-2 border-error
                                   bg-surface-container-lowest px-4 py-3 text-zp-body
                                   font-semibold text-error">
          <Icono d={ALERTA} /> <span>{error}</span>
        </p>
      )}

      <button onClick={abrir} disabled={ocupado} className={BOTON_PRIMARIO}>
        {ocupado ? 'Abriendo…' : 'Abrir turno'}
      </button>
    </div>
  );
}

function Fila({
  termino, valor, destacado = false,
}: { termino: string; valor: string; destacado?: boolean }) {
  return (
    <div className={`flex items-baseline justify-between gap-3 border-b border-outline-variant
                     px-4 py-3 last:border-0 ${destacado ? 'font-extrabold' : ''}`}>
      <dt className="text-zp-body text-on-surface-variant">{termino}</dt>
      <dd className="shrink-0 text-zp-body tabular-nums">{valor}</dd>
    </div>
  );
}
