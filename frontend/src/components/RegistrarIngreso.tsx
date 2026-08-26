import { useEffect, useRef, useState } from 'react';

/**
 * Registro de ingreso.
 *
 * La pantalla que más se usa del sistema: el operario la abre decenas de
 * veces por turno, de pie y con una mano. El objetivo es que un ingreso
 * salga en menos de cinco segundos, así que el tipo de vehículo son
 * botones grandes (no un desplegable) y la placa se escribe de una vez.
 */

interface Tipo {
  id: string;
  codigo: string;
  nombre: string;
  requiere_placa: boolean;
}
interface Sede {
  id: string;
  codigo: string;
  nombre: string;
}
interface TicketAbierto {
  id: string;
  codigo: string;
  placa: string | null;
  entrada_at: string;
}

type Estado =
  | { fase: 'form' }
  | { fase: 'enviando' }
  | { fase: 'duplicada'; existente: TicketAbierto }
  | { fase: 'listo'; codigo: string; placa: string | null }
  | { fase: 'error'; mensaje: string };

const ICONOS: Record<string, string> = {
  carro: '🚗',
  moto: '🏍️',
  bicicleta: '🚲',
  camioneta: '🚙',
  patineta: '🛴',
  camion: '🚚',
};

function haceCuanto(iso: string): string {
  const minutos = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
  if (minutos < 60) return `hace ${minutos} min`;
  const horas = Math.floor(minutos / 60);
  return `hace ${horas} h ${minutos % 60} min`;
}

interface Props {
  tenant: string;
  sedes: Sede[];
  tipos: Tipo[];
}

export default function RegistrarIngreso({ tenant, sedes, tipos }: Props) {
  const [sede, setSede] = useState(sedes[0]?.id ?? '');
  const [tipo, setTipo] = useState(tipos[0]?.id ?? '');
  const [placa, setPlaca] = useState('');
  const [estado, setEstado] = useState<Estado>({ fase: 'form' });
  const campoPlaca = useRef<HTMLInputElement>(null);

  const tipoActual = tipos.find((t) => t.id === tipo);
  const necesitaPlaca = tipoActual?.requiere_placa ?? true;

  useEffect(() => {
    if (necesitaPlaca) campoPlaca.current?.focus();
  }, [tipo, necesitaPlaca]);

  async function registrar(forzar = false) {
    setEstado({ fase: 'enviando' });
    try {
      const res = await fetch(`/api/v1/t/${tenant}/tickets`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          parking_lot_id: sede,
          vehicle_type_id: tipo,
          placa: placa.trim() || null,
          forzar,
        }),
      });
      const datos = await res.json();

      if (res.status === 409 && datos.detail?.ticket_abierto) {
        setEstado({ fase: 'duplicada', existente: datos.detail.ticket_abierto });
        return;
      }
      if (!res.ok) {
        const mensaje =
          typeof datos.detail === 'string'
            ? datos.detail
            : (datos.detail?.[0]?.msg ?? 'No se pudo registrar');
        setEstado({ fase: 'error', mensaje });
        return;
      }

      setEstado({ fase: 'listo', codigo: datos.codigo, placa: datos.placa });
    } catch {
      setEstado({ fase: 'error', mensaje: 'Sin conexión con el servidor' });
    }
  }

  function otroMas() {
    setPlaca('');
    setEstado({ fase: 'form' });
    campoPlaca.current?.focus();
  }

  // ── Confirmación ──────────────────────────────────────────────────────
  if (estado.fase === 'listo') {
    return (
      <div className="space-y-6 text-center">
        <div className="rounded-2xl bg-emerald-50 py-10 dark:bg-emerald-950">
          <p className="text-sm font-medium text-emerald-700 dark:text-emerald-300">
            Ingreso registrado
          </p>
          <p className="mt-2 text-4xl font-bold tabular-nums text-emerald-900 dark:text-emerald-100">
            {estado.codigo}
          </p>
          {estado.placa && (
            <p className="mt-1 text-lg text-emerald-700 dark:text-emerald-300">{estado.placa}</p>
          )}
        </div>
        <button
          onClick={otroMas}
          className="w-full rounded-xl bg-brand-600 px-4 py-4 text-lg font-semibold text-white
                     active:bg-brand-700"
        >
          Registrar otro
        </button>
        <a
          href={`/t/${tenant}`}
          className="block text-sm font-medium text-brand-600 dark:text-brand-500"
        >
          Volver al tablero
        </a>
      </div>
    );
  }

  // ── Aviso de placa repetida (D6) ──────────────────────────────────────
  if (estado.fase === 'duplicada') {
    return (
      <div className="space-y-5">
        <div className="rounded-2xl bg-amber-50 p-5 dark:bg-amber-950">
          <p className="font-semibold text-amber-900 dark:text-amber-100">
            Esa placa ya está adentro
          </p>
          <p className="mt-1 text-sm text-amber-800 dark:text-amber-200">
            El ticket <strong>{estado.existente.codigo}</strong> con placa{' '}
            <strong>{estado.existente.placa}</strong> entró{' '}
            {haceCuanto(estado.existente.entrada_at)}.
          </p>
        </div>

        <p className="text-sm text-slate-600 dark:text-slate-300">
          Casi siempre es la placa mal digitada la primera vez. ¿Qué pasó?
        </p>

        <div className="space-y-3">
          <a
            href={`/t/${tenant}/tickets/${estado.existente.id}`}
            className="block w-full rounded-xl bg-brand-600 px-4 py-4 text-center text-lg
                       font-semibold text-white active:bg-brand-700"
          >
            Es el mismo — abrir su ticket
          </a>
          <button
            onClick={() => registrar(true)}
            className="w-full rounded-xl bg-white px-4 py-4 text-lg font-semibold text-slate-900
                       shadow-sm active:bg-slate-100 dark:bg-slate-900 dark:text-slate-100
                       dark:active:bg-slate-800"
          >
            Son dos vehículos distintos
          </button>
          <button
            onClick={() => setEstado({ fase: 'form' })}
            className="w-full py-2 text-sm font-medium text-slate-600 dark:text-slate-300"
          >
            Corregir la placa
          </button>
        </div>
      </div>
    );
  }

  // ── Formulario ────────────────────────────────────────────────────────
  const enviando = estado.fase === 'enviando';

  return (
    <form
      className="space-y-6"
      onSubmit={(e) => {
        e.preventDefault();
        void registrar();
      }}
    >
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

      <fieldset className="space-y-2">
        <legend className="mb-2 text-sm font-medium text-slate-600 dark:text-slate-300">
          Tipo de vehículo
        </legend>
        <div className="grid grid-cols-3 gap-2.5">
          {tipos.map((t) => (
            <button
              key={t.id}
              type="button"
              onClick={() => setTipo(t.id)}
              aria-pressed={t.id === tipo}
              className={`flex flex-col items-center gap-1 rounded-xl px-2 py-4 transition ${
                t.id === tipo
                  ? 'bg-brand-600 text-white shadow-md'
                  : 'bg-white text-slate-700 shadow-sm active:bg-slate-100 ' +
                    'dark:bg-slate-900 dark:text-slate-200 dark:active:bg-slate-800'
              }`}
            >
              <span className="text-3xl leading-none">{ICONOS[t.codigo] ?? '🅿️'}</span>
              <span className="text-sm font-medium">{t.nombre}</span>
            </button>
          ))}
        </div>
      </fieldset>

      <label className="block space-y-1.5">
        <span className="text-sm font-medium text-slate-600 dark:text-slate-300">
          Placa {!necesitaPlaca && <span className="font-normal">(opcional)</span>}
        </span>
        <input
          ref={campoPlaca}
          value={placa}
          onChange={(e) => setPlaca(e.target.value.toUpperCase())}
          required={necesitaPlaca}
          autoCapitalize="characters"
          autoCorrect="off"
          spellCheck={false}
          placeholder="ABC123"
          className="w-full rounded-xl border border-slate-300 bg-white px-4 py-4 text-center
                     text-2xl font-bold tracking-widest text-slate-900 outline-none
                     focus:border-brand-500 focus:ring-2 focus:ring-brand-500/30
                     dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
        />
      </label>

      {estado.fase === 'error' && (
        <p
          role="alert"
          className="rounded-lg bg-red-50 px-3 py-2.5 text-sm text-red-800
                     dark:bg-red-950 dark:text-red-200"
        >
          {estado.mensaje}
        </p>
      )}

      <button
        type="submit"
        disabled={enviando || (necesitaPlaca && !placa.trim())}
        className="w-full rounded-xl bg-brand-600 px-4 py-5 text-xl font-semibold text-white
                   active:bg-brand-700 disabled:bg-slate-400"
      >
        {enviando ? 'Registrando…' : 'Registrar ingreso'}
      </button>
    </form>
  );
}
