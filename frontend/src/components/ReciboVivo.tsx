/**
 * El recibo que ve el cliente mientras su vehículo está adentro.
 *
 * Va maquetado como el papel que sale de la impresora de la caseta —una
 * sola tira, bloques separados por cortes de puntos, borde inferior
 * rasgado— porque es lo que la gente reconoce como "el recibo del
 * parqueadero". El monoespaciado es parte de eso: alinea las cifras en
 * columna sin tablas.
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
  terminos: string;
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
  acordada: boolean;
  estimado: boolean;
  en_cortesia: boolean;
  calculado_at: string;
}

function pesos(v: string | number): string {
  return new Intl.NumberFormat('es-CO', {
    style: 'currency', currency: 'COP', maximumFractionDigits: 0,
  }).format(Number(v));
}

function hora(d: string): string {
  return new Date(d).toLocaleTimeString('es-CO', {
    hour: '2-digit', minute: '2-digit', hour12: true,
  });
}

function fecha(d: string): string {
  return new Date(d).toLocaleDateString('es-CO', {
    day: '2-digit', month: 'short', year: 'numeric',
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

const TELEFONO = 'M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2 4.2 2 2 0 0 1 4 2h3a2 2 0 0 1 2 1.7c.1 1 .3 1.9.6 2.8a2 2 0 0 1-.5 2.1L8 9.8a16 16 0 0 0 6 6l1.2-1.1a2 2 0 0 1 2.1-.5c.9.3 1.8.5 2.8.6a2 2 0 0 1 1.7 2Z';

/** Un renglón del recibo: concepto a la izquierda, dato a la derecha. */
function Renglon({ etiqueta, children }: { etiqueta: string; children: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-4">
      <span className="text-on-surface-variant">{etiqueta}</span>
      <span className="text-right font-bold tabular-nums">{children}</span>
    </div>
  );
}

function Corte() {
  return <div className="ticket-corte my-4" />;
}

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
    <div className="ticket recibo-mono text-zp-body">
      <div className="ticket-hoja px-5 pt-6">
        {/* ── Quién cobra ───────────────────────────────────────────── */}
        <header className="text-center">
          <h1 className="text-zp-lg font-extrabold uppercase tracking-wide">
            {recibo.parqueadero}
          </h1>
          {recibo.sede !== recibo.parqueadero && (
            <p className="mt-0.5 font-semibold">{recibo.sede}</p>
          )}
          {recibo.direccion && (
            <p className="mt-2 text-zp-caption text-on-surface-variant">{recibo.direccion}</p>
          )}
          {recibo.telefono && (
            <a href={`tel:${recibo.telefono.replace(/[^\d+]/g, '')}`}
               className="mt-1 inline-flex items-center gap-2 text-zp-caption font-bold
                          underline underline-offset-4">
              <Icono d={TELEFONO} className="h-4 w-4 shrink-0" />
              {recibo.telefono}
            </a>
          )}
        </header>

        <Corte />

        {/* ── Qué se dejó ───────────────────────────────────────────── */}
        <div className="text-center">
          {recibo.placa ? (
            <span className="placa text-zp-xl">{recibo.placa}</span>
          ) : (
            <span className="inline-flex items-center rounded-zp border-2 border-dashed
                             border-outline-variant px-3 py-1 font-bold
                             text-on-surface-variant">
              {recibo.vehiculo}
            </span>
          )}
        </div>

        <div className="mt-4 space-y-1.5">
          <Renglon etiqueta="Ticket">{recibo.codigo}</Renglon>
          <Renglon etiqueta="Tipo">{recibo.vehiculo}</Renglon>
          <Renglon etiqueta="Fecha">{fecha(recibo.entrada_at)}</Renglon>
          <Renglon etiqueta="Entrada">{hora(recibo.entrada_at)}</Renglon>
          {cerrado && recibo.salida_at && (
            <Renglon etiqueta="Salida">{hora(recibo.salida_at)}</Renglon>
          )}
          <Renglon etiqueta={cerrado ? 'Tiempo total' : 'Lleva'}>
            {duracion(minutos)}
          </Renglon>
        </div>

        {/* ── Cuánto va ─────────────────────────────────────────────── */}
        {anulado ? (
          <>
            <Corte />
            <p className="py-4 text-center text-zp-lg font-extrabold uppercase">
              Ticket anulado
            </p>
            <p className="pb-2 text-center text-zp-caption text-on-surface-variant">
              Este ticket ya no está en curso. Consulta en la caseta.
            </p>
          </>
        ) : (
          <>
            <Corte />

            <p className="text-zp-caption font-bold uppercase tracking-widest
                          text-on-surface-variant">
              Detalle del cobro{recibo.tarifa && ` · ${recibo.tarifa}`}
            </p>

            <ul className="mt-3 space-y-2">
              {recibo.lineas.map((l, i) => (
                <li key={i} className="flex items-baseline justify-between gap-4">
                  <span className="min-w-0">
                    <span className="block font-bold">{l.concepto}</span>
                    {l.detalle && (
                      <span className="block text-zp-caption text-on-surface-variant">
                        {l.detalle}
                      </span>
                    )}
                  </span>
                  <span className="shrink-0 font-bold tabular-nums">{pesos(l.monto)}</span>
                </li>
              ))}
            </ul>

            <div className="mt-4 flex items-baseline justify-between gap-4 rounded-zp
                            border-2 border-outline px-4 py-3">
              <span className="text-zp-caption font-bold uppercase tracking-widest">
                {recibo.estimado ? 'Va en' : 'Total cobrado'}
              </span>
              <span className="text-zp-xl font-extrabold tabular-nums">
                {recibo.en_cortesia ? 'Sin cobro' : pesos(recibo.total)}
              </span>
            </div>

            {recibo.estimado && (
              <p className="mt-3 text-zp-caption text-on-surface-variant">
                {recibo.acordada
                  ? 'Calculado con la tarifa que acordaste al dejar tu vehículo. Sube con el tiempo y se actualiza solo.'
                  : 'Valor estimado, se actualiza solo. El monto definitivo lo confirma el operario al momento de salir.'}
                {sinConexion && ' Sin conexión: puede estar desactualizado.'}
              </p>
            )}
          </>
        )}

        <Corte />

        {/* ── El reglamento ─────────────────────────────────────────── */}
        <section className="pb-6">
          <h2 className="text-center text-zp-caption font-bold uppercase tracking-widest
                         text-on-surface-variant">
            Términos y condiciones
          </h2>
          <p className="mt-3 text-justify text-zp-caption leading-relaxed
                        text-on-surface-variant">
            {recibo.terminos}
          </p>
        </section>
      </div>
    </div>
  );
}
