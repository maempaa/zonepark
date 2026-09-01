/**
 * El enlace al recibo en vivo, para pasárselo al cliente.
 *
 * Se comparte, no se dicta: el token son 32 caracteres al azar y nadie va
 * a teclearlos. `navigator.share` abre WhatsApp y lo demás en el celular;
 * fuera de contexto seguro no existe, y el portapapeles tampoco, así que
 * siempre queda el enlace visible y seleccionable como último recurso.
 */
import { useEffect, useState } from 'react';

function Icono({ d }: { d: string }) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" className="h-5 w-5 shrink-0" fill="none"
         stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"
         strokeLinejoin="round">
      <path d={d} />
    </svg>
  );
}

const COMPARTIR = 'M4 12v7a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-7M16 6l-4-4-4 4M12 2v14';
const COPIAR = 'M9 9h9a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H9a1 1 0 0 1-1-1v-9a1 1 0 0 1 1-1ZM5 15H4a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1h9a1 1 0 0 1 1 1v1';

interface Props {
  tenant: string;
  token: string;
  codigo: string;
}

export default function EnlaceRecibo({ tenant, token, codigo }: Props) {
  const [aviso, setAviso] = useState<string | null>(null);
  const ruta = `/t/${tenant}/r/${token}`;

  // El origen solo existe en el navegador. Se resuelve después de montar
  // para que el HTML del servidor y el del cliente coincidan.
  const [url, setUrl] = useState(ruta);
  const [puedeCompartir, setPuedeCompartir] = useState(false);
  useEffect(() => {
    setUrl(`${window.location.origin}${ruta}`);
    setPuedeCompartir(typeof navigator !== 'undefined' && 'share' in navigator);
  }, [ruta]);

  async function compartir() {
    const texto = `Tu recibo del parqueadero (ticket ${codigo}): ${url}`;
    if (puedeCompartir) {
      try {
        await navigator.share({ text: texto, url });
        return;
      } catch {
        // Cancelar el diálogo no es un fallo; se cae al portapapeles.
      }
    }
    try {
      await navigator.clipboard.writeText(url);
      setAviso('Enlace copiado');
    } catch {
      setAviso('Copia el enlace de abajo a mano');
    }
    setTimeout(() => setAviso(null), 4000);
  }

  return (
    <div className="rounded-zp border-2 border-outline bg-surface-container-lowest p-4">
      <p className="text-zp-caption font-bold uppercase tracking-wide text-on-surface-variant">
        Recibo del cliente
      </p>
      <p className="mt-1 text-zp-body text-on-surface-variant">
        Pásaselo y podrá ver en su celular cuánto lleva corriendo.
      </p>

      <div className="mt-3 flex flex-wrap gap-3">
        <button
          onClick={compartir}
          className="flex items-center gap-2 rounded-zp border-2 border-outline
                     bg-surface-container-lowest px-4 py-3 text-zp-body font-bold
                     active:bg-surface-container"
        >
          <Icono d={puedeCompartir ? COMPARTIR : COPIAR} />
          {puedeCompartir ? 'Compartir' : 'Copiar enlace'}
        </button>
        <a
          href={ruta}
          target="_blank"
          rel="noopener"
          className="flex items-center rounded-zp border-2 border-outline
                     bg-surface-container-lowest px-4 py-3 text-zp-body font-bold
                     active:bg-surface-container"
        >
          Abrirlo
        </a>
      </div>

      {aviso && <p className="mt-2 text-zp-caption font-bold">{aviso}</p>}

      {/* Visible siempre: si compartir y copiar fallan, esto se puede
          seleccionar con el dedo. `break-all` porque el token no tiene
          espacios donde cortar. */}
      <p className="mt-3 break-all rounded-zp border-2 border-outline-variant
                    bg-surface-container px-3 py-2 text-zp-caption
                    text-on-surface-variant">
        {url}
      </p>
    </div>
  );
}
