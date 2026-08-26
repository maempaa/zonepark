import { useState } from 'react';

/**
 * Turno de caja.
 *
 * El conteo es **a ciegas**: mientras el turno está abierto el operario no
 * ve cuánto debería haber en el cajón. Si lo viera, teclearía ese número
 * al cerrar y el arqueo no mediría nada. La diferencia aparece después de
 * confirmar el conteo, que es cuando le sirve.
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
interface Sede {
  id: string;
  nombre: string;
}

function pesos(valor: string | number | null): string {
  if (valor === null) return '—';
  return new Intl.NumberFormat('es-CO', {
    style: 'currency',
    currency: 'COP',
    maximumFractionDigits: 0,
  }).format(Number(valor));
}

function hora(iso: string): string {
  return new Date(iso).toLocaleTimeString('es-CO', { hour: '2-digit', minute: '2-digit' });
}

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
  const [movimiento, setMovimiento] = useState<{ tipo: string; concepto: string; monto: string } | null>(null);
  const [error, setError] = useState('');
  const [ocupado, setOcupado] = useState(false);

  async function pedir(ruta: string, opciones?: RequestInit): Promise<any | null> {
    setOcupado(true);
    setError('');
    try {
      const res = await fetch(`/api/v1/t/${tenant}${ruta}`, opciones);
      const datos = res.status === 204 ? null : await res.json();
      if (!res.ok) {
        setError(
          typeof datos?.detail === 'string'
            ? datos.detail
            : (datos?.detail?.detail ?? 'No se pudo completar la operación'),
        );
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

  const campo =
    'w-full rounded-xl border border-slate-300 bg-white px-4 py-4 text-center text-2xl ' +
    'font-bold tabular-nums outline-none focus:border-brand-500 dark:border-slate-700 ' +
    'dark:bg-slate-900 dark:text-slate-100';

  // ── Turno cerrado: el resultado del arqueo ────────────────────────────
  if (detalle && detalle.turno.estado === 'cerrado') {
    const { arqueo } = detalle;
    const cuadra = arqueo.cuadra;
    return (
      <div className="space-y-5">
        <div
          className={`rounded-2xl p-6 text-center ${
            cuadra
              ? 'bg-emerald-50 dark:bg-emerald-950'
              : 'bg-amber-50 dark:bg-amber-950'
          }`}
        >
          <p
            className={`text-sm font-medium ${
              cuadra
                ? 'text-emerald-700 dark:text-emerald-300'
                : 'text-amber-800 dark:text-amber-300'
            }`}
          >
            {cuadra ? 'La caja cuadra' : 'La caja no cuadra'}
          </p>
          <p className="mt-1 text-4xl font-bold tabular-nums">{pesos(arqueo.diferencia)}</p>
        </div>

        <dl className="overflow-hidden rounded-2xl bg-white shadow-sm dark:bg-slate-900">
          <Fila termino="Esperado" valor={pesos(arqueo.esperado)} />
          <Fila termino="Contado" valor={pesos(arqueo.contado)} />
          <Fila termino="Base inicial" valor={pesos(arqueo.base_inicial)} />
          <Fila termino="Efectivo cobrado" valor={pesos(arqueo.efectivo_cobrado)} />
          <Fila termino="Ingresos manuales" valor={pesos(arqueo.ingresos_manuales)} />
          <Fila termino="Egresos manuales" valor={`−${pesos(arqueo.egresos_manuales)}`} />
          <Fila termino="Tickets cobrados" valor={String(arqueo.tickets_cobrados)} />
        </dl>

        {arqueo.efectivo_sin_turno !== null && Number(arqueo.efectivo_sin_turno) > 0 && (
          <p className="rounded-lg bg-amber-50 px-3 py-2.5 text-sm text-amber-900
                        dark:bg-amber-950 dark:text-amber-200">
            Se cobraron {pesos(arqueo.efectivo_sin_turno)} en efectivo sin turno abierto.
            Ese dinero no entra en el esperado.
          </p>
        )}

        <a
          href={`/t/${tenant}`}
          className="block w-full rounded-xl bg-brand-600 px-4 py-4 text-center text-lg
                     font-semibold text-white active:bg-brand-700"
        >
          Volver al tablero
        </a>
      </div>
    );
  }

  // ── Cierre: conteo a ciegas ───────────────────────────────────────────
  if (detalle && cerrando) {
    return (
      <div className="space-y-5">
        <div className="rounded-2xl bg-white p-5 dark:bg-slate-900">
          <p className="text-center text-sm text-slate-600 dark:text-slate-300">
            Cuenta el efectivo del cajón y escribe el total.
          </p>
          <p className="mt-1 text-center text-xs text-slate-500 dark:text-slate-400">
            La diferencia aparece después de confirmar.
          </p>
        </div>

        <label className="block space-y-1.5">
          <span className="text-sm font-medium text-slate-600 dark:text-slate-300">
            Total contado
          </span>
          <input
            inputMode="numeric"
            autoFocus
            value={contado}
            onChange={(e) => setContado(e.target.value.replace(/\D/g, ''))}
            placeholder="0"
            className={campo}
          />
        </label>

        {error && (
          <p role="alert" className="rounded-lg bg-red-50 px-3 py-2.5 text-sm text-red-800
                                     dark:bg-red-950 dark:text-red-200">
            {error}
          </p>
        )}

        <button
          onClick={cerrar}
          disabled={ocupado || !contado}
          className="w-full rounded-xl bg-emerald-600 px-4 py-5 text-xl font-semibold text-white
                     active:bg-emerald-700 disabled:bg-slate-400"
        >
          {ocupado ? 'Cerrando…' : 'Confirmar cierre'}
        </button>
        <button
          onClick={() => setCerrando(false)}
          className="w-full py-2 text-sm font-medium text-slate-600 dark:text-slate-300"
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
      <div className="space-y-5">
        <div className="rounded-2xl bg-white p-5 text-center shadow-sm dark:bg-slate-900">
          <p className="text-sm text-slate-500 dark:text-slate-400">
            Turno abierto desde las {hora(detalle.turno.abierto_at)}
          </p>
          <p className="mt-3 text-3xl font-bold tabular-nums">{arqueo.tickets_cobrados}</p>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            {arqueo.tickets_cobrados === 1 ? 'ticket cobrado' : 'tickets cobrados'}
          </p>
        </div>

        <dl className="overflow-hidden rounded-2xl bg-white shadow-sm dark:bg-slate-900">
          <Fila termino="Base inicial" valor={pesos(arqueo.base_inicial)} />
          <Fila termino="Ingresos manuales" valor={pesos(arqueo.ingresos_manuales)} />
          <Fila termino="Egresos manuales" valor={`−${pesos(arqueo.egresos_manuales)}`} />
          {!arqueo.conteo_a_ciegas && (
            <Fila termino="Esperado" valor={pesos(arqueo.esperado)} destacado />
          )}
        </dl>

        {movimientos.length > 0 && (
          <section className="space-y-2">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
              Movimientos
            </h2>
            <ul className="overflow-hidden rounded-2xl bg-white shadow-sm dark:bg-slate-900">
              {movimientos.map((m) => (
                <li
                  key={m.id}
                  className="flex items-baseline justify-between gap-3 border-b
                             border-slate-100 px-4 py-2.5 last:border-0 dark:border-slate-800"
                >
                  <div className="min-w-0">
                    <p className="truncate text-sm">{m.concepto}</p>
                    <p className="text-xs text-slate-500">{hora(m.created_at)}</p>
                  </div>
                  <p
                    className={`shrink-0 text-sm font-medium tabular-nums ${
                      m.tipo === 'ingreso'
                        ? 'text-emerald-700 dark:text-emerald-400'
                        : 'text-red-700 dark:text-red-400'
                    }`}
                  >
                    {m.tipo === 'ingreso' ? '+' : '−'}
                    {pesos(m.monto)}
                  </p>
                </li>
              ))}
            </ul>
          </section>
        )}

        {movimiento ? (
          <div className="space-y-3 rounded-2xl bg-white p-4 shadow-sm dark:bg-slate-900">
            <p className="font-medium">
              {movimiento.tipo === 'ingreso' ? 'Ingreso de efectivo' : 'Salida de efectivo'}
            </p>
            <input
              value={movimiento.concepto}
              onChange={(e) => setMovimiento({ ...movimiento, concepto: e.target.value })}
              placeholder="¿En qué?"
              className="w-full rounded-xl border border-slate-300 px-4 py-3 text-base
                         dark:border-slate-700 dark:bg-slate-950"
            />
            <input
              inputMode="numeric"
              value={movimiento.monto}
              onChange={(e) =>
                setMovimiento({ ...movimiento, monto: e.target.value.replace(/\D/g, '') })
              }
              placeholder="0"
              className="w-full rounded-xl border border-slate-300 px-4 py-3 text-center
                         text-xl font-bold tabular-nums dark:border-slate-700 dark:bg-slate-950"
            />
            <div className="flex gap-2">
              <button
                onClick={guardarMovimiento}
                disabled={ocupado || !movimiento.concepto || !movimiento.monto}
                className="flex-1 rounded-xl bg-brand-600 px-4 py-3 font-semibold text-white
                           disabled:bg-slate-400"
              >
                Guardar
              </button>
              <button
                onClick={() => setMovimiento(null)}
                className="rounded-xl px-4 py-3 text-sm font-medium text-slate-600
                           dark:text-slate-300"
              >
                Cancelar
              </button>
            </div>
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-2.5">
            <button
              onClick={() => setMovimiento({ tipo: 'ingreso', concepto: '', monto: '' })}
              className="rounded-xl bg-white px-4 py-4 font-medium shadow-sm
                         active:bg-slate-100 dark:bg-slate-900 dark:active:bg-slate-800"
            >
              + Entra plata
            </button>
            <button
              onClick={() => setMovimiento({ tipo: 'egreso', concepto: '', monto: '' })}
              className="rounded-xl bg-white px-4 py-4 font-medium shadow-sm
                         active:bg-slate-100 dark:bg-slate-900 dark:active:bg-slate-800"
            >
              − Sale plata
            </button>
          </div>
        )}

        {error && (
          <p role="alert" className="rounded-lg bg-red-50 px-3 py-2.5 text-sm text-red-800
                                     dark:bg-red-950 dark:text-red-200">
            {error}
          </p>
        )}

        <button
          onClick={() => {
            setContado('');
            setError('');
            setCerrando(true);
          }}
          className="w-full rounded-xl bg-emerald-600 px-4 py-5 text-xl font-semibold text-white
                     active:bg-emerald-700"
        >
          Cerrar turno
        </button>
      </div>
    );
  }

  // ── Sin turno: apertura ───────────────────────────────────────────────
  return (
    <div className="space-y-5">
      <p className="text-sm text-slate-600 dark:text-slate-300">
        Abre el turno con la plata que dejas en el cajón para dar cambio.
      </p>

      {sedes.length > 1 && (
        <label className="block space-y-1.5">
          <span className="text-sm font-medium text-slate-600 dark:text-slate-300">Sede</span>
          <select
            value={sede}
            onChange={(e) => setSede(e.target.value)}
            className="w-full rounded-xl border border-slate-300 bg-white px-4 py-3 text-base
                       dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
          >
            {sedes.map((s) => (
              <option key={s.id} value={s.id}>
                {s.nombre}
              </option>
            ))}
          </select>
        </label>
      )}

      <label className="block space-y-1.5">
        <span className="text-sm font-medium text-slate-600 dark:text-slate-300">Base inicial</span>
        <input
          inputMode="numeric"
          autoFocus
          value={base}
          onChange={(e) => setBase(e.target.value.replace(/\D/g, ''))}
          placeholder="0"
          className={campo}
        />
      </label>

      {error && (
        <p role="alert" className="rounded-lg bg-red-50 px-3 py-2.5 text-sm text-red-800
                                   dark:bg-red-950 dark:text-red-200">
          {error}
        </p>
      )}

      <button
        onClick={abrir}
        disabled={ocupado}
        className="w-full rounded-xl bg-brand-600 px-4 py-5 text-xl font-semibold text-white
                   active:bg-brand-700 disabled:bg-slate-400"
      >
        {ocupado ? 'Abriendo…' : 'Abrir turno'}
      </button>
    </div>
  );
}

function Fila({
  termino,
  valor,
  destacado = false,
}: {
  termino: string;
  valor: string;
  destacado?: boolean;
}) {
  return (
    <div
      className={`flex items-baseline justify-between gap-3 border-b border-slate-100 px-4 py-3
                  last:border-0 dark:border-slate-800 ${destacado ? 'font-semibold' : ''}`}
    >
      <dt className="text-sm text-slate-600 dark:text-slate-300">{termino}</dt>
      <dd className="shrink-0 tabular-nums">{valor}</dd>
    </div>
  );
}
