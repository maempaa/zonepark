import { useEffect, useRef, useState } from 'react';

import IconoVehiculo from './IconoVehiculo';

/**
 * Registro de ingreso.
 *
 * La pantalla que más se usa del sistema: el operario la abre decenas de
 * veces por turno, de pie y con una mano. El objetivo es que un ingreso
 * salga en menos de cinco segundos.
 *
 * El campo de la placa imita una placa real porque es exactamente lo que
 * el operario está copiando del vehículo que tiene delante.
 *
 * Los adicionales van aquí y no en una pantalla posterior: el casco se
 * entrega en el mismo momento en que se recibe la moto, y se registran
 * junto con el ticket para que no pueda quedar entregado y sin cobrar.
 */

const LLAVE_DISPOSITIVO = 'zp_device';

function obtenerHuella(): string {
  try {
    let huella = localStorage.getItem(LLAVE_DISPOSITIVO);
    if (!huella) {
      huella = crypto.randomUUID();
      localStorage.setItem(LLAVE_DISPOSITIVO, huella);
    }
    return huella;
  } catch {
    return '';
  }
}

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
interface Articulo {
  codigo: string;
  nombre: string;
  precio: string;
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

function pesos(valor: string | number): string {
  return new Intl.NumberFormat('es-CO', {
    style: 'currency',
    currency: 'COP',
    maximumFractionDigits: 0,
  }).format(Number(valor));
}

function haceCuanto(iso: string): string {
  const minutos = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
  if (minutos < 60) return `hace ${minutos} min`;
  return `hace ${Math.floor(minutos / 60)} h ${minutos % 60} min`;
}

function IconoCheck() {
  return (
    <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor"
         strokeWidth="3.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="m4 12 6 6L20 6" />
    </svg>
  );
}

function IconoError() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" className="h-6 w-6 shrink-0" fill="none"
         stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
      <circle cx="12" cy="12" r="9" /><path d="M12 7v6" /><path d="M12 16.5v.01" />
    </svg>
  );
}

interface Props {
  tenant: string;
  sedes: Sede[];
  tipos: Tipo[];
  articulos: Articulo[];
}

export default function RegistrarIngreso({ tenant, sedes, tipos, articulos }: Props) {
  const [sede, setSede] = useState(sedes[0]?.id ?? '');
  const [tipo, setTipo] = useState(tipos[0]?.id ?? '');
  const [placa, setPlaca] = useState('');
  const [elegidos, setElegidos] = useState<string[]>([]);
  const [estado, setEstado] = useState<Estado>({ fase: 'form' });
  const campoPlaca = useRef<HTMLInputElement>(null);

  const tipoActual = tipos.find((t) => t.id === tipo);
  const necesitaPlaca = tipoActual?.requiere_placa ?? true;

  useEffect(() => {
    if (necesitaPlaca) campoPlaca.current?.focus();
  }, [tipo, necesitaPlaca]);

  function alternar(codigo: string) {
    setElegidos((actual) =>
      actual.includes(codigo) ? actual.filter((c) => c !== codigo) : [...actual, codigo],
    );
  }

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
          items: elegidos.map((codigo) => ({ codigo, cantidad: 1 })),
          forzar,
        }),
      });
      const datos = await res.json();

      if (res.status === 409 && datos.detail?.ticket_abierto) {
        setEstado({ fase: 'duplicada', existente: datos.detail.ticket_abierto });
        return;
      }
      if (!res.ok) {
        setEstado({
          fase: 'error',
          mensaje:
            typeof datos.detail === 'string'
              ? datos.detail
              : (datos.detail?.[0]?.msg ?? 'No se pudo registrar'),
        });
        return;
      }
      setEstado({ fase: 'listo', codigo: datos.codigo, placa: datos.placa });
    } catch {
      setEstado({ fase: 'error', mensaje: 'Sin conexión con el servidor' });
    }
  }

  function otroMas() {
    setPlaca('');
    setElegidos([]);
    setEstado({ fase: 'form' });
    campoPlaca.current?.focus();
  }

  // ── Confirmación ──────────────────────────────────────────────────────
  if (estado.fase === 'listo') {
    return (
      <div className="space-y-4">
        <div className="rounded-zp border-2 border-success bg-surface-container-lowest p-8 text-center">
          <p className="flex items-center justify-center gap-2 text-zp-body font-bold uppercase
                        tracking-wide text-success">
            <IconoCheck /> Ingreso registrado
          </p>
          {estado.placa ? (
            <span className="placa mt-5 text-zp-2xl">{estado.placa}</span>
          ) : (
            <p className="mt-5 text-zp-2xl font-extrabold">{estado.codigo}</p>
          )}
          {estado.placa && (
            <p className="mt-3 text-zp-body text-on-surface-variant">{estado.codigo}</p>
          )}
        </div>

        <button
          onClick={otroMas}
          className="w-full rounded-zp border-2 border-outline bg-primary px-4 py-4 text-zp-lg
                     font-extrabold uppercase tracking-wide text-on-primary active:bg-primary-container"
        >
          Registrar otro
        </button>
        <a
          href={`/t/${tenant}`}
          className="block w-full rounded-zp border-2 border-outline bg-surface-container-lowest
                     px-4 py-4 text-center text-zp-body font-bold active:bg-surface-container"
        >
          Volver al tablero
        </a>
      </div>
    );
  }

  // ── Aviso de placa repetida (D6) ──────────────────────────────────────
  if (estado.fase === 'duplicada') {
    return (
      <div className="space-y-4">
        <div className="rounded-zp border-2 border-warning bg-surface-container-lowest p-5">
          <p className="text-zp-lg font-extrabold">Esa placa ya está adentro</p>
          <div className="mt-4 flex items-center gap-3">
            <span className="placa text-zp-lg">{estado.existente.placa}</span>
            <span className="text-zp-caption text-on-surface-variant">
              {estado.existente.codigo} · entró {haceCuanto(estado.existente.entrada_at)}
            </span>
          </div>
          <p className="mt-4 text-zp-body text-on-surface-variant">
            Casi siempre es la placa mal digitada la primera vez. ¿Qué pasó?
          </p>
        </div>

        <a
          href={`/t/${tenant}/tickets/${estado.existente.id}`}
          className="block w-full rounded-zp border-2 border-outline bg-primary px-4 py-4
                     text-center text-zp-lg font-extrabold uppercase tracking-wide
                     text-on-primary active:bg-primary-container"
        >
          Es el mismo — abrir su ticket
        </a>
        <button
          onClick={() => registrar(true)}
          className="w-full rounded-zp border-2 border-outline bg-surface-container-lowest px-4
                     py-4 text-zp-body font-bold active:bg-surface-container"
        >
          Son dos vehículos distintos
        </button>
        <button
          onClick={() => setEstado({ fase: 'form' })}
          className="w-full py-2 text-zp-caption font-bold uppercase tracking-wide
                     text-on-surface-variant"
        >
          Corregir la placa
        </button>
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
        <label className="block space-y-2">
          <span className="text-zp-caption font-bold uppercase tracking-wide text-on-surface-variant">
            Sede
          </span>
          <select
            value={sede}
            onChange={(e) => setSede(e.target.value)}
            className="w-full rounded-zp border-2 border-outline bg-surface-container-lowest
                       px-4 py-3 text-zp-body font-semibold text-on-surface"
          >
            {sedes.map((s) => (
              <option key={s.id} value={s.id}>
                {s.nombre}
              </option>
            ))}
          </select>
        </label>
      )}

      <fieldset className="space-y-3">
        <legend className="mb-3 text-zp-caption font-bold uppercase tracking-wide
                           text-on-surface-variant">
          Tipo de vehículo
        </legend>
        <div className="grid grid-cols-3 gap-3">
          {tipos.map((t) => {
            const activo = t.id === tipo;
            return (
              <button
                key={t.id}
                type="button"
                onClick={() => setTipo(t.id)}
                aria-pressed={activo}
                className={`flex flex-col items-center justify-center gap-1.5 rounded-zp border-2
                            border-outline px-2 py-4 transition ${
                              activo
                                ? 'bg-primary text-on-primary'
                                : 'bg-surface-container-lowest text-on-surface active:bg-surface-container'
                            }`}
              >
                <IconoVehiculo codigo={t.codigo} className="h-8 w-8" />
                <span className="text-zp-caption font-bold">{t.nombre}</span>
              </button>
            );
          })}
        </div>
      </fieldset>

      <label className="block space-y-2">
        <span className="text-zp-caption font-bold uppercase tracking-wide text-on-surface-variant">
          Placa {!necesitaPlaca && <span className="normal-case">(opcional)</span>}
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
          className="placa-campo"
        />
      </label>

      {articulos.length > 0 && (
        <fieldset className="space-y-3">
          <legend className="mb-3 text-zp-caption font-bold uppercase tracking-wide
                             text-on-surface-variant">
            Adicionales
          </legend>
          <div className="space-y-3">
            {articulos.map((a) => {
              const marcado = elegidos.includes(a.codigo);
              return (
                <label
                  key={a.codigo}
                  className={`flex cursor-pointer items-center gap-4 rounded-zp border-2
                              border-outline px-4 py-3 transition ${
                                marcado
                                  ? 'bg-primary text-on-primary'
                                  : 'bg-surface-container-lowest active:bg-surface-container'
                              }`}
                >
                  <input
                    type="checkbox"
                    checked={marcado}
                    onChange={() => alternar(a.codigo)}
                    className="sr-only"
                  />
                  {/* Casilla dibujada: la nativa es diminuta y no se puede
                      agrandar de forma fiable en todos los navegadores. */}
                  <span
                    aria-hidden="true"
                    className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-[4px]
                                border-2 border-outline ${
                                  marcado ? 'bg-on-primary text-primary' : 'bg-surface-container-lowest'
                                }`}
                  >
                    {marcado && <IconoCheck />}
                  </span>
                  <span className="flex-1 text-zp-body font-bold">{a.nombre}</span>
                  <span className="text-zp-body font-semibold tabular-nums">
                    {pesos(a.precio)}
                  </span>
                </label>
              );
            })}
          </div>
        </fieldset>
      )}

      {estado.fase === 'error' && (
        <p
          role="alert"
          className="flex items-start gap-3 rounded-zp border-2 border-error
                     bg-surface-container-lowest px-4 py-3 text-zp-body font-semibold text-error"
        >
          <IconoError />
          <span>{estado.mensaje}</span>
        </p>
      )}

      <button
        type="submit"
        disabled={enviando || (necesitaPlaca && !placa.trim())}
        className="w-full rounded-zp border-2 border-outline bg-primary px-4 py-5 text-zp-xl
                   font-extrabold uppercase tracking-wide text-on-primary transition
                   active:bg-primary-container disabled:border-outline-variant
                   disabled:bg-surface-container-high disabled:text-on-surface-variant"
      >
        {enviando ? 'Registrando…' : 'Registrar ingreso'}
      </button>
    </form>
  );
}
