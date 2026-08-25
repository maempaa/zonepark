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
      className="shrink-0 rounded-lg px-3 py-2 text-sm font-medium text-slate-600
                 active:bg-slate-200 disabled:opacity-50 dark:text-slate-300
                 dark:active:bg-slate-800"
    >
      {saliendo ? 'Saliendo…' : 'Salir'}
    </button>
  );
}
