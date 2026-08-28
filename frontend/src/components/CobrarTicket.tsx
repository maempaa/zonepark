import { useEffect, useRef, useState } from 'react';

import { idUnico } from '../lib/id';

/**
 * Cotización en vivo y cobro.
 *
 * El valor se actualiza solo mientras el vehículo sigue adentro, así el
 * operario no tiene que pulsar nada para saber cuánto va.
 *
 * La llave de idempotencia se genera **una vez por intento de cobro** y se
 * reutiliza en los reintentos: es lo que hace que pulsar dos veces con mala
 * señal no cobre dos veces.
 */

interface Ticket {
  id: string;
  codigo: string;
  placa: string | null;
  entrada_at: string;
  estado: string;
}
interface Linea { concepto: string; monto: string; detalle: string | null }
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
interface Articulo { codigo: string; nombre: string; precio: string }

const METODOS: Array<[string, string]> = [
  ['efectivo', 'Efectivo'],
  ['tarjeta', 'Tarjeta'],
  ['qr', 'QR'],
  ['transferencia', 'Transferencia'],
];

// Denominaciones habituales en Colombia, para no teclear el monto entero.
const BILLETES = [2000, 5000, 10000, 20000, 50000];

function pesos(v: string | number): string {
  return new Intl.NumberFormat('es-CO', {
    style: 'currency', currency: 'COP', maximumFractionDigits: 0,
  }).format(Number(v));
}

function transcurrido(desde: string): string {
  const minutos = Math.max(0, Math.floor((Date.now() - new Date(desde).getTime()) / 60000));
  const h = Math.floor(minutos / 60);
  return h ? `${h} h ${String(minutos % 60).padStart(2, '0')}` : `${minutos} min`;
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

const BOTON_PRIMARIO =
  'w-full rounded-zp border-2 border-outline bg-primary px-4 py-5 text-zp-xl font-extrabold ' +
  'uppercase tracking-wide text-on-primary transition active:bg-primary-container ' +
  'disabled:border-outline-variant disabled:bg-surface-container-high ' +
  'disabled:text-on-surface-variant';
const BOTON_LLANO =
  'w-full rounded-zp border-2 border-outline bg-surface-container-lowest px-4 py-4 ' +
  'text-zp-body font-bold text-on-surface active:bg-surface-container';

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
  const [aviso, setAviso] = useState('');
  const llave = useRef<string>('');

  const cerrado = ticket.estado !== 'abierto' || recibo !== null;

  async function traerCotizacion() {
    try {
      const res = await fetch(`/api/v1/t/${tenant}/tickets/${ticket.id}/cotizar`);
      if (res.ok) {
        setCotizacion(await res.json());
        setError('');
        return;
      }
      // Sin cotización el botón de cobrar queda deshabilitado. Callarlo
      // haría que la pantalla pareciera rota en vez de avisar.
      setError('No se pudo calcular el valor. Reintentando…');
    } catch {
      setError('Sin conexión. Reintentando…');
    }
  }

  useEffect(() => {
    if (cerrado) return;
    void traerCotizacion();
    const tictac = setInterval(() => setReloj(transcurrido(ticket.entrada_at)), 10_000);
    const refresco = setInterval(traerCotizacion, 30_000);
    return () => { clearInterval(tictac); clearInterval(refresco); };
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
    llave.current = idUnico();
    setRecibido('');
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
    ].filter(Boolean).join('\n');

    // `share` y `clipboard` tampoco existen fuera de contexto seguro; se
    // comprueban antes de llamarlas en vez de confiar en el try.
    try {
      if (typeof navigator.share === 'function') {
        await navigator.share({ text: texto });
        return;
      }
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(texto);
        setAviso('Recibo copiado al portapapeles');
        return;
      }
      setAviso('Este navegador no permite compartir; anota el total.');
    } catch {
      /* el usuario canceló el diálogo de compartir */
    }
  }

  // ── Recibo ────────────────────────────────────────────────────────────
  if (recibo) {
    const cambio = Number(recibo.pago.cambio ?? 0);
    return (
      <div className="space-y-4">
        <div className="rounded-zp border-2 border-success bg-surface-container-lowest p-6 text-center">
          <p className="flex items-center justify-center gap-2 text-zp-body font-bold
                        uppercase tracking-wide text-success">
            <Icono d={CHECK} className="h-6 w-6" /> Cobrado
          </p>
          <p className="mt-3 text-zp-3xl font-extrabold leading-none tabular-nums">
            {pesos(recibo.pago.monto)}
          </p>
          {ticket.placa && <span className="placa mt-4 text-zp-lg">{ticket.placa}</span>}
        </div>

        {cambio > 0 && (
          <div className="rounded-zp border-2 border-outline bg-primary p-6 text-center
                          text-on-primary">
            <p className="text-zp-caption font-bold uppercase tracking-wide">Cambio a devolver</p>
            <p className="mt-1 text-zp-3xl font-extrabold leading-none tabular-nums">
              {pesos(cambio)}
            </p>
          </div>
        )}

        <Desglose cotizacion={recibo.cotizacion} />

        {aviso && (
          <p className="rounded-zp border-2 border-outline-variant px-4 py-3 text-zp-body
                        text-on-surface-variant">
            {aviso}
          </p>
        )}
        <button onClick={compartir} className={BOTON_LLANO}>Compartir recibo</button>
        <a href={`/t/${tenant}/buscar`} className={`${BOTON_PRIMARIO} block text-center`}>
          Siguiente vehículo
        </a>
      </div>
    );
  }

  // ── Confirmación de cobro ─────────────────────────────────────────────
  if (cobrando && cotizacion) {
    const vuelto = Number(recibido || 0) - Number(cotizacion.total);
    const falta = recibido !== '' && vuelto < 0;
    return (
      <div className="space-y-5">
        <div className="rounded-zp border-2 border-outline bg-surface-container-lowest p-6 text-center">
          <p className="text-zp-caption font-bold uppercase tracking-wide text-on-surface-variant">
            Total a cobrar
          </p>
          <p className="mt-1 text-zp-3xl font-extrabold leading-none tabular-nums">
            {pesos(cotizacion.total)}
          </p>
        </div>

        <fieldset>
          <legend className="mb-3 text-zp-caption font-bold uppercase tracking-wide
                             text-on-surface-variant">
            Forma de pago
          </legend>
          <div className="grid grid-cols-2 gap-3">
            {METODOS.map(([valor, texto]) => (
              <button
                key={valor}
                type="button"
                onClick={() => setMetodo(valor)}
                aria-pressed={metodo === valor}
                className={`rounded-zp border-2 border-outline px-3 py-4 text-zp-body font-bold
                            transition ${
                              metodo === valor
                                ? 'bg-primary text-on-primary'
                                : 'bg-surface-container-lowest active:bg-surface-container'
                            }`}
              >
                {texto}
              </button>
            ))}
          </div>
        </fieldset>

        {metodo === 'efectivo' && (
          <div className="space-y-3">
            <p className="text-zp-caption font-bold uppercase tracking-wide text-on-surface-variant">
              ¿Con cuánto paga?
            </p>
            <div className="flex flex-wrap gap-2">
              {BILLETES.filter((b) => b >= Number(cotizacion.total)).slice(0, 4).map((b) => (
                <button
                  key={b}
                  type="button"
                  onClick={() => setRecibido(String(b))}
                  className="rounded-zp border-2 border-outline bg-surface-container-lowest px-4
                             py-3 text-zp-body font-bold tabular-nums active:bg-surface-container"
                >
                  {pesos(b)}
                </button>
              ))}
              <button
                type="button"
                onClick={() => setRecibido(String(Math.ceil(Number(cotizacion.total))))}
                className="rounded-zp border-2 border-outline bg-surface-container-lowest px-4
                           py-3 text-zp-body font-bold active:bg-surface-container"
              >
                Exacto
              </button>
            </div>
            <input
              inputMode="numeric"
              value={recibido}
              onChange={(e) => setRecibido(e.target.value.replace(/\D/g, ''))}
              placeholder="0"
              className="w-full rounded-zp border-2 border-outline bg-surface-container-lowest
                         px-4 py-4 text-center text-zp-2xl font-extrabold tabular-nums"
            />
            {recibido && !falta && (
              <div className="rounded-zp border-2 border-outline bg-primary p-4 text-center
                              text-on-primary">
                <p className="text-zp-caption font-bold uppercase tracking-wide">Cambio</p>
                <p className="text-zp-2xl font-extrabold tabular-nums">{pesos(vuelto)}</p>
              </div>
            )}
            {falta && (
              <p className="flex items-center gap-2 rounded-zp border-2 border-error
                            bg-surface-container-lowest px-4 py-3 text-zp-body font-bold text-error">
                <Icono d={ALERTA} /> Faltan {pesos(-vuelto)}
              </p>
            )}
          </div>
        )}

        {error && (
          <p role="alert"
             className="flex items-start gap-3 rounded-zp border-2 border-error
                        bg-surface-container-lowest px-4 py-3 text-zp-body font-semibold text-error">
            <Icono d={ALERTA} /> <span>{error}</span>
          </p>
        )}

        <button onClick={confirmar} disabled={enviando || falta} className={BOTON_PRIMARIO}>
          {enviando ? 'Cobrando…' : 'Confirmar cobro'}
        </button>
        <button
          onClick={() => setCobrando(false)}
          className="w-full py-2 text-zp-caption font-bold uppercase tracking-wide
                     text-on-surface-variant"
        >
          Volver
        </button>
      </div>
    );
  }

  // ── Vista en vivo ─────────────────────────────────────────────────────
  return (
    <div className="space-y-4">
      <div className="rounded-zp border-2 border-outline bg-surface-container-lowest p-6 text-center">
        {ticket.placa ? (
          <span className="placa text-zp-2xl">{ticket.placa}</span>
        ) : (
          <p className="text-zp-2xl font-extrabold">{ticket.codigo}</p>
        )}
        {ticket.placa && (
          <p className="mt-2 text-zp-caption text-on-surface-variant">{ticket.codigo}</p>
        )}

        <div className="mt-6 grid grid-cols-2 gap-4 border-t-2 border-outline pt-5">
          <div>
            <p className="text-zp-caption font-bold uppercase tracking-wide text-on-surface-variant">
              Tiempo
            </p>
            <p className="mt-1 text-zp-xl font-extrabold tabular-nums">{reloj}</p>
          </div>
          <div>
            <p className="text-zp-caption font-bold uppercase tracking-wide text-on-surface-variant">
              Va en
            </p>
            <p className="mt-1 text-zp-2xl font-extrabold leading-none tabular-nums">
              {cotizacion ? pesos(cotizacion.total) : '…'}
            </p>
          </div>
        </div>
      </div>

      {error && (
        <p role="alert"
           className="flex items-start gap-3 rounded-zp border-2 border-error
                      bg-surface-container-lowest px-4 py-3 text-zp-body font-semibold text-error">
          <Icono d={ALERTA} /> <span>{error}</span>
        </p>
      )}

      {cotizacion && <Desglose cotizacion={cotizacion} />}

      {articulos.length > 0 && (
        <div className="space-y-3">
          <p className="text-zp-caption font-bold uppercase tracking-wide text-on-surface-variant">
            Agregar
          </p>
          <div className="flex flex-wrap gap-3">
            {articulos.map((a) => (
              <button
                key={a.codigo}
                onClick={() => agregar(a.codigo)}
                className="rounded-zp border-2 border-outline bg-surface-container-lowest px-4
                           py-3 text-zp-body font-bold active:bg-surface-container"
              >
                + {a.nombre} · {pesos(a.precio)}
              </button>
            ))}
          </div>
        </div>
      )}

      <button onClick={abrirCobro} disabled={!cotizacion} className={BOTON_PRIMARIO}>
        Cobrar y cerrar
      </button>
    </div>
  );
}

function Desglose({ cotizacion }: { cotizacion: Cotizacion }) {
  return (
    <section className="overflow-hidden rounded-zp border-2 border-outline
                        bg-surface-container-lowest">
      <ul>
        {cotizacion.lineas.map((linea, i) => (
          <li key={i} className="flex items-baseline justify-between gap-3 border-b
                                 border-outline-variant px-4 py-3 last:border-0">
            <div className="min-w-0">
              <p className="truncate text-zp-body">{linea.concepto}</p>
              {linea.detalle && (
                <p className="truncate text-zp-caption text-on-surface-variant">
                  {linea.detalle}
                </p>
              )}
            </div>
            <p className="shrink-0 text-zp-body font-semibold tabular-nums">
              {pesos(linea.monto)}
            </p>
          </li>
        ))}
      </ul>
      {(cotizacion.en_cortesia || cotizacion.tope_aplicado || cotizacion.minimo_aplicado) && (
        <footer className="flex flex-wrap gap-2 border-t-2 border-outline px-4 py-3">
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
    <span className="rounded-zp border-2 border-warning px-2.5 py-0.5 text-zp-caption
                     font-bold uppercase tracking-wide">
      {texto}
    </span>
  );
}
