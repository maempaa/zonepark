import { useEffect, useState } from 'react';

/**
 * Simulador de tarifas.
 *
 * Sirve para responder la pregunta que se hace quien configura un
 * parqueadero: "si un carro entra a las 7 de la noche y sale a las 7 de la
 * mañana, ¿cuánto le cobro?". Los atajos de duración están para poder
 * revisar una tarifa entera en medio minuto, sin escribir fechas.
 */

interface Tipo {
  id: string;
  codigo: string;
  nombre: string;
}
interface Plan {
  id: string;
  codigo: string;
  version: number;
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
  subtotal: string;
  impuesto: string;
  total: string;
  regla_aplicada: string;
  en_cortesia: boolean;
  tope_aplicado: boolean;
  minimo_aplicado: boolean;
}

const ATAJOS: Array<[string, number]> = [
  ['10 min', 10],
  ['45 min', 45],
  ['1 h', 60],
  ['2 h 17', 137],
  ['8 h', 480],
  ['1 día', 1440],
  ['3 días', 4320],
];

function pesos(valor: string): string {
  return new Intl.NumberFormat('es-CO', {
    style: 'currency',
    currency: 'COP',
    maximumFractionDigits: 0,
  }).format(Number(valor));
}

/** Convierte un <input type="datetime-local"> a ISO con la zona del navegador. */
function aIso(local: string): string {
  return new Date(local).toISOString();
}

function localAhora(desplazamientoMin = 0): string {
  const d = new Date(Date.now() + desplazamientoMin * 60_000);
  d.setSeconds(0, 0);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

interface Props {
  tenant: string;
  planes: Plan[];
  tipos: Tipo[];
}

export default function SimuladorTarifas({ tenant, planes, tipos }: Props) {
  const [plan, setPlan] = useState(planes[0]?.id ?? '');
  const [tipo, setTipo] = useState(tipos[0]?.id ?? '');
  const [entrada, setEntrada] = useState(() => localAhora(-137));
  const [salida, setSalida] = useState(() => localAhora());
  const [resultado, setResultado] = useState<Cotizacion | null>(null);
  const [error, setError] = useState('');
  const [cargando, setCargando] = useState(false);

  function aplicarAtajo(minutos: number) {
    const fin = new Date(entrada);
    fin.setMinutes(fin.getMinutes() + minutos);
    const pad = (n: number) => String(n).padStart(2, '0');
    setSalida(
      `${fin.getFullYear()}-${pad(fin.getMonth() + 1)}-${pad(fin.getDate())}T${pad(fin.getHours())}:${pad(fin.getMinutes())}`,
    );
  }

  useEffect(() => {
    if (!plan || !tipo || !entrada || !salida) return;
    let cancelado = false;

    // Pequeño retardo: al arrastrar el selector de hora no tiene sentido
    // disparar una petición por cada cambio.
    const temporizador = setTimeout(async () => {
      setCargando(true);
      setError('');
      try {
        const res = await fetch(`/api/v1/t/${tenant}/planes/${plan}/simular`, {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({
            vehicle_type_id: tipo,
            entrada: aIso(entrada),
            salida: aIso(salida),
          }),
        });
        const datos = await res.json();
        if (cancelado) return;
        if (!res.ok) {
          setResultado(null);
          setError(
            typeof datos.detail === 'string' ? datos.detail : 'No se pudo cotizar',
          );
          return;
        }
        setResultado(datos);
      } catch {
        if (!cancelado) setError('Sin conexión con el servidor');
      } finally {
        if (!cancelado) setCargando(false);
      }
    }, 250);

    return () => {
      cancelado = true;
      clearTimeout(temporizador);
    };
  }, [tenant, plan, tipo, entrada, salida]);

  const campo =
    'w-full rounded-xl border border-slate-300 bg-white px-3 py-2.5 text-base ' +
    'text-slate-900 outline-none focus:border-brand-500 focus:ring-2 focus:ring-brand-500/30 ' +
    'dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100';

  return (
    <div className="space-y-5">
      <div className="grid gap-4 sm:grid-cols-2">
        <label className="space-y-1.5">
          <span className="text-sm font-medium text-slate-600 dark:text-slate-300">Plan</span>
          <select value={plan} onChange={(e) => setPlan(e.target.value)} className={campo}>
            {planes.map((p) => (
              <option key={p.id} value={p.id}>
                {p.codigo} v{p.version} · {p.estado}
              </option>
            ))}
          </select>
        </label>

        <label className="space-y-1.5">
          <span className="text-sm font-medium text-slate-600 dark:text-slate-300">Vehículo</span>
          <select value={tipo} onChange={(e) => setTipo(e.target.value)} className={campo}>
            {tipos.map((t) => (
              <option key={t.id} value={t.id}>
                {t.nombre}
              </option>
            ))}
          </select>
        </label>

        <label className="space-y-1.5">
          <span className="text-sm font-medium text-slate-600 dark:text-slate-300">Entrada</span>
          <input
            type="datetime-local"
            value={entrada}
            onChange={(e) => setEntrada(e.target.value)}
            className={campo}
          />
        </label>

        <label className="space-y-1.5">
          <span className="text-sm font-medium text-slate-600 dark:text-slate-300">Salida</span>
          <input
            type="datetime-local"
            value={salida}
            onChange={(e) => setSalida(e.target.value)}
            className={campo}
          />
        </label>
      </div>

      <div className="flex flex-wrap gap-2">
        {ATAJOS.map(([texto, minutos]) => (
          <button
            key={texto}
            type="button"
            onClick={() => aplicarAtajo(minutos)}
            className="rounded-lg bg-slate-200 px-3 py-2 text-sm font-medium text-slate-700
                       active:bg-slate-300 dark:bg-slate-800 dark:text-slate-200
                       dark:active:bg-slate-700"
          >
            {texto}
          </button>
        ))}
      </div>

      {error && (
        <p
          role="alert"
          className="rounded-lg bg-red-50 px-3 py-2.5 text-sm text-red-800
                     dark:bg-red-950 dark:text-red-200"
        >
          {error}
        </p>
      )}

      {resultado && (
        <section
          className={`overflow-hidden rounded-2xl bg-white shadow-sm transition
                      dark:bg-slate-900 ${cargando ? 'opacity-50' : ''}`}
        >
          <header className="flex items-baseline justify-between gap-3 border-b
                             border-slate-100 px-4 py-3 dark:border-slate-800">
            <div>
              <p className="text-sm text-slate-500 dark:text-slate-400">
                {resultado.minutos} min · regla{' '}
                <code className="text-xs">{resultado.regla_aplicada}</code>
              </p>
            </div>
            <p className="text-2xl font-bold tabular-nums">{pesos(resultado.total)}</p>
          </header>

          <ul className="divide-y divide-slate-100 dark:divide-slate-800">
            {resultado.lineas.map((linea, i) => (
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

          {(resultado.en_cortesia || resultado.tope_aplicado || resultado.minimo_aplicado) && (
            <footer className="flex flex-wrap gap-2 px-4 py-3">
              {resultado.en_cortesia && <Etiqueta texto="Cortesía" />}
              {resultado.tope_aplicado && <Etiqueta texto="Tope diario aplicado" />}
              {resultado.minimo_aplicado && <Etiqueta texto="Cobro mínimo aplicado" />}
            </footer>
          )}
        </section>
      )}
    </div>
  );
}

function Etiqueta({ texto }: { texto: string }) {
  return (
    <span
      className="rounded-full bg-amber-100 px-3 py-1 text-xs font-semibold text-amber-800
                 dark:bg-amber-950 dark:text-amber-300"
    >
      {texto}
    </span>
  );
}
