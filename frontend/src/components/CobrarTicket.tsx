import { useEffect, useRef, useState } from 'react';

/**
 * Cotización en vivo y cobro.
 *
 * El valor se actualiza solo mientras el vehículo sigue adentro, así el
 * operario no tiene que pulsar nada para saber cuánto va.
 *
 * La llave de idempotencia se genera **una vez por intento de cobro** y se
 * reutiliza en los reintentos. Es lo que hace que pulsar dos veces con mala
 * señal no cobre dos veces.
 */

interface Ticket {
  id: string;
  codigo: string;
  placa: string | null;
  entrada_at: string;
  estado: string;
}
interface Linea {
  concepto: string;
  monto: string;
  detalle: string | null;
}
interface Cotizacion {
  minutos: number;
  lineas: Linea[];
  total: string;
  en_cortesia: boolean;
  tope_aplicado: boolean;
  minimo_aplicado: boolean;
}
interface Pago {
  metodo: string;
  monto: string;
  recibido: string | null;
  cambio: string | null;
}
interface Articulo {
  codigo: string;
  nombre: string;
  precio: string;
}

const METODOS: Array<[string, string]> = [
  ['efectivo', 'Efectivo'],
  ['tarjeta', 'Tarjeta'],
  ['qr', 'QR'],
  ['transferencia', 'Transferencia'],
];

function pesos(valor: string | number): string {
  return new Intl.NumberFormat('es-CO', {
    style: 'currency',
    currency: 'COP',
    maximumFractionDigits: 0,
  }).format(Number(valor));
}

function transcurrido(desde: string): string {
  const minutos = Math.max(0, Math.floor((Date.now() - new Date(desde).getTime()) / 60000));
  const h = Math.floor(minutos / 60);
  const m = minutos % 60;
  return h ? `${h} h ${String(m).padStart(2, '0')} min` : `${m} min`;
}

interface Props {
  tenant: string;
  ticket: Ticket;
  articulos: Articulo[];
}

export default function CobrarTicket({ tenant, ticket, articulos }: Props) {
  const [cotizacion, setCotizacion] = useState<Cotizacion | null>(null);
  const [reloj, setReloj] = useState(() => transcurrido(ticket.entrada_at));
  const [cobrando, setCobrando] = useState(false);
  const [metodo, setMetodo] = useState('efectivo');
  const [recibido, setRecibido] = useState('');
  const [recibo, setRecibo] = useState<{ pago: Pago; cotizacion: Cotizacion } | null>(null);
  const [error, setError] = useState('');
  const [enviando, setEnviando] = useState(false);
  const llave = useRef<string>('');

  const cerrado = ticket.estado !== 'abierto' || recibo !== null;

  async function traerCotizacion() {
    try {
      const res = await fetch(`/api/v1/t/${tenant}/tickets/${ticket.id}/cotizar`);
      if (res.ok) setCotizacion(await res.json());
    } catch {
      /* se reintenta en el siguiente ciclo */
    }
  }

  useEffect(() => {
    if (cerrado) return;
    void traerCotizacion();
    const tictac = setInterval(() => setReloj(transcurrido(ticket.entrada_at)), 10_000);
    const refresco = setInterval(traerCotizacion, 30_000);
    return () => {
      clearInterval(tictac);
      clearInterval(refresco);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cerrado]);

  async function agregar(codigo: string) {
    await fetch(`/api/v1/t/${tenant}/tickets/${ticket.id}/items`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ codigo }),
    });
    await traerCotizacion();
  }

  function abrirCobro() {
    // Una llave por intento: los reintentos la reutilizan.
    llave.current = crypto.randomUUID();
    setError('');
    setCobrando(true);
  }

  async function confirmar() {
    setEnviando(true);
    setError('');
    try {
      const res = await fetch(`/api/v1/t/${tenant}/tickets/${ticket.id}/cobrar`, {
        method: 'POST',
        headers: { 'content-type': 'application/json', 'Idempotency-Key': llave.current },
        body: JSON.stringify({
          metodo,
          recibido: metodo === 'efectivo' && recibido ? recibido : null,
        }),
      });
      const datos = await res.json();
      if (!res.ok) {
        setError(typeof datos.detail === 'string' ? datos.detail : 'No se pudo cobrar');
        return;
      }
      setRecibo({ pago: datos.pago, cotizacion: datos.cotizacion });
      setCobrando(false);
    } catch {
      setError('Sin conexión. Vuelve a intentar: no se cobrará dos veces.');
    } finally {
      setEnviando(false);
    }
  }

  async function compartir() {
    if (!recibo) return;
    const texto = [
      `Parqueadero — recibo ${ticket.codigo}`,
      ticket.placa ? `Placa: ${ticket.placa}` : null,
      `Tiempo: ${recibo.cotizacion.minutos} min`,
      '',
      ...recibo.cotizacion.lineas.map((l) => `${l.concepto}: ${pesos(l.monto)}`),
      '',
      `TOTAL: ${pesos(recibo.pago.monto)}`,
    ]
      .filter(Boolean)
      .join('\n');

    try {
      if (navigator.share) await navigator.share({ text: texto });
      else await navigator.clipboard.writeText(texto);
    } catch {
      /* el usuario canceló */
    }
  }

  // ── Recibo ────────────────────────────────────────────────────────────
  if (recibo) {
    return (
      <div className="space-y-5">
        <div className="rounded-2xl bg-emerald-50 p-6 text-center dark:bg-emerald-950">
          <p className="text-sm font-medium text-emerald-700 dark:text-emerald-300">Cobrado</p>
          <p className="mt-1 text-4xl font-bold tabular-nums text-emerald-900 dark:text-emerald-100">
            {pesos(recibo.pago.monto)}
          </p>
          {recibo.pago.cambio !== null && Number(recibo.pago.cambio) > 0 && (
            <p className="mt-3 text-lg font-semibold text-emerald-800 dark:text-emerald-200">
              Cambio: {pesos(recibo.pago.cambio)}
            </p>
          )}
        </div>

        <Desglose cotizacion={recibo.cotizacion} />

        <div className="space-y-3">
          <button
            onClick={compartir}
            className="w-full rounded-xl bg-white px-4 py-4 text-lg font-semibold text-slate-900
                       shadow-sm active:bg-slate-100 dark:bg-slate-900 dark:text-slate-100"
          >
            Compartir recibo
          </button>
          <a
            href={`/t/${tenant}/buscar`}
            className="block w-full rounded-xl bg-brand-600 px-4 py-4 text-center text-lg
                       font-semibold text-white active:bg-brand-700"
          >
            Siguiente vehículo
          </a>
        </div>
      </div>
    );
  }

  // ── Confirmación de cobro ─────────────────────────────────────────────
  if (cobrando && cotizacion) {
    const faltante = Number(recibido || 0) - Number(cotizacion.total);
    return (
      <div className="space-y-5">
        <div className="rounded-2xl bg-white p-5 text-center shadow-sm dark:bg-slate-900">
          <p className="text-sm text-slate-500 dark:text-slate-400">Total a cobrar</p>
          <p className="text-4xl font-bold tabular-nums">{pesos(cotizacion.total)}</p>
        </div>

        <fieldset className="space-y-2">
          <legend className="mb-2 text-sm font-medium text-slate-600 dark:text-slate-300">
            Forma de pago
          </legend>
          <div className="grid grid-cols-2 gap-2.5">
            {METODOS.map(([valor, texto]) => (
              <button
                key={valor}
                type="button"
                onClick={() => setMetodo(valor)}
                aria-pressed={metodo === valor}
                className={`rounded-xl px-3 py-4 text-base font-medium transition ${
                  metodo === valor
                    ? 'bg-brand-600 text-white shadow-md'
                    : 'bg-white text-slate-700 shadow-sm dark:bg-slate-900 dark:text-slate-200'
                }`}
              >
                {texto}
              </button>
            ))}
          </div>
        </fieldset>

        {metodo === 'efectivo' && (
          <label className="block space-y-1.5">
            <span className="text-sm font-medium text-slate-600 dark:text-slate-300">
              ¿Con cuánto paga?
            </span>
            <input
              inputMode="numeric"
              value={recibido}
              onChange={(e) => setRecibido(e.target.value.replace(/\D/g, ''))}
              placeholder="0"
              className="w-full rounded-xl border border-slate-300 bg-white px-4 py-4 text-center
                         text-2xl font-bold tabular-nums outline-none focus:border-brand-500
                         dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
            />
            {recibido && faltante >= 0 && (
              <p className="text-center text-lg font-semibold text-emerald-700 dark:text-emerald-400">
                Cambio: {pesos(faltante)}
              </p>
            )}
            {recibido && faltante < 0 && (
              <p className="text-center text-sm font-medium text-red-700 dark:text-red-400">
                Faltan {pesos(-faltante)}
              </p>
            )}
          </label>
        )}

        {error && (
          <p
            role="alert"
            className="rounded-lg bg-red-50 px-3 py-2.5 text-sm text-red-800
                       dark:bg-red-950 dark:text-red-200"
          >
            {error}
          </p>
        )}

        <div className="space-y-3">
          <button
            onClick={confirmar}
            disabled={enviando || (metodo === 'efectivo' && recibido !== '' && faltante < 0)}
            className="w-full rounded-xl bg-emerald-600 px-4 py-5 text-xl font-semibold text-white
                       active:bg-emerald-700 disabled:bg-slate-400"
          >
            {enviando ? 'Cobrando…' : 'Confirmar cobro'}
          </button>
          <button
            onClick={() => setCobrando(false)}
            className="w-full py-2 text-sm font-medium text-slate-600 dark:text-slate-300"
          >
            Volver
          </button>
        </div>
      </div>
    );
  }

  // ── Vista en vivo ─────────────────────────────────────────────────────
  return (
    <div className="space-y-5">
      <div className="rounded-2xl bg-white p-5 text-center shadow-sm dark:bg-slate-900">
        <p className="text-3xl font-bold tracking-wide">{ticket.placa ?? 'Sin placa'}</p>
        <p className="mt-0.5 text-sm text-slate-500 dark:text-slate-400">{ticket.codigo}</p>
        <div className="mt-4 flex items-baseline justify-center gap-6">
          <div>
            <p className="text-xs uppercase tracking-wide text-slate-400">Tiempo</p>
            <p className="text-xl font-semibold tabular-nums">{reloj}</p>
          </div>
          <div>
            <p className="text-xs uppercase tracking-wide text-slate-400">Va en</p>
            <p className="text-3xl font-bold tabular-nums">
              {cotizacion ? pesos(cotizacion.total) : '…'}
            </p>
          </div>
        </div>
      </div>

      {cotizacion && <Desglose cotizacion={cotizacion} />}

      {articulos.length > 0 && (
        <div className="space-y-2">
          <p className="text-sm font-medium text-slate-600 dark:text-slate-300">Agregar</p>
          <div className="flex flex-wrap gap-2">
            {articulos.map((a) => (
              <button
                key={a.codigo}
                onClick={() => agregar(a.codigo)}
                className="rounded-lg bg-white px-3 py-2.5 text-sm font-medium shadow-sm
                           active:bg-slate-100 dark:bg-slate-900 dark:active:bg-slate-800"
              >
                + {a.nombre} · {pesos(a.precio)}
              </button>
            ))}
          </div>
        </div>
      )}

      <button
        onClick={abrirCobro}
        disabled={!cotizacion}
        className="w-full rounded-xl bg-emerald-600 px-4 py-5 text-xl font-semibold text-white
                   active:bg-emerald-700 disabled:bg-slate-400"
      >
        Cobrar y cerrar
      </button>
    </div>
  );
}

function Desglose({ cotizacion }: { cotizacion: Cotizacion }) {
  return (
    <section className="overflow-hidden rounded-2xl bg-white shadow-sm dark:bg-slate-900">
      <ul className="divide-y divide-slate-100 dark:divide-slate-800">
        {cotizacion.lineas.map((linea, i) => (
          <li key={i} className="flex items-baseline justify-between gap-3 px-4 py-2.5">
            <div className="min-w-0">
              <p className="truncate text-sm">{linea.concepto}</p>
              {linea.detalle && (
                <p className="truncate text-xs text-slate-500 dark:text-slate-400">
                  {linea.detalle}
                </p>
              )}
            </div>
            <p className="shrink-0 text-sm tabular-nums">{pesos(linea.monto)}</p>
          </li>
        ))}
      </ul>
      {(cotizacion.en_cortesia || cotizacion.tope_aplicado || cotizacion.minimo_aplicado) && (
        <footer className="flex flex-wrap gap-2 px-4 py-3">
          {cotizacion.en_cortesia && <Etiqueta texto="Cortesía" />}
          {cotizacion.tope_aplicado && <Etiqueta texto="Tope diario" />}
          {cotizacion.minimo_aplicado && <Etiqueta texto="Cobro mínimo" />}
        </footer>
      )}
    </section>
  );
}

function Etiqueta({ texto }: { texto: string }) {
  return (
    <span className="rounded-full bg-amber-100 px-3 py-1 text-xs font-semibold text-amber-800
                     dark:bg-amber-950 dark:text-amber-300">
      {texto}
    </span>
  );
}
