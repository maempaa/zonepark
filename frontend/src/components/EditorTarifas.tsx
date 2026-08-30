import { useEffect, useMemo, useState } from 'react';

/**
 * Editor de tarifas.
 *
 * El modelo del backend manda sobre la interfaz: un plan publicado no se
 * edita, se versiona. Así que aquí no hay un "guardar" que cambie lo que
 * está cobrando ahora mismo; hay un borrador que se prueba y se publica.
 *
 * El simulador vive dentro de este mismo componente y no aparte porque
 * apunta al borrador que se está editando: probar la tarifa vieja mientras
 * se escribe la nueva no serviría de nada.
 *
 * Lo que no se edita aquí —el modo de cobro, los escalones, las franjas
 * horarias— se muestra y se conserva intacto al versionar. Cambiar eso es
 * rehacer la estructura del plan, no ajustar un precio, y merece su propia
 * pantalla.
 */

interface Tipo { id: string; codigo: string; nombre: string }
interface Escalon {
  desde_minuto: number;
  hasta_minuto: number | null;
  precio: string;
  unidad: string;
  bloque_minutos: number;
}
interface Franja {
  dias: number[];
  desde_hora: string;
  hasta_hora: string;
  incluye_festivos: boolean;
  solo_festivos: boolean;
}
interface Regla {
  codigo: string;
  vehicle_type_id: string;
  modo: string;
  precio_minuto: string;
  precio_bloque: string;
  precio_plena: string;
  precio_dia: string;
  bloque_minutos: number;
  dia_horas: number;
  gracia_minutos: number;
  cobro_minimo: string | null;
  tope_diario: string | null;
  tarifa_ticket_perdido: string | null;
  redondeo_modo: string;
  redondeo_paso: number;
  impuesto_modo: string;
  impuesto_tasa: string;
  prioridad: number;
  escalones: Escalon[];
  franja: Franja | null;
}
interface Plan {
  id: string;
  codigo: string;
  nombre: string;
  version: number;
  estado: string;
}

const MODOS: Record<string, string> = {
  por_minuto: 'Por minuto',
  por_bloque: 'Por fracción',
  primer_bloque_luego_minuto: 'Primer bloque y luego minutos',
  escalonado: 'Escalonado',
  plena: 'Tarifa plena',
  por_dia: 'Por día',
  mensualidad: 'Mensualidad',
};

const DIAS = ['lun', 'mar', 'mié', 'jue', 'vie', 'sáb', 'dom'];

const ATAJOS: Array<[string, number]> = [
  ['10 min', 10], ['45 min', 45], ['1 h', 60],
  ['2 h 17', 137], ['8 h', 480], ['1 día', 1440], ['3 días', 4320],
];

function pesos(v: string | number | null): string {
  if (v === null || v === '') return '—';
  return new Intl.NumberFormat('es-CO', {
    style: 'currency', currency: 'COP', maximumFractionDigits: 0,
  }).format(Number(v));
}

/** Convierte una regla de la API al formato que se manda de vuelta. */
function aEditable(r: any): Regla {
  return {
    codigo: r.codigo,
    vehicle_type_id: r.vehicle_type_id,
    modo: r.modo,
    precio_minuto: r.precio_minuto,
    precio_bloque: r.precio_bloque,
    precio_plena: r.precio_plena,
    precio_dia: r.precio_dia,
    bloque_minutos: r.bloque_minutos,
    dia_horas: r.dia_horas,
    gracia_minutos: r.gracia_minutos,
    cobro_minimo: r.cobro_minimo,
    tope_diario: r.tope_diario,
    tarifa_ticket_perdido: r.tarifa_ticket_perdido,
    redondeo_modo: r.redondeo_modo,
    redondeo_paso: r.redondeo_paso,
    impuesto_modo: r.impuesto_modo,
    impuesto_tasa: r.impuesto_tasa,
    prioridad: r.prioridad,
    escalones: r.escalones ?? [],
    franja: r.tiene_franja
      ? {
          dias: r.franja_dias ?? [0, 1, 2, 3, 4, 5, 6],
          desde_hora: r.franja_desde,
          hasta_hora: r.franja_hasta,
          incluye_festivos: r.franja_incluye_festivos,
          solo_festivos: r.franja_solo_festivos,
        }
      : null,
  };
}

const CAMPO =
  'w-full rounded-zp border-2 border-outline bg-surface-container-lowest px-3 py-2 ' +
  'text-zp-body font-semibold text-on-surface tabular-nums';
const BOTON_PRIMARIO =
  'rounded-zp border-2 border-outline bg-primary px-5 py-3 text-zp-body font-extrabold ' +
  'uppercase tracking-wide text-on-primary active:bg-primary-container ' +
  'disabled:border-outline-variant disabled:bg-surface-container-high ' +
  'disabled:text-on-surface-variant';
const BOTON_LLANO =
  'rounded-zp border-2 border-outline bg-surface-container-lowest px-5 py-3 text-zp-body ' +
  'font-bold active:bg-surface-container';

function Icono({ d, className = 'h-5 w-5' }: { d: string; className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor"
         strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {d.split('|').map((p, i) => <path key={i} d={p} />)}
    </svg>
  );
}

interface Props {
  tenant: string;
  planes: Plan[];
  tipos: Tipo[];
}

export default function EditorTarifas({ tenant, planes: iniciales, tipos }: Props) {
  const [planes, setPlanes] = useState(iniciales);
  const [reglas, setReglas] = useState<Regla[] | null>(null);
  const [sucio, setSucio] = useState(false);
  const [ocupado, setOcupado] = useState(false);
  const [error, setError] = useState('');
  const [aviso, setAviso] = useState('');

  // Primera tarifa: un precio por tipo de vehículo. No se inventa ninguno,
  // los pone el cliente.
  const [primeros, setPrimeros] = useState<Record<string, { precio: string; bloque: string }>>(
    () => Object.fromEntries(tipos.map((t) => [t.id, { precio: '', bloque: '60' }])),
  );

  const activo = planes.find((p) => p.estado === 'activo') ?? null;
  const borrador = planes.find((p) => p.estado === 'borrador') ?? null;

  // Simulador, siempre apuntando al borrador si lo hay.
  const objetivo = borrador ?? activo;
  const [tipoSim, setTipoSim] = useState(tipos[0]?.id ?? '');
  const [minutos, setMinutos] = useState(137);
  const [cotizacion, setCotizacion] = useState<any>(null);

  const nombreTipo = useMemo(
    () => Object.fromEntries(tipos.map((t) => [t.id, t.nombre])),
    [tipos],
  );

  async function pedir(ruta: string, opciones?: RequestInit) {
    setOcupado(true);
    setError('');
    try {
      const res = await fetch(`/api/v1/t/${tenant}${ruta}`, opciones);
      const datos = res.status === 204 ? null : await res.json();
      if (!res.ok) {
        const d = datos?.detail;
        setError(
          typeof d === 'string' ? d : (d?.[0]?.msg ?? 'No se pudo completar la operación'),
        );
        return null;
      }
      return datos ?? true;
    } catch {
      setError('Sin conexión con el servidor');
      return null;
    } finally {
      setOcupado(false);
    }
  }

  async function recargarPlanes() {
    const lista = await pedir('/planes');
    if (lista) setPlanes(lista);
    return lista;
  }

  // Carga las reglas del borrador cuando aparece.
  useEffect(() => {
    if (!borrador) {
      setReglas(null);
      return;
    }
    let cancelado = false;
    void (async () => {
      const detalle = await pedir(`/planes/${borrador.id}`);
      if (!cancelado && detalle) {
        setReglas(detalle.reglas.map(aEditable));
        setSucio(false);
      }
    })();
    return () => { cancelado = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [borrador?.id]);

  // Simula cada vez que cambia algo relevante.
  useEffect(() => {
    if (!objetivo || !tipoSim) return;
    let cancelado = false;
    const t = setTimeout(async () => {
      const entrada = new Date('2026-08-24T13:00:00Z');
      const salida = new Date(entrada.getTime() + minutos * 60_000);
      try {
        const res = await fetch(`/api/v1/t/${tenant}/planes/${objetivo.id}/simular`, {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({
            vehicle_type_id: tipoSim,
            entrada: entrada.toISOString(),
            salida: salida.toISOString(),
          }),
        });
        const d = await res.json();
        if (!cancelado) setCotizacion(res.ok ? d : null);
      } catch {
        if (!cancelado) setCotizacion(null);
      }
    }, 250);
    return () => { cancelado = true; clearTimeout(t); };
  }, [tenant, objetivo?.id, tipoSim, minutos, aviso]);

  function cambiar(i: number, campo: keyof Regla, valor: unknown) {
    setReglas((r) => r && r.map((x, j) => (j === i ? { ...x, [campo]: valor } : x)));
    setSucio(true);
  }

  async function crearPrimera(e: React.FormEvent) {
    e.preventDefault();
    const reglas = Object.entries(primeros)
      .filter(([, v]) => v.precio.trim() !== '')
      .map(([tipoId, v]) => ({
        codigo: `${tipos.find((t) => t.id === tipoId)?.codigo ?? tipoId}-general`,
        vehicle_type_id: tipoId,
        modo: 'por_bloque',
        precio_bloque: v.precio,
        bloque_minutos: Number(v.bloque) || 60,
        gracia_minutos: 15,
        redondeo_modo: 'cercano',
        redondeo_paso: 50,
      }));

    if (reglas.length === 0) {
      setError('Pon al menos un precio para poder crear la tarifa');
      return;
    }

    const creado = await pedir('/planes', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ codigo: 'general', nombre: 'Tarifa general', reglas }),
    });
    if (creado) {
      await recargarPlanes();
      setAviso('Borrador creado. Pruébalo abajo y publícalo cuando cuadre.');
    }
  }

  async function crearVersion() {
    if (!activo) return;
    const detalle = await pedir(`/planes/${activo.id}`);
    if (!detalle) return;
    const copia = await pedir('/planes', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        codigo: detalle.codigo,
        nombre: detalle.nombre,
        reglas: detalle.reglas.map(aEditable),
      }),
    });
    if (copia) {
      await recargarPlanes();
      setAviso('Borrador creado a partir de la tarifa vigente');
    }
  }

  async function guardar() {
    if (!borrador || !reglas) return;
    const guardado = await pedir(`/planes/${borrador.id}/reglas`, {
      method: 'PUT',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(reglas),
    });
    if (guardado) {
      setSucio(false);
      setAviso('Borrador guardado. Pruébalo abajo antes de publicar.');
    }
  }

  async function publicar() {
    if (!borrador) return;
    if (sucio) {
      setError('Guarda los cambios antes de publicar');
      return;
    }
    const ok = await pedir(`/planes/${borrador.id}/activar`, { method: 'POST' });
    if (ok) {
      await recargarPlanes();
      setAviso('Tarifa publicada. Los tickets abiertos siguen con la anterior.');
    }
  }

  async function descartar() {
    if (!borrador) return;
    const ok = await pedir(`/planes/${borrador.id}`, { method: 'DELETE' });
    if (ok) {
      await recargarPlanes();
      setReglas(null);
      setAviso('Borrador descartado');
    }
  }

  return (
    <div className="space-y-6">
      {(error || aviso) && (
        <p
          role="alert"
          className={`flex items-start gap-3 rounded-zp border-2 px-4 py-3 text-zp-body
                      font-semibold bg-surface-container-lowest ${
                        error ? 'border-error text-error' : 'border-success text-success'
                      }`}
        >
          <Icono
            d={error ? 'M12 7v6|M12 16.5v.01' : 'm4 12 6 6L20 6'}
            className="h-6 w-6 shrink-0"
          />
          <span>{error || aviso}</span>
        </p>
      )}

      {/* ── Primera tarifa ────────────────────────────────────────────── */}
      {planes.length === 0 && (
        <section className="rounded-zp border-2 border-outline bg-surface-container-lowest p-6">
          <h2 className="text-zp-lg font-extrabold">Todavía no hay ninguna tarifa</h2>
          <p className="mt-2 text-zp-body text-on-surface-variant">
            Pon cuánto cobras por cada tipo de vehículo. Lo más común es cobrar por hora o
            fracción: una hora empezada se cobra completa. Podrás cambiarlo y añadir tarifas
            nocturnas o de festivo cuando quieras.
          </p>

          {tipos.length === 0 ? (
            <p className="mt-5 rounded-zp border-2 border-warning px-4 py-3 text-zp-body">
              Antes necesitas tipos de vehículo.{' '}
              <a href={`/t/${tenant}/config/catalogo`}
                 className="font-bold underline underline-offset-4">
                Créalos en el catálogo
              </a>
              .
            </p>
          ) : (
            <form onSubmit={crearPrimera} className="mt-6 space-y-4">
              <ul className="space-y-3">
                {tipos.map((t) => (
                  <li key={t.id}
                      className="flex flex-wrap items-end gap-4 rounded-zp border-2
                                 border-outline-variant p-4">
                    <p className="min-w-32 flex-1 text-zp-body font-bold">{t.nombre}</p>
                    <label className="w-40 space-y-1.5">
                      <span className="text-zp-caption font-bold uppercase tracking-wide
                                       text-on-surface-variant">Precio</span>
                      <input
                        inputMode="numeric"
                        value={primeros[t.id]?.precio ?? ''}
                        placeholder="3000"
                        onChange={(e) =>
                          setPrimeros({
                            ...primeros,
                            [t.id]: {
                              ...primeros[t.id],
                              precio: e.target.value.replace(/\D/g, ''),
                            },
                          })
                        }
                        className={`${CAMPO} text-right`}
                      />
                    </label>
                    <label className="w-40 space-y-1.5">
                      <span className="text-zp-caption font-bold uppercase tracking-wide
                                       text-on-surface-variant">Cada … minutos</span>
                      <input
                        inputMode="numeric"
                        value={primeros[t.id]?.bloque ?? '60'}
                        onChange={(e) =>
                          setPrimeros({
                            ...primeros,
                            [t.id]: {
                              ...primeros[t.id],
                              bloque: e.target.value.replace(/\D/g, ''),
                            },
                          })
                        }
                        className={`${CAMPO} text-right`}
                      />
                    </label>
                  </li>
                ))}
              </ul>
              <p className="text-zp-caption text-on-surface-variant">
                Los tipos que dejes sin precio quedan fuera de la tarifa y no se les podrá
                registrar el ingreso. Se incluye una cortesía de 15 minutos y redondeo a $50,
                ajustables después.
              </p>
              <button type="submit" disabled={ocupado} className={BOTON_PRIMARIO}>
                {ocupado ? 'Creando…' : 'Crear la primera tarifa'}
              </button>
            </form>
          )}
        </section>
      )}

      {/* ── Estado y acciones ─────────────────────────────────────────── */}
      {planes.length > 0 && (
      <section className="rounded-zp border-2 border-outline bg-surface-container-lowest p-5">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <p className="text-zp-caption font-bold uppercase tracking-wide text-on-surface-variant">
              Tarifa vigente
            </p>
            <p className="mt-1 text-zp-lg font-extrabold">
              {activo ? `${activo.nombre} · v${activo.version}` : 'Ninguna publicada'}
            </p>
          </div>
          {!borrador && activo && (
            <button onClick={crearVersion} disabled={ocupado} className={BOTON_PRIMARIO}>
              Crear nueva versión
            </button>
          )}
        </div>
        {!borrador && activo && (
          <p className="mt-3 text-zp-caption text-on-surface-variant">
            Una tarifa publicada no se edita: se crea una versión nueva, se prueba y se
            publica. Así un ticket abierto hace días conserva la tarifa con la que entró.
          </p>
        )}
      </section>
      )}

      {/* ── Editor del borrador ───────────────────────────────────────── */}
      {borrador && reglas && (
        <section className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 className="text-zp-lg font-extrabold">
              Borrador v{borrador.version}
              {sucio && (
                <span className="ml-3 rounded-zp border-2 border-warning px-2 py-0.5
                                 text-zp-caption font-bold uppercase tracking-wide">
                  sin guardar
                </span>
              )}
            </h2>
            <div className="flex flex-wrap gap-3">
              <button onClick={guardar} disabled={ocupado || !sucio} className={BOTON_LLANO}>
                Guardar
              </button>
              <button onClick={publicar} disabled={ocupado || sucio} className={BOTON_PRIMARIO}>
                Publicar
              </button>
              <button
                onClick={descartar}
                disabled={ocupado}
                className="rounded-zp border-2 border-error px-4 py-3 text-zp-body font-bold
                           text-error active:bg-surface-container"
              >
                Descartar
              </button>
            </div>
          </div>

          <ul className="space-y-4">
            {reglas.map((r, i) => (
              <li
                key={r.codigo}
                className="rounded-zp border-2 border-outline bg-surface-container-lowest p-5"
              >
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <p className="text-zp-lg font-extrabold">
                    {nombreTipo[r.vehicle_type_id] ?? 'Tipo desconocido'}
                  </p>
                  <p className="text-zp-caption font-bold uppercase tracking-wide
                                text-on-surface-variant">
                    {MODOS[r.modo] ?? r.modo}
                    {r.franja && (
                      <> · {r.franja.solo_festivos
                        ? 'festivos'
                        : `${r.franja.desde_hora.slice(0, 5)}–${r.franja.hasta_hora.slice(0, 5)}`}
                      </>
                    )}
                  </p>
                </div>

                {r.franja && !r.franja.solo_festivos && r.franja.dias.length < 7 && (
                  <p className="mt-1 text-zp-caption text-on-surface-variant">
                    {r.franja.dias.map((d) => DIAS[d]).join(', ')}
                  </p>
                )}

                <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                  {(r.modo === 'por_bloque' || r.modo === 'primer_bloque_luego_minuto') && (
                    <>
                      <Campo etiqueta="Precio por fracción"
                             valor={r.precio_bloque}
                             onChange={(v) => cambiar(i, 'precio_bloque', v)} />
                      <Campo etiqueta="Minutos por fracción" entero
                             valor={String(r.bloque_minutos)}
                             onChange={(v) => cambiar(i, 'bloque_minutos', Number(v) || 1)} />
                    </>
                  )}
                  {(r.modo === 'por_minuto' || r.modo === 'primer_bloque_luego_minuto') && (
                    <Campo etiqueta="Precio por minuto"
                           valor={r.precio_minuto}
                           onChange={(v) => cambiar(i, 'precio_minuto', v)} />
                  )}
                  {r.modo === 'plena' && (
                    <Campo etiqueta="Precio único"
                           valor={r.precio_plena}
                           onChange={(v) => cambiar(i, 'precio_plena', v)} />
                  )}
                  {r.modo === 'por_dia' && (
                    <>
                      <Campo etiqueta="Precio por día"
                             valor={r.precio_dia}
                             onChange={(v) => cambiar(i, 'precio_dia', v)} />
                      <Campo etiqueta="Horas por día" entero
                             valor={String(r.dia_horas)}
                             onChange={(v) => cambiar(i, 'dia_horas', Number(v) || 24)} />
                    </>
                  )}

                  <Campo etiqueta="Cortesía (min)" entero
                         valor={String(r.gracia_minutos)}
                         onChange={(v) => cambiar(i, 'gracia_minutos', Number(v) || 0)} />
                  <Campo etiqueta="Cobro mínimo" opcional
                         valor={r.cobro_minimo ?? ''}
                         onChange={(v) => cambiar(i, 'cobro_minimo', v || null)} />
                  <Campo etiqueta="Tope por 24 h" opcional
                         valor={r.tope_diario ?? ''}
                         onChange={(v) => cambiar(i, 'tope_diario', v || null)} />
                  <Campo etiqueta="Redondear a" entero
                         valor={String(r.redondeo_paso)}
                         onChange={(v) => cambiar(i, 'redondeo_paso', Number(v) || 0)} />
                </div>

                {r.escalones.length > 0 && (
                  <div className="mt-4 rounded-zp border-2 border-outline-variant p-3">
                    <p className="text-zp-caption font-bold uppercase tracking-wide
                                  text-on-surface-variant">
                      Escalones (se conservan al versionar)
                    </p>
                    <ul className="mt-2 space-y-1">
                      {r.escalones.map((e, k) => (
                        <li key={k} className="text-zp-caption tabular-nums">
                          {e.desde_minuto}–{e.hasta_minuto ?? '∞'} min · {pesos(e.precio)} por{' '}
                          {e.unidad === 'fijo' ? 'el tramo' : e.unidad}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* ── Simulador ─────────────────────────────────────────────────── */}
      {objetivo && (
        <section className="space-y-4">
          <div>
            <h2 className="text-zp-lg font-extrabold">Simulador</h2>
            <p className="mt-1 text-zp-caption text-on-surface-variant">
              Cotiza contra{' '}
              {borrador ? `el borrador v${borrador.version}` : `la tarifa vigente`}. Guarda los
              cambios para verlos reflejados aquí.
            </p>
          </div>

          <div className="flex flex-wrap gap-3">
            {tipos.map((t) => (
              <button
                key={t.id}
                onClick={() => setTipoSim(t.id)}
                aria-pressed={t.id === tipoSim}
                className={`rounded-zp border-2 border-outline px-4 py-3 text-zp-body font-bold ${
                  t.id === tipoSim
                    ? 'bg-primary text-on-primary'
                    : 'bg-surface-container-lowest active:bg-surface-container'
                }`}
              >
                {t.nombre}
              </button>
            ))}
          </div>

          <div className="flex flex-wrap gap-2">
            {ATAJOS.map(([texto, m]) => (
              <button
                key={texto}
                onClick={() => setMinutos(m)}
                aria-pressed={m === minutos}
                className={`rounded-zp border-2 px-3 py-2 text-zp-caption font-bold ${
                  m === minutos
                    ? 'border-outline bg-secondary text-on-secondary'
                    : 'border-outline-variant bg-surface-container-lowest'
                }`}
              >
                {texto}
              </button>
            ))}
          </div>

          {cotizacion ? (
            <div className="overflow-hidden rounded-zp border-2 border-outline
                            bg-surface-container-lowest">
              <div className="flex items-baseline justify-between gap-3 border-b-2
                              border-outline px-4 py-3">
                <p className="text-zp-caption text-on-surface-variant">
                  {cotizacion.minutos} min · <code>{cotizacion.regla_aplicada}</code>
                </p>
                <p className="text-zp-xl font-extrabold tabular-nums">
                  {pesos(cotizacion.total)}
                </p>
              </div>
              <ul>
                {cotizacion.lineas.map((l: any, k: number) => (
                  <li key={k} className="flex items-baseline justify-between gap-3 border-b
                                         border-outline-variant px-4 py-2 last:border-0">
                    <span className="text-zp-caption">
                      {l.concepto}
                      {l.detalle && (
                        <span className="text-on-surface-variant"> · {l.detalle}</span>
                      )}
                    </span>
                    <span className="shrink-0 text-zp-caption tabular-nums">
                      {pesos(l.monto)}
                    </span>
                  </li>
                ))}
              </ul>
              {(cotizacion.en_cortesia || cotizacion.tope_aplicado || cotizacion.minimo_aplicado) && (
                <div className="flex flex-wrap gap-2 px-4 py-3">
                  {cotizacion.en_cortesia && <Etiqueta texto="Cortesía" />}
                  {cotizacion.tope_aplicado && <Etiqueta texto="Tope diario" />}
                  {cotizacion.minimo_aplicado && <Etiqueta texto="Cobro mínimo" />}
                </div>
              )}
            </div>
          ) : (
            <p className="rounded-zp border-2 border-outline-variant px-4 py-3 text-zp-caption
                          text-on-surface-variant">
              Este plan no tiene tarifa para ese tipo de vehículo.
            </p>
          )}
        </section>
      )}

      {/* ── Historial ─────────────────────────────────────────────────── */}
      {planes.length > 0 && (
      <section className="space-y-3">
        <h2 className="text-zp-caption font-bold uppercase tracking-wide text-on-surface-variant">
          Versiones
        </h2>
        <ul className="overflow-hidden rounded-zp border-2 border-outline
                       bg-surface-container-lowest">
          {planes.map((p) => (
            <li key={p.id} className="flex items-center justify-between gap-3 border-b
                                      border-outline-variant px-4 py-3 last:border-0">
              <span className="text-zp-body">
                <strong>{p.nombre}</strong>{' '}
                <span className="text-on-surface-variant">v{p.version}</span>
              </span>
              <span
                className={`shrink-0 rounded-zp border-2 border-outline px-2.5 py-0.5
                            text-zp-caption font-bold uppercase tracking-wide ${
                              p.estado === 'activo'
                                ? 'bg-primary text-on-primary'
                                : p.estado === 'borrador'
                                  ? 'bg-surface-container-lowest'
                                  : 'bg-surface-container-high text-on-surface-variant'
                            }`}
              >
                {p.estado}
              </span>
            </li>
          ))}
        </ul>
      </section>
      )}
    </div>
  );
}

function Campo({
  etiqueta, valor, onChange, entero = false, opcional = false,
}: {
  etiqueta: string;
  valor: string;
  onChange: (v: string) => void;
  entero?: boolean;
  opcional?: boolean;
}) {
  return (
    <label className="block space-y-1.5">
      <span className="text-zp-caption font-bold uppercase tracking-wide text-on-surface-variant">
        {etiqueta}
      </span>
      <input
        inputMode="numeric"
        value={valor}
        placeholder={opcional ? 'sin límite' : '0'}
        onChange={(e) => {
          const limpio = e.target.value.replace(/[^\d.]/g, '');
          onChange(entero ? limpio.replace(/\./g, '') : limpio);
        }}
        className={CAMPO}
      />
    </label>
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
