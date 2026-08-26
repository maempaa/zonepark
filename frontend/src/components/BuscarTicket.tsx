import { useEffect, useState } from 'react';

/**
 * Búsqueda de un ticket abierto.
 *
 * El operario teclea los últimos dígitos de la placa, no la placa entera:
 * es lo que alcanza a leer del carro que tiene delante. El backend busca
 * por coincidencia parcial tanto en la placa como en el código.
 */

interface Ticket {
  id: string;
  codigo: string;
  placa: string | null;
  entrada_at: string;
}

interface Props {
  tenant: string;
  iniciales: Ticket[];
}

function transcurrido(iso: string): string {
  const minutos = Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 60000));
  if (minutos < 60) return `${minutos} min`;
  return `${Math.floor(minutos / 60)} h ${String(minutos % 60).padStart(2, '0')} min`;
}

export default function BuscarTicket({ tenant, iniciales }: Props) {
  const [texto, setTexto] = useState('');
  const [tickets, setTickets] = useState<Ticket[]>(iniciales);
  const [buscando, setBuscando] = useState(false);
  const [, forzarRedibujo] = useState(0);

  // El tiempo transcurrido se refresca solo, sin volver a pedir nada.
  useEffect(() => {
    const t = setInterval(() => forzarRedibujo((n) => n + 1), 30_000);
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
    <div className="space-y-4">
      <input
        value={texto}
        onChange={(e) => setTexto(e.target.value.toUpperCase())}
        autoFocus
        autoCapitalize="characters"
        autoCorrect="off"
        spellCheck={false}
        placeholder="Últimos dígitos de la placa"
        className="w-full rounded-xl border border-slate-300 bg-white px-4 py-4 text-center
                   text-2xl font-bold tracking-widest text-slate-900 outline-none
                   focus:border-brand-500 focus:ring-2 focus:ring-brand-500/30
                   dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
      />

      <p className="text-center text-sm text-slate-500 dark:text-slate-400">
        {buscando
          ? 'Buscando…'
          : `${tickets.length} ${tickets.length === 1 ? 'vehículo adentro' : 'vehículos adentro'}`}
      </p>

      <ul className="space-y-2">
        {tickets.map((t) => (
          <li key={t.id}>
            <a
              href={`/t/${tenant}/tickets/${t.id}`}
              className="flex items-center justify-between gap-3 rounded-2xl bg-white p-4
                         shadow-sm active:bg-slate-50 dark:bg-slate-900 dark:active:bg-slate-800"
            >
              <div className="min-w-0">
                <p className="text-xl font-bold tracking-wide tabular-nums">
                  {t.placa ?? 'Sin placa'}
                </p>
                <p className="text-sm text-slate-500 dark:text-slate-400">{t.codigo}</p>
              </div>
              <div className="shrink-0 text-right">
                <p className="text-sm font-medium tabular-nums">{transcurrido(t.entrada_at)}</p>
                <p className="text-xs text-slate-400">adentro</p>
              </div>
            </a>
          </li>
        ))}
        {tickets.length === 0 && !buscando && (
          <li className="rounded-2xl bg-white p-6 text-center text-sm text-slate-500
                         shadow-sm dark:bg-slate-900 dark:text-slate-400">
            {texto ? 'Ninguna placa coincide' : 'No hay vehículos adentro'}
          </li>
        )}
      </ul>
    </div>
  );
}
