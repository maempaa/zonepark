import { useState } from 'react';

type Estado = 'inicial' | 'cargando' | 'ok' | 'error';

/**
 * Verifica desde el navegador la cadena completa
 * navegador → proxy de Astro → FastAPI.
 */
export default function PruebaConexion() {
  const [estado, setEstado] = useState<Estado>('inicial');
  const [detalle, setDetalle] = useState('');

  async function probar() {
    setEstado('cargando');
    try {
      const res = await fetch('/api/v1/meta');
      const body = await res.json();
      if (!res.ok) throw new Error(body.detail ?? `HTTP ${res.status}`);
      setEstado('ok');
      setDetalle(`${body.app} v${body.version} · ${body.default_currency} · ${body.default_timezone}`);
    } catch (e) {
      setEstado('error');
      setDetalle(e instanceof Error ? e.message : String(e));
    }
  }

  const borde =
    estado === 'ok' ? 'border-success text-success'
    : estado === 'error' ? 'border-error text-error'
    : 'border-outline';

  return (
    <div className="space-y-3">
      <button
        onClick={probar}
        disabled={estado === 'cargando'}
        className="w-full rounded-zp border-2 border-outline bg-primary px-4 py-4 text-zp-body
                   font-extrabold uppercase tracking-wide text-on-primary
                   active:bg-primary-container disabled:border-outline-variant
                   disabled:bg-surface-container-high disabled:text-on-surface-variant"
      >
        {estado === 'cargando' ? 'Probando…' : 'Probar conexión con la API'}
      </button>
      {detalle && (
        <p className={`rounded-zp border-2 bg-surface-container-lowest px-4 py-3 text-zp-body
                       font-semibold ${borde}`}>
          {detalle}
        </p>
      )}
    </div>
  );
}
