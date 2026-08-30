import type { ReactNode } from 'react';

/**
 * Icono del tipo de vehículo.
 *
 * Cada icono trae su propio `viewBox` y su propia técnica: carro y moto
 * son de relleno, la bicicleta de trazo. Se conservan tal cual llegaron
 * en vez de redibujarlos a un molde común, que es lo que les quitaría el
 * acabado.
 *
 * El color va en `currentColor`, no fijo: el mismo icono se pinta sobre
 * el botón amarillo cuando está seleccionado y sobre el blanco cuando no.
 *
 * Un tipo que el cliente invente —"camión", "grúa"— cae en el genérico y
 * queda acompañado de su nombre, así que no se queda mudo.
 */

interface Dibujo {
  viewBox: string;
  /** De relleno; si es falso, de trazo. */
  relleno: boolean;
  contenido: ReactNode;
}

const CARRO: Dibujo = {
  viewBox: '0 0 24 24',
  relleno: true,
  contenido: (
    <path d="m5 11l1.5-4.5h11L19 11m-1.5 5a1.5 1.5 0 0 1-1.5-1.5a1.5 1.5 0 0 1 1.5-1.5a1.5 1.5 0 0 1 1.5 1.5a1.5 1.5 0 0 1-1.5 1.5m-11 0A1.5 1.5 0 0 1 5 14.5A1.5 1.5 0 0 1 6.5 13A1.5 1.5 0 0 1 8 14.5A1.5 1.5 0 0 1 6.5 16M18.92 6c-.2-.58-.76-1-1.42-1h-11c-.66 0-1.22.42-1.42 1L3 12v8a1 1 0 0 0 1 1h1a1 1 0 0 0 1-1v-1h12v1a1 1 0 0 0 1 1h1a1 1 0 0 0 1-1v-8z" />
  ),
};

const VEHICULOS: Record<string, Dibujo> = {
  carro: CARRO,
  // Una camioneta se lee igual con el icono del carro; dibujarla aparte
  // solo añadiría una silueta casi idéntica.
  camioneta: CARRO,

  moto: {
    viewBox: '0 0 20 20',
    relleno: true,
    contenido: (
      <>
        <path d="M12.75 12.5a1 1 0 1 1-2 0a1 1 0 0 1 2 0m-3.5 0a1 1 0 1 1-2 0a1 1 0 0 1 2 0" />
        <path
          fillRule="evenodd"
          clipRule="evenodd"
          d="M10 8a3.5 3.5 0 1 0 0-7a3.5 3.5 0 0 0 0 7m0-5a1.5 1.5 0 1 1 0 3a1.5 1.5 0 0 1 0-3"
        />
        <path d="M10 14a2 2 0 0 1 2 2v1.5a2 2 0 1 1-4 0V16a2 2 0 0 1 2-2" />
        <path
          fillRule="evenodd"
          clipRule="evenodd"
          d="M15 11a5 5 0 0 0-10 0v2.5A2.5 2.5 0 0 0 7.5 16h5a2.5 2.5 0 0 0 2.5-2.5zm-8 0a3 3 0 0 1 6 0v2.5a.5.5 0 0 1-.5.5h-5a.5.5 0 0 1-.5-.5z"
        />
        <path d="M15.5 4.5a1 1 0 1 1 0-2h2a1 1 0 1 1 0 2zm-13 0a1 1 0 0 1 0-2h2a1 1 0 0 1 0 2z" />
        <path d="m3.41 4.046l.476-1.455l4.524.863l-.477 1.456zm8.18-.592l.477 1.456l4.523-.864l-.476-1.455z" />
      </>
    ),
  },

  bicicleta: {
    viewBox: '0 0 24 24',
    relleno: false,
    contenido: (
      <>
        <circle cx="6" cy="15" r="4" />
        <circle cx="18" cy="15" r="4" />
        <path d="m6 15l2-7h7.5M6 5h3m9 10L15 5h4m0 0h.5A1.5 1.5 0 0 1 21 6.5v0A1.5 1.5 0 0 1 19.5 8H19" />
      </>
    ),
  },
};

// La P de parqueadero en un recuadro, para cualquier tipo que el cliente
// invente.
const GENERICO: Dibujo = {
  viewBox: '0 0 24 24',
  relleno: false,
  contenido: (
    <>
      <rect x="3.5" y="3.5" width="17" height="17" rx="2.5" />
      <path d="M9.5 16.5V8h3a2.75 2.75 0 0 1 0 5.5H9.5" />
    </>
  ),
};

export default function IconoVehiculo({
  codigo,
  className,
}: {
  codigo: string;
  className?: string;
}) {
  const dibujo = VEHICULOS[codigo] ?? GENERICO;

  const pintura = dibujo.relleno
    ? { fill: 'currentColor' }
    : {
        fill: 'none',
        stroke: 'currentColor',
        strokeWidth: 2,
        strokeLinecap: 'round' as const,
        strokeLinejoin: 'round' as const,
      };

  return (
    <svg viewBox={dibujo.viewBox} className={className} aria-hidden="true" {...pintura}>
      {dibujo.contenido}
    </svg>
  );
}
