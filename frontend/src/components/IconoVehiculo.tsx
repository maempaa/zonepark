/**
 * Icono del tipo de vehículo.
 *
 * Trazo monocromo en `currentColor`, no emoji: los emoji se pintan
 * distinto en cada sistema y su color rompe un esquema de solo amarillo y
 * negro. El icono acompaña al nombre, no lo sustituye, así que un tipo
 * que el cliente invente cae en el genérico sin quedar mudo.
 */

interface Dibujo {
  trazos: string[];
  ruedas: Array<[number, number, number]>;
}

const VEHICULOS: Record<string, Dibujo> = {
  carro: {
    trazos: ['M5 17H3v-4l2-5h14l2 5v4h-2', 'M5 13h14'],
    ruedas: [[7.5, 17, 2], [16.5, 17, 2]],
  },
  camioneta: {
    trazos: ['M4 17H2.5v-5l2.5-5h14l2.5 5v5H20', 'M5 12h14'],
    ruedas: [[7.5, 17, 2], [16.5, 17, 2]],
  },
  moto: {
    trazos: ['M5.5 16h4l3-6h-2', 'M12.5 10h3l3 6', 'M14 7h3'],
    ruedas: [[5.5, 16, 3.5], [18.5, 16, 3.5]],
  },
  bicicleta: {
    trazos: ['M5.5 17l4-8h5l4 8', 'M9.5 9h5', 'M12 17l2.5-8'],
    ruedas: [[5.5, 17, 3.5], [18.5, 17, 3.5]],
  },
  patineta: {
    trazos: ['M4 15h16', 'M8 11h8l-1 4H9z'],
    ruedas: [[8, 18, 1.6], [16, 18, 1.6]],
  },
};

export default function IconoVehiculo({
  codigo,
  className,
}: {
  codigo: string;
  className?: string;
}) {
  const dibujo = VEHICULOS[codigo];

  return (
    <svg
      viewBox="0 0 24 24"
      className={className}
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {dibujo ? (
        <>
          {dibujo.trazos.map((d, i) => (
            <path key={i} d={d} />
          ))}
          {dibujo.ruedas.map(([cx, cy, r], i) => (
            <circle key={i} cx={cx} cy={cy} r={r} />
          ))}
        </>
      ) : (
        // Genérico: la P de parqueadero en un recuadro.
        <>
          <rect x="3.5" y="3.5" width="17" height="17" rx="2.5" />
          <path d="M9.5 16.5V8h3a2.75 2.75 0 0 1 0 5.5H9.5" />
        </>
      )}
    </svg>
  );
}
