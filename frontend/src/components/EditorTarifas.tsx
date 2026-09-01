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
  nombre: string | null;
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
  activa: boolean;
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

/**
 * Esquemas de cobro tal como los nombra un parqueadero, no como los llama
 * el motor. "Por hora" y "Por fracción" son el mismo modo por dentro
 * —bloques de tiempo— y solo se diferencian en el tamaño del bloque; que
 * el administrador tenga que saber eso no aporta nada.
 */
interface Esquema {
  clave: string;
  etiqueta: string;
  descripcion: string;
  modo: string;
  /** Minutos del bloque, cuando el esquema los fija. */
  bloque?: number;
  /** Campos de precio que el esquema necesita. */
  precios: Array<'precio_bloque' | 'precio_minuto' | 'precio_plena' | 'precio_dia'>;
  /** Si el administrador puede ajustar el tamaño del bloque. */
  bloqueEditable?: boolean;
  diaEditable?: boolean;
}

const ESQUEMAS: Esquema[] = [
  {
    clave: 'hora',
    etiqueta: 'Por hora',
    descripcion: 'Cada hora empezada se cobra completa',
    modo: 'por_bloque',
    bloque: 60,
    precios: ['precio_bloque'],
  },
  {
    clave: 'fraccion',
    etiqueta: 'Por fracción',
    descripcion: 'Cada fracción empezada se cobra completa',
    modo: 'por_bloque',
    precios: ['precio_bloque'],
    bloqueEditable: true,
  },
  {
    clave: 'minuto',
    etiqueta: 'Por minuto',
    descripcion: 'Se cobra el tiempo exacto',
    modo: 'por_minuto',
    precios: ['precio_minuto'],
  },
  {
    clave: 'primera_luego_minuto',
    etiqueta: 'Primer bloque y luego minutos',
    descripcion: 'El primer bloque completo, después al minuto',
    modo: 'primer_bloque_luego_minuto',
    precios: ['precio_bloque', 'precio_minuto'],
    bloqueEditable: true,
  },
  {
    clave: 'plena',
    etiqueta: 'Tarifa plena',
    descripcion: 'Un precio único, sin importar el tiempo',
    modo: 'plena',
    precios: ['precio_plena'],
  },
  {
    clave: 'dia',
    etiqueta: 'Por día',
    descripcion: 'Cada día empezado se cobra completo',
    modo: 'por_dia',
    precios: ['precio_dia'],
    diaEditable: true,
  },
];

const ETIQUETA_PRECIO: Record<string, string> = {
  precio_bloque: 'Precio',
  precio_minuto: 'Precio por minuto',
  precio_plena: 'Precio único',
  precio_dia: 'Precio por día',
};

/** El esquema que corresponde a una regla ya guardada. */
function esquemaDe(regla: { modo: string; bloque_minutos: number }): Esquema | null {
  if (regla.modo === 'por_bloque') {
    return ESQUEMAS.find((e) => e.clave === (regla.bloque_minutos === 60 ? 'hora' : 'fraccion'))!;
  }
  return ESQUEMAS.find((e) => e.modo === regla.modo) ?? null;
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
    nombre: r.nombre ?? null,
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
    // Las tarifas creadas antes de poder apagarlas estaban todas en uso.
    activa: r.activa ?? true,
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

const ALERTA = 'M12 7v6|M12 16.5v.01';

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
  const [primeros, setPrimeros] = useState<
    Record<string, { esquema: string; precio: string; bloque: string }>
  >(() =>
    Object.fromEntries(tipos.map((t) => [t.id, { esquema: 'hora', precio: '', bloque: '30' }])),
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

  // ── Rejilla de tarifas ────────────────────────────────────────────────
  // Un vehículo puede tener varias formas de cobro a la vez: por hora,
  // por fracción, por minuto, plena. Cada una se enciende o se apaga sin
  // perder su precio, y una queda marcada como la que se aplica sola.
  //
  // Cada fila de la rejilla es una regla del plan. Se busca por el esquema
  // y no por el código, para que las tarifas que ya existían con nombres
  // como "carro-general" caigan en su fila sin renombrarlas.

  /* Cada regla ocupa a lo sumo una casilla de la rejilla. Se reparten por
     código exacto primero, porque "por bloque de 60 minutos" es a la vez
     "por hora" y "una fracción de una hora": sin el código, una fracción
     puesta en 60 caería en la fila de al lado y se pisarían el precio.
     Las que vienen de antes (carro-general) no traen código de esquema y
     caen por su forma de cobrar, que es como se editaban hasta ahora. */
  const rejilla = useMemo(() => {
    const mapa = new Map<string, Record<string, { regla: Regla; i: number }>>();
    if (!reglas) return mapa;

    const codigoEsquema = (r: Regla) => {
      const tipo = tipos.find((t) => t.id === r.vehicle_type_id);
      return ESQUEMAS.find((e) => r.codigo === `${tipo?.codigo}-${e.clave}`)?.clave ?? null;
    };

    const candidatas = reglas
      .map((regla, i) => ({ regla, i }))
      .filter(({ regla }) => !regla.franja && esquemaDe(regla));

    for (const pasada of [codigoEsquema, (r: Regla) => esquemaDe(r)?.clave ?? null]) {
      for (const { regla, i } of candidatas) {
        const clave = pasada(regla);
        if (!clave) continue;
        const filas = mapa.get(regla.vehicle_type_id) ?? {};
        if (filas[clave]) continue;
        filas[clave] = { regla, i };
        mapa.set(regla.vehicle_type_id, filas);
      }
    }
    return mapa;
  }, [reglas, tipos]);

  function filaDe(tipoId: string, clave: string): { regla: Regla; i: number } | null {
    return rejilla.get(tipoId)?.[clave] ?? null;
  }

  function reglaVacia(tipoId: string, esquema: Esquema): Regla {
    const tipo = tipos.find((t) => t.id === tipoId);
    return {
      codigo: `${tipo?.codigo ?? tipoId}-${esquema.clave}`,
      nombre: null,
      vehicle_type_id: tipoId,
      modo: esquema.modo,
      precio_minuto: '0', precio_bloque: '0', precio_plena: '0', precio_dia: '0',
      bloque_minutos: esquema.bloque ?? 30,
      dia_horas: 24,
      gracia_minutos: 0,
      cobro_minimo: null, tope_diario: null, tarifa_ticket_perdido: null,
      redondeo_modo: 'cercano', redondeo_paso: 50,
      impuesto_modo: 'incluido', impuesto_tasa: '0',
      prioridad: 0, activa: true, escalones: [], franja: null,
    };
  }

  function alternarActiva(tipoId: string, esquema: Esquema) {
    if (!reglas) return;
    const encontrada = filaDe(tipoId, esquema.clave);

    if (!encontrada) {
      setReglas([...reglas, reglaVacia(tipoId, esquema)]);
    } else {
      setReglas(
        reglas.map((r, j) => (j === encontrada.i ? { ...r, activa: !r.activa } : r)),
      );
    }
    setSucio(true);
  }

  function ponerCampo(tipoId: string, esquema: Esquema, campo: keyof Regla, valor: unknown) {
    if (!reglas) return;
    const encontrada = filaDe(tipoId, esquema.clave);

    if (!encontrada) {
      setReglas([...reglas, { ...reglaVacia(tipoId, esquema), [campo]: valor }]);
    } else {
      setReglas(reglas.map((r, j) => (j === encontrada.i ? { ...r, [campo]: valor } : r)));
    }
    setSucio(true);
  }

  /**
   * Marca qué tarifa se aplica sola cuando nadie elige.
   *
   * Se hace con la prioridad, y solo entre las que no tienen franja: las
   * nocturnas y de festivo llevan prioridades más altas y tienen que
   * seguir ganando a su hora.
   */
  function marcarPredeterminada(tipoId: string, clave: string) {
    if (!reglas) return;
    setReglas(
      reglas.map((r) => {
        if (r.vehicle_type_id !== tipoId || r.franja) return r;
        return { ...r, prioridad: esquemaDe(r)?.clave === clave ? 1 : 0 };
      }),
    );
    setSucio(true);
  }

  function esPredeterminada(tipoId: string, clave: string): boolean {
    const activas = (reglas ?? []).filter(
      (r) => r.vehicle_type_id === tipoId && !r.franja && r.activa,
    );
    if (activas.length === 0) return false;
    const marcada = activas.find((r) => r.prioridad > 0);
    const elegida = marcada ?? activas[0];
    return esquemaDe(elegida)?.clave === clave;
  }

  /**
   * Los modificadores son del vehículo, no de cada tarifa.
   *
   * "Quince minutos de cortesía para los carros" es como lo piensa un
   * parqueadero. Tenerlos por tarifa obligaría a repetirlos y abriría la
   * puerta a que la cortesía dependiera de qué opción eligió el operario.
   */
  function ponerModificador(tipoId: string, campo: keyof Regla, valor: unknown) {
    if (!reglas) return;
    setReglas(
      reglas.map((r) => (r.vehicle_type_id === tipoId ? { ...r, [campo]: valor } : r)),
    );
    setSucio(true);
  }

  function modificadorDe(tipoId: string, campo: keyof Regla): string {
    const r = (reglas ?? []).find((x) => x.vehicle_type_id === tipoId);
    const v = r?.[campo];
    return v === null || v === undefined ? '' : String(v);
  }

  /** Filas encendidas a las que les falta el precio que su esquema pide. */
  const incompletas = (reglas ?? []).filter((r) => {
    if (!r.activa) return false;
    const esquema = esquemaDe(r);
    if (!esquema) return false;
    return esquema.precios.some((c) => !r[c] || Number(r[c]) <= 0);
  });

  /** Vehículos que se quedarían sin ninguna tarifa. */
  const sinTarifa = tipos.filter(
    (t) => !(reglas ?? []).some((r) => r.vehicle_type_id === t.id && r.activa),
  );

  async function crearPrimera(e: React.FormEvent) {
    e.preventDefault();
    const reglas = Object.entries(primeros)
      .filter(([, v]) => v.precio.trim() !== '')
      .map(([tipoId, v]) => {
        const esquema = ESQUEMAS.find((e) => e.clave === v.esquema)!;
        const base = {
          codigo: `${tipos.find((t) => t.id === tipoId)?.codigo ?? tipoId}-general`,
          vehicle_type_id: tipoId,
          modo: esquema.modo,
          gracia_minutos: 15,
          redondeo_modo: 'cercano',
          redondeo_paso: 50,
        };
        // El precio va al campo que su esquema usa.
        const campo = esquema.precios[0];
        const bloque = esquema.bloque ?? (Number(v.bloque) || 30);
        return campo === 'precio_bloque'
          ? { ...base, precio_bloque: v.precio, bloque_minutos: bloque }
          : { ...base, [campo]: v.precio };
      });

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
                {tipos.map((t) => {
                  const fila = primeros[t.id] ?? { esquema: 'hora', precio: '', bloque: '30' };
                  const esquema = ESQUEMAS.find((e) => e.clave === fila.esquema)!;
                  const poner = (cambio: Partial<typeof fila>) =>
                    setPrimeros({ ...primeros, [t.id]: { ...fila, ...cambio } });

                  return (
                    <li key={t.id}
                        className="space-y-3 rounded-zp border-2 border-outline-variant p-4">
                      <p className="text-zp-body font-bold">{t.nombre}</p>

                      <div className="flex flex-wrap gap-2">
                        {ESQUEMAS.filter((e) =>
                          ['hora', 'fraccion', 'minuto', 'plena'].includes(e.clave),
                        ).map((e) => (
                          <button
                            key={e.clave}
                            type="button"
                            onClick={() => poner({ esquema: e.clave })}
                            aria-pressed={fila.esquema === e.clave}
                            className={`rounded-zp border-2 border-outline px-3 py-2
                                        text-zp-caption font-bold ${
                                          fila.esquema === e.clave
                                            ? 'bg-primary text-on-primary'
                                            : 'bg-surface-container-lowest'
                                        }`}
                          >
                            {e.etiqueta}
                          </button>
                        ))}
                      </div>

                      <div className="flex flex-wrap items-end gap-4">
                        <label className="w-40 space-y-1.5">
                          <span className="text-zp-caption font-bold uppercase tracking-wide
                                           text-on-surface-variant">
                            {ETIQUETA_PRECIO[esquema.precios[0]]}
                          </span>
                          <input
                            inputMode="numeric"
                            value={fila.precio}
                            placeholder="3000"
                            onChange={(e) => poner({ precio: e.target.value.replace(/\D/g, '') })}
                            className={`${CAMPO} text-right`}
                          />
                        </label>

                        {esquema.bloqueEditable && (
                          <label className="w-40 space-y-1.5">
                            <span className="text-zp-caption font-bold uppercase tracking-wide
                                             text-on-surface-variant">Cada … minutos</span>
                            <input
                              inputMode="numeric"
                              value={fila.bloque}
                              onChange={(e) => poner({ bloque: e.target.value.replace(/\D/g, '') })}
                              className={`${CAMPO} text-right`}
                            />
                          </label>
                        )}

                        <p className="pb-2 text-zp-caption text-on-surface-variant">
                          {esquema.descripcion}
                        </p>
                      </div>
                    </li>
                  );
                })}
              </ul>
              <p className="text-zp-caption text-on-surface-variant">
                Cada tipo se cobra de una sola forma; podrás cambiarla después. Los que dejes
                sin precio quedan fuera de la tarifa y no se les podrá registrar el ingreso.
                Se incluye una cortesía de 15 minutos y redondeo a $50, ajustables después.
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
              <button
                onClick={guardar}
                disabled={ocupado || !sucio || incompletas.length > 0}
                className={BOTON_LLANO}
              >
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

          {sinTarifa.length > 0 && (
            <p className="flex items-start gap-3 rounded-zp border-2 border-warning
                          bg-surface-container-lowest px-4 py-3 text-zp-body">
              <Icono d={ALERTA} className="h-6 w-6 shrink-0" />
              <span>
                {sinTarifa.map((t) => t.nombre).join(', ')} se quedaría sin ninguna tarifa
                encendida, y no se le podrá registrar el ingreso.
              </span>
            </p>
          )}

          {incompletas.length > 0 && (
            <p className="flex items-start gap-3 rounded-zp border-2 border-warning
                          bg-surface-container-lowest px-4 py-3 text-zp-body">
              <Icono d={ALERTA} className="h-6 w-6 shrink-0" />
              <span>
                Falta el precio de{' '}
                {incompletas
                  .map((r) => `${nombreTipo[r.vehicle_type_id] ?? r.codigo} · ${esquemaDe(r)?.etiqueta ?? ''}`)
                  .join(', ')}
                . Una tarifa encendida en cero cobraría gratis.
              </span>
            </p>
          )}

          <ul className="space-y-5">
            {tipos.map((tipo) => {
              const franjas = (reglas ?? []).filter(
                (r) => r.vehicle_type_id === tipo.id && r.franja,
              );
              const enRejilla = new Set(
                Object.values(rejilla.get(tipo.id) ?? {}).map((f) => f.i),
              );
              const otras = (reglas ?? []).filter(
                (r, i) => r.vehicle_type_id === tipo.id && !r.franja && !enRejilla.has(i),
              );

              return (
                <li key={tipo.id}
                    className="rounded-zp border-2 border-outline bg-surface-container-lowest p-5">
                  <p className="text-zp-lg font-extrabold">{tipo.nombre}</p>
                  <p className="mt-1 text-zp-caption text-on-surface-variant">
                    Enciende las formas de cobro que ofreces. Quien cobra elige entre ellas al
                    cerrar el ticket; la marcada como predeterminada es la que se aplica sola.
                  </p>

                  <div className="mt-4 space-y-3">
                    {ESQUEMAS.map((e) => {
                      const encontrada = filaDe(tipo.id, e.clave);
                      const r = encontrada?.regla;
                      const activa = r?.activa ?? false;
                      const falta =
                        activa && e.precios.some((c) => !r?.[c] || Number(r[c]) <= 0);

                      return (
                        <div
                          key={e.clave}
                          className={`rounded-zp border-2 p-4 transition ${
                            activa ? 'border-outline' : 'border-outline-variant opacity-70'
                          }`}
                        >
                          <div className="flex flex-wrap items-center gap-4">
                            <label className="flex cursor-pointer items-center gap-3">
                              <input
                                type="checkbox"
                                checked={activa}
                                onChange={() => alternarActiva(tipo.id, e)}
                                className="h-6 w-6 shrink-0"
                              />
                              <span className="text-zp-body font-bold">{e.etiqueta}</span>
                            </label>

                            <span className="text-zp-caption text-on-surface-variant">
                              {e.descripcion}
                            </span>

                            {activa && (
                              <label className="ml-auto flex cursor-pointer items-center gap-2">
                                <input
                                  type="radio"
                                  name={`predeterminada-${tipo.id}`}
                                  checked={esPredeterminada(tipo.id, e.clave)}
                                  onChange={() => marcarPredeterminada(tipo.id, e.clave)}
                                  className="h-5 w-5 shrink-0"
                                />
                                <span className="text-zp-caption font-bold uppercase
                                                 tracking-wide text-on-surface-variant">
                                  predeterminada
                                </span>
                              </label>
                            )}
                          </div>

                          {activa && (
                            <div className="mt-4 flex flex-wrap gap-4">
                              {e.precios.map((campo) => (
                                <label key={campo} className="w-44 space-y-1.5">
                                  <span className="text-zp-caption font-bold uppercase
                                                   tracking-wide text-on-surface-variant">
                                    {ETIQUETA_PRECIO[campo]}
                                  </span>
                                  <input
                                    inputMode="numeric"
                                    value={r?.[campo] ?? ''}
                                    placeholder="0"
                                    onChange={(ev) =>
                                      ponerCampo(
                                        tipo.id, e, campo,
                                        ev.target.value.replace(/[^\d.]/g, ''),
                                      )
                                    }
                                    className={`${CAMPO} text-right ${
                                      falta ? 'border-warning' : ''
                                    }`}
                                  />
                                </label>
                              ))}

                              {e.clave === 'fraccion' && r?.bloque_minutos === 60 && (
                                <p className="order-last w-full text-zp-caption text-on-surface-variant">
                                  Una fracción de 60 minutos cobra igual que «Por hora».
                                </p>
                              )}

                              {e.bloqueEditable && (
                                <label className="w-44 space-y-1.5">
                                  <span className="text-zp-caption font-bold uppercase
                                                   tracking-wide text-on-surface-variant">
                                    Cada … minutos
                                  </span>
                                  <input
                                    inputMode="numeric"
                                    value={String(r?.bloque_minutos ?? 30)}
                                    onChange={(ev) =>
                                      ponerCampo(
                                        tipo.id, e, 'bloque_minutos',
                                        Number(ev.target.value.replace(/\D/g, '')) || 1,
                                      )
                                    }
                                    className={`${CAMPO} text-right`}
                                  />
                                </label>
                              )}

                              {e.diaEditable && (
                                <label className="w-44 space-y-1.5">
                                  <span className="text-zp-caption font-bold uppercase
                                                   tracking-wide text-on-surface-variant">
                                    Horas por día
                                  </span>
                                  <input
                                    inputMode="numeric"
                                    value={String(r?.dia_horas ?? 24)}
                                    onChange={(ev) =>
                                      ponerCampo(
                                        tipo.id, e, 'dia_horas',
                                        Number(ev.target.value.replace(/\D/g, '')) || 24,
                                      )
                                    }
                                    className={`${CAMPO} text-right`}
                                  />
                                </label>
                              )}

                              <label className="w-56 space-y-1.5">
                                <span className="text-zp-caption font-bold uppercase
                                                 tracking-wide text-on-surface-variant">
                                  Cómo se llama al cobrar
                                </span>
                                <input
                                  value={r?.nombre ?? ''}
                                  placeholder={e.etiqueta}
                                  onChange={(ev) =>
                                    ponerCampo(tipo.id, e, 'nombre', ev.target.value)
                                  }
                                  className={CAMPO}
                                />
                              </label>
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>

                  {/* Modificadores comunes a todas las tarifas del vehículo. */}
                  <div className="mt-5 border-t-2 border-outline-variant pt-4">
                    <p className="text-zp-caption font-bold uppercase tracking-wide
                                  text-on-surface-variant">
                      Reglas comunes a todas las tarifas de {tipo.nombre.toLowerCase()}
                    </p>
                    <div className="mt-3 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                      <Campo etiqueta="Cortesía (min)" entero
                             valor={modificadorDe(tipo.id, 'gracia_minutos')}
                             onChange={(v) =>
                               ponerModificador(tipo.id, 'gracia_minutos', Number(v) || 0)} />
                      <Campo etiqueta="Cobro mínimo" opcional
                             valor={modificadorDe(tipo.id, 'cobro_minimo')}
                             onChange={(v) =>
                               ponerModificador(tipo.id, 'cobro_minimo', v || null)} />
                      <Campo etiqueta="Tope por 24 h" opcional
                             valor={modificadorDe(tipo.id, 'tope_diario')}
                             onChange={(v) =>
                               ponerModificador(tipo.id, 'tope_diario', v || null)} />
                      <Campo etiqueta="Redondear a" entero
                             valor={modificadorDe(tipo.id, 'redondeo_paso')}
                             onChange={(v) =>
                               ponerModificador(tipo.id, 'redondeo_paso', Number(v) || 0)} />
                    </div>
                  </div>

                  {(franjas.length > 0 || otras.length > 0) && (
                    <div className="mt-4 rounded-zp border-2 border-outline-variant p-3">
                      <p className="text-zp-caption font-bold uppercase tracking-wide
                                    text-on-surface-variant">
                        Se conservan tal cual
                      </p>
                      <ul className="mt-2 space-y-1">
                        {franjas.map((r) => (
                          <li key={r.codigo} className="text-zp-caption">
                            <strong>{r.nombre ?? r.codigo}</strong> ·{' '}
                            {r.franja?.solo_festivos
                              ? 'solo festivos'
                              : `${r.franja?.desde_hora.slice(0, 5)}–${r.franja?.hasta_hora.slice(0, 5)}`}
                            {' · se aplica sola a su hora, no se ofrece como opción'}
                          </li>
                        ))}
                        {otras.map((r) => (
                          <li key={r.codigo} className="text-zp-caption">
                            <strong>{r.nombre ?? r.codigo}</strong> · escalonada, se edita
                            creando un plan nuevo
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </li>
              );
            })}
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
  etiqueta, valor, onChange, entero = false, opcional = false, resaltado = false,
}: {
  etiqueta: string;
  valor: string;
  onChange: (v: string) => void;
  entero?: boolean;
  opcional?: boolean;
  resaltado?: boolean;
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
        className={resaltado ? `${CAMPO} border-warning` : CAMPO}
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
