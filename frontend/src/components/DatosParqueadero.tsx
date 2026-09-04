/**
 * Lo que el cliente ve en su recibo, editable por el administrador.
 *
 * La dirección y el teléfono son de la sede —una empresa con dos casetas
 * tiene dos direcciones— y el reglamento es del parqueadero entero,
 * porque es una política, no una ubicación.
 */
import { useState } from 'react';

const CAMPO =
  'w-full rounded-zp border-2 border-outline bg-surface-container-lowest px-3 py-2 ' +
  'text-zp-body text-on-surface';

const ETIQUETA =
  'text-zp-caption font-bold uppercase tracking-wide text-on-surface-variant';

interface Sede {
  id: string;
  codigo: string;
  nombre: string;
  direccion: string | null;
  telefono: string | null;
}

interface Config {
  nombre: string;
  terminos_condiciones: string | null;
  terminos_efectivos: string;
}

interface Props {
  tenant: string;
  sedes: Sede[];
  config: Config;
  puedeEditarSedes: boolean;
  puedeEditarConfig: boolean;
}

export default function DatosParqueadero({
  tenant, sedes: sedesIniciales, config: configInicial,
  puedeEditarSedes, puedeEditarConfig,
}: Props) {
  const [sedes, setSedes] = useState(sedesIniciales);
  const [config, setConfig] = useState(configInicial);
  const [terminos, setTerminos] = useState(configInicial.terminos_condiciones ?? '');
  const [ocupado, setOcupado] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);

  async function pedir(ruta: string, init: RequestInit) {
    setOcupado(true);
    setError(null);
    setOk(null);
    try {
      const res = await fetch(`/api/v1/t/${tenant}${ruta}`, init);
      const datos = await res.json().catch(() => null);
      if (!res.ok) {
        setError(
          typeof datos?.detail === 'string'
            ? datos.detail
            : (datos?.detail?.[0]?.msg ?? 'No se pudo guardar'),
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

  async function guardarSede(sede: Sede) {
    const datos = await pedir(`/sedes/${sede.id}`, {
      method: 'PATCH',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        nombre: sede.nombre,
        direccion: sede.direccion,
        telefono: sede.telefono,
      }),
    });
    if (datos) {
      setSedes(sedes.map((s) => (s.id === sede.id ? { ...s, ...datos } : s)));
      setOk(`${sede.nombre} actualizada`);
    }
  }

  async function guardarTextos(campos: Record<string, string | null>, hecho: string) {
    const datos = await pedir('/config', {
      method: 'PATCH',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(campos),
    });
    if (datos) {
      setConfig(datos);
      setTerminos(datos.terminos_condiciones ?? '');
      setOk(hecho);
    }
  }

  function cambiar(id: string, campo: keyof Sede, valor: string) {
    setSedes(sedes.map((s) => (s.id === id ? { ...s, [campo]: valor } : s)));
  }

  return (
    <div className="space-y-8">
      {error && (
        <p className="rounded-zp border-2 border-error bg-surface-container-lowest px-4 py-3
                      text-zp-body font-bold text-error">
          {error}
        </p>
      )}
      {ok && (
        <p className="rounded-zp border-2 border-success bg-surface-container-lowest px-4 py-3
                      text-zp-body font-bold text-success">
          {ok}
        </p>
      )}

      {/* ── Dónde y a quién llamar ─────────────────────────────────── */}
      <section className="space-y-4">
        <div>
          <h2 className="text-zp-lg font-extrabold">Dirección y teléfono</h2>
          <p className="mt-1 text-zp-body text-on-surface-variant">
            Es lo que aparece en el recibo del cliente. Si algo pasa con su vehículo,
            este es el número al que va a llamar.
          </p>
        </div>

        <ul className="space-y-4">
          {sedes.map((s) => (
            <li key={s.id}
                className="space-y-4 rounded-zp border-2 border-outline
                           bg-surface-container-lowest p-5">
              <p className="text-zp-body font-extrabold">{s.codigo}</p>

              <label className="block space-y-1.5">
                <span className={ETIQUETA}>Nombre de la sede</span>
                <input value={s.nombre} disabled={!puedeEditarSedes}
                       onChange={(e) => cambiar(s.id, 'nombre', e.target.value)}
                       className={CAMPO} />
              </label>

              <label className="block space-y-1.5">
                <span className={ETIQUETA}>Dirección</span>
                <input value={s.direccion ?? ''} disabled={!puedeEditarSedes}
                       placeholder="Calle 100 #15-20"
                       onChange={(e) => cambiar(s.id, 'direccion', e.target.value)}
                       className={CAMPO} />
              </label>

              <label className="block space-y-1.5">
                <span className={ETIQUETA}>Teléfono</span>
                <input value={s.telefono ?? ''} disabled={!puedeEditarSedes}
                       inputMode="tel" placeholder="310 555 0101"
                       onChange={(e) => cambiar(s.id, 'telefono', e.target.value)}
                       className={CAMPO} />
              </label>

              {puedeEditarSedes && (
                <button onClick={() => guardarSede(s)} disabled={ocupado}
                        className="rounded-zp border-2 border-outline bg-primary px-5 py-3
                                   text-zp-body font-extrabold uppercase tracking-wide
                                   text-on-primary disabled:bg-surface-container-high
                                   disabled:text-on-surface-variant">
                  Guardar
                </button>
              )}
            </li>
          ))}
        </ul>
      </section>

      {/* ── El reglamento ───────────────────────────────────────────── */}
      <section className="space-y-4">
        <div>
          <h2 className="text-zp-lg font-extrabold">Términos y condiciones</h2>
          <p className="mt-1 text-zp-body text-on-surface-variant">
            El reglamento completo, al pie del recibo y en letra pequeña. Déjalo en
            blanco para usar el que trae ZonePark.
          </p>
        </div>

        <label className="block space-y-1.5">
          <span className={ETIQUETA}>Tu reglamento</span>
          <textarea
            value={terminos}
            disabled={!puedeEditarConfig}
            rows={10}
            maxLength={2000}
            placeholder={config.terminos_efectivos}
            onChange={(e) => setTerminos(e.target.value)}
            className={`${CAMPO} resize-y`}
          />
        </label>
        <p className="text-zp-caption text-on-surface-variant">
          {terminos.length}/2000
          {!terminos.trim() && ' · en blanco se muestra el texto de ejemplo de arriba'}
        </p>

        {puedeEditarConfig && (
          <button
            onClick={() =>
              guardarTextos(
                { terminos_condiciones: terminos.trim() || null },
                'Términos actualizados',
              )
            }
            disabled={ocupado}
            className="rounded-zp border-2 border-outline bg-primary px-5 py-3
                       text-zp-body font-extrabold uppercase tracking-wide
                       text-on-primary disabled:bg-surface-container-high
                       disabled:text-on-surface-variant"
          >
            Guardar términos
          </button>
        )}

        <div className="rounded-zp border-2 border-outline-variant
                        bg-surface-container-lowest p-4">
          <p className={ETIQUETA}>Así lo verá el cliente</p>
          <p className="recibo-mono mt-2 text-justify text-zp-caption leading-relaxed
                        text-on-surface-variant">
            {terminos.trim() || config.terminos_efectivos}
          </p>
        </div>
      </section>
    </div>
  );
}
