import { useState } from 'react';

export default function CerrarSesion({ tenant }: { tenant: string }) {
  const [saliendo, setSaliendo] = useState(false);

  async function salir() {
    setSaliendo(true);
    await fetch('/api/session', { method: 'DELETE' }).catch(() => undefined);
    window.location.href = `/t/${tenant}/login`;
  }

  return (
    <button
      onClick={salir}
      disabled={saliendo}
      className="shrink-0 rounded-zp border-2 border-outline bg-surface-container-lowest px-4
                 text-zp-caption font-bold uppercase tracking-wide text-on-surface
                 transition active:bg-surface-container disabled:opacity-50"
    >
      {saliendo ? 'Saliendo…' : 'Salir'}
    </button>
  );
}
