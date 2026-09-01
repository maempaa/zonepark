/**
 * El recibo que ve el cliente mientras su vehículo está adentro.
 *
 * Dos relojes distintos, y la diferencia importa. El tiempo transcurrido
 * se cuenta en el navegador cada segundo, porque una cifra congelada
 * parece una pantalla rota. El **monto** solo cambia cuando el servidor
 * lo recalcula: interpolarlo aquí sería inventar un número que el
 * parqueadero no va a cobrar, y este recibo existe para evitar
 * discusiones, no para provocarlas.
 */
import { useEffect, useRef, useState } from 'react';

const REFRESCO_MS = 30_000;

interface Linea {
  concepto: string;
  detalle: string | null;
  monto: string;
}

export interface Recibo {
  parqueadero: string;
  sede: string;
  direccion: string | null;
  telefono: string | null;
  aviso: string;
  codigo: string;
  placa: string | null;
  vehiculo: string;
  entrada_at: string;
  salida_at: string | null;
  estado: string;
  minutos: number;
  lineas: Linea[];
  total: string;
  tarifa: string | null;
  estimado: boolean;
  en_cortesia: boolean;
  calculado_at: string;
}

function pesos(v: string | number): string {
  return new Intl.NumberFormat('es-CO', {
    style: 'currency', currency: 'COP', maximumFractionDigits: 0,
  }).format(Number(v));
}

function reloj(d: string): string {
  return new Date(d).toLocaleString('es-CO', {
    day: '2-digit', month: 'short', hour: 'numeric', minute: '2-digit', hour12: true,
  });
}

/** "2 h 17 min". Sin segundos: nadie discute por segundos. */
function duracion(minutos: number): string {
  const h = Math.floor(minutos / 60);
  const m = minutos % 60;
  if (h === 0) return `${m} min`;
  return m === 0 ? `${h} h` : `${h} h ${m} min`;
}

function Icono({ d, className }: { d: string; className?: string }) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" className={className} fill="none"
         stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"
         strokeLinejoin="round">
      <path d={d} />
    </svg>
  );
}

const ALERTA = 'M12 9v4m0 4h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z';
const TELEFONO = 'M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2 4.2 2 2 0 0 1 4 2h3a2 2 0 0 1 2 1.7c.1 1 .3 1.9.6 2.8a2 2 0 0 1-.5 2.1L8 9.8a16 16 0 0 0 6 6l1.2-1.1a2 2 0 0 1 2.1-.5c.9.3 1.8.5 2.8.6a2 2 0 0 1 1.7 2Z';
const LUGAR = 'M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0Z';

interface Props {
  tenant: string;
  token: string;
  inicial: Recibo;
}

export default function ReciboVivo({ tenant, token, inicial }: Props) {
  const [recibo, setRecibo] = useState(inicial);
  const [ahora, setAhora] = useState(() => Date.now());
  const [sinConexion, setSinConexion] = useState(false);
  const montado = useRef(true);

  const cerrado = recibo.estado !== 'abierto';

  // El reloj de pantalla. Se apaga al cerrarse el ticket: ahí el tiempo
  // dejó de correr y seguir contando sería mentir.
  useEffect(() => {
    if (cerrado) return;
    const id = setInterval(() => setAhora(Date.now()), 1000);
    return () => clearInterval(id);
  }, [cerrado]);

  // El monto. Solo lo que diga el servidor.
  useEffect(() => {
    montado.current = true;
    if (cerrado) return;

    async function refrescar() {
      try {
        const res = await fetch(`/api/v1/t/${tenant}/publico/recibo/${token}`, {
          headers: { accept: 'application/json' },
        });
        if (!res.ok) return;
        const datos = (await res.json()) as Recibo;
        if (montado.current) {
          setRecibo(datos);
          setSinConexion(false);
        }
      } catch {
        if (montado.current) setSinConexion(true);
      }
    }

    const id = setInterval(refrescar, REFRESCO_MS);
    // Volver a la pestaña después de un rato no debe mostrar un monto viejo.
    const alVolver = () => { if (document.visibilityState === 'visible') void refrescar(); };
    document.addEventListener('visibilitychange', alVolver);
    return () => {
      montado.current = false;
      clearInterval(id);
      document.removeEventListener('visibilitychange', alVolver);
    };
  }, [tenant, token, cerrado]);

  const entrada = new Date(recibo.entrada_at).getTime();
  const hasta = recibo.salida_at ? new Date(recibo.salida_at).getTime() : ahora;
  const minutos = cerrado ? recibo.minutos : Math.max(0, Math.floor((hasta - entrada) / 60000));

  const anulado = recibo.estado === 'anulado';

  return (
    <div className="space-y-5">
      {/* ── Quién cobra ─────────────────────────────────────────────── */}
      <header className="text-center">
        <h1 className="text-zp-2xl font-extrabold leading-tight">{recibo.parqueadero}</h1>
        {recibo.sede !== recibo.parqueadero && (
          <p className="mt-1 text-zp-body font-semibold">{recibo.sede}</p>
        )}
        <div className="mt-3 space-y-1.5 text-zp-body text-on-surface-variant">
          {recibo.direccion && (
            <p className="flex items-center justify-center gap-2">
              <Icono d={LUGAR} className="h-5 w-5 shrink-0" />
              <span>{recibo.direccion}</span>
            </p>
          )}
          {recibo.telefono && (
            <a href={`tel:${recibo.telefono.replace(/[^\d+]/g, '')}`}
               className="flex items-center justify-center gap-2 font-semibold
                          text-on-surface underline underline-offset-4">
              <Icono d={TELEFONO} className="h-5 w-5 shrink-0" />
              <span>{recibo.telefono}</span>
            </a>
          )}
        </div>
      </header>

      {/* ── Qué se dejó ─────────────────────────────────────────────── */}
      <section className="rounded-zp border-2 border-outline bg-surface-container-lowest p-5
                          text-center">
        {recibo.placa ? (
          <span className="placa text-zp-xl">{recibo.placa}</span>
        ) : (
          <span className="inline-flex items-center rounded-zp border-2 border-dashed
                           border-outline-variant px-3 py-1 font-semibold
                           text-on-surface-variant">
            {recibo.vehiculo}
          </span>
        )}
        <p className="mt-3 text-zp-caption font-bold uppercase tracking-wide
                      text-on-surface-variant">
          {recibo.vehiculo} · Ticket {recibo.codigo}
        </p>
      </section>

      {/* ── Cuánto va ───────────────────────────────────────────────── */}
      {anulado ? (
        <section className="rounded-zp border-2 border-outline bg-surface-container-lowest
                            p-6 text-center">
          <p className="text-zp-lg font-extrabold">Ticket anulado</p>
          <p className="mt-2 text-zp-body text-on-surface-variant">
            Este ticket ya no está en curso. Consulta en la caseta.
          </p>
        </section>
      ) : (
        <section className="rounded-zp border-2 border-outline bg-surface-container-lowest p-6">
          <dl className="flex items-baseline justify-between gap-4">
            <dt className="text-zp-caption font-bold uppercase tracking-wide
                           text-on-surface-variant">Entrada</dt>
            <dd className="text-zp-body font-semibold">{reloj(recibo.entrada_at)}</dd>
          </dl>
          <dl className="mt-2 flex items-baseline justify-between gap-4">
            <dt className="text-zp-caption font-bold uppercase tracking-wide
                           text-on-surface-variant">
              {cerrado ? 'Salida' : 'Lleva'}
            </dt>
            <dd className="text-zp-body font-semibold tabular-nums">
              {cerrado && recibo.salida_at ? reloj(recibo.salida_at) : duracion(minutos)}
            </dd>
          </dl>

          <div className="my-5 border-t-2 border-outline-variant" />

          <p className="text-zp-caption font-bold uppercase tracking-wide
                        text-on-surface-variant">
            {recibo.estimado ? 'Va en' : 'Total cobrado'}
          </p>
          <p className="mt-1 text-zp-4xl font-extrabold leading-none tabular-nums">
            {recibo.en_cortesia ? 'Sin cobro' : pesos(recibo.total)}
          </p>
          {recibo.tarifa && (
            <p className="mt-2 text-zp-body text-on-surface-variant">{recibo.tarifa}</p>
          )}

          {recibo.lineas.length > 1 && (
            <ul className="mt-4 space-y-1.5 border-t-2 border-outline-variant pt-4">
              {recibo.lineas.map((l, i) => (
                <li key={i} className="flex items-baseline justify-between gap-4
                                       text-zp-body">
                  <span className="text-on-surface-variant">
                    {l.concepto}
                    {l.detalle && <span className="text-zp-caption"> · {l.detalle}</span>}
                  </span>
                  <span className="shrink-0 font-semibold tabular-nums">{pesos(l.monto)}</span>
                </li>
              ))}
            </ul>
          )}

          {recibo.estimado && (
            <p className="mt-4 text-zp-caption text-on-surface-variant">
              Valor estimado, se actualiza solo. El monto definitivo lo confirma
              el operario al momento de salir.
              {sinConexion && ' Sin conexión: puede estar desactualizado.'}
            </p>
          )}
        </section>
      )}

      {/* ── El aviso ────────────────────────────────────────────────── */}
      <section className="flex items-start gap-3 rounded-zp border-2 border-warning
                          bg-surface-container-lowest p-5">
        <Icono d={ALERTA} className="mt-0.5 h-6 w-6 shrink-0" />
        <div>
          <p className="text-zp-body font-extrabold">Objetos dentro del vehículo</p>
          <p className="mt-1 text-zp-body text-on-surface-variant">{recibo.aviso}</p>
        </div>
      </section>
    </div>
  );
}
