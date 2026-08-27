import { useEffect, useState } from 'react';

/**
 * Búsqueda del vehículo que va a salir.
 *
 * El operario teclea los últimos dígitos de la placa, no la placa entera:
 * es lo que alcanza a leer del carro que tiene delante. El campo imita una
 * placa por la misma razón que en el ingreso —está copiando de una— y el
 * backend busca por coincidencia parcial tanto en la placa como en el
 * código del ticket.
 */

interface Ticket {
  id: string;
  codigo: string;
  placa: string | null;
  entrada_at: string;
}

function transcurrido(iso: string): string {
  const minutos = Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 60000));
  if (minutos < 60) return `${minutos} min`;
  return `${Math.floor(minutos / 60)} h ${String(minutos % 60).padStart(2, '0')}`;
}

interface Props {
  tenant: string;
  iniciales: Ticket[];
}

export default function BuscarTicket({ tenant, iniciales }: Props) {
  const [texto, setTexto] = useState('');
  const [tickets, setTickets] = useState<Ticket[]>(iniciales);
  const [buscando, setBuscando] = useState(false);
  const [, redibujar] = useState(0);

  // El tiempo adentro se refresca solo, sin volver a pedir nada al servidor.
  useEffect(() => {
    const t = setInterval(() => redibujar((n) => n + 1), 30_000);
    return () => clearInterval(t);
  }, []);

  useEffect(() => {
    let cancelado = false;
    const temporizador = setTimeout(async () => {
      setBuscando(true);
      try {
        const url = `/api/v1/t/${tenant}/tickets?estado=abierto${
          texto.trim() ? `&placa=${encodeURIComponent(texto.trim())}` : ''
        }`;
        const res = await fetch(url);
        if (!cancelado && res.ok) setTickets(await res.json());
      } finally {
        if (!cancelado) setBuscando(false);
      }
    }, 200);

    return () => {
      cancelado = true;
      clearTimeout(temporizador);
    };
  }, [tenant, texto]);

  return (
    <div className="space-y-5">
      <label className="block space-y-2">
        <span className="text-zp-caption font-bold uppercase tracking-wide text-on-surface-variant">
          Placa o últimos dígitos
        </span>
        <input
          value={texto}
          onChange={(e) => setTexto(e.target.value.toUpperCase())}
          autoFocus
          autoCapitalize="characters"
          autoCorrect="off"
          spellCheck={false}
          placeholder="123"
          className="placa-campo"
        />
      </label>

      <p className="text-center text-zp-body font-bold text-on-surface-variant">
        {buscando
          ? 'Buscando…'
          : `${tickets.length} ${tickets.length === 1 ? 'vehículo adentro' : 'vehículos adentro'}`}
      </p>

      <ul className="space-y-3">
        {tickets.map((t) => (
          <li key={t.id}>
            <a
              href={`/t/${tenant}/tickets/${t.id}`}
              className="flex items-center justify-between gap-4 rounded-zp border-2
                         border-outline bg-surface-container-lowest p-4 transition
                         active:bg-surface-container"
            >
              <div className="flex min-w-0 flex-col items-start gap-1.5">
                {t.placa ? (
                  <span className="placa text-zp-xl">{t.placa}</span>
                ) : (
                  <span className="text-zp-lg font-extrabold">{t.codigo}</span>
                )}
                {t.placa && (
                  <span className="text-zp-caption text-on-surface-variant">{t.codigo}</span>
                )}
              </div>
              <div className="shrink-0 text-right">
                <p className="text-zp-lg font-extrabold tabular-nums">
                  {transcurrido(t.entrada_at)}
                </p>
                <p className="text-zp-caption text-on-surface-variant">adentro</p>
              </div>
            </a>
          </li>
        ))}

        {tickets.length === 0 && !buscando && (
          <li className="rounded-zp border-2 border-dashed border-outline-variant p-8
                         text-center text-zp-body text-on-surface-variant">
            {texto ? 'Ninguna placa coincide' : 'No hay vehículos adentro'}
          </li>
        )}
      </ul>
    </div>
  );
}
