import { useState } from 'react';

export default function CerrarSesionAdmin() {
  const [saliendo, setSaliendo] = useState(false);

  async function salir() {
    setSaliendo(true);
    await fetch('/api/admin-session', { method: 'DELETE' }).catch(() => undefined);
    window.location.href = '/admin/login';
  }

  return (
    <button
      onClick={salir}
      disabled={saliendo}
      className="shrink-0 rounded-zp border-2 border-outline bg-surface-container-lowest px-4
                 text-zp-caption font-bold uppercase tracking-wide text-on-surface
                 active:bg-surface-container disabled:opacity-50"
    >
      {saliendo ? 'Saliendo…' : 'Salir'}
    </button>
  );
}
