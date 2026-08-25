import { useState } from 'react';

type Estado = 'inicial' | 'cargando' | 'ok' | 'error';

/**
 * Isla de prueba de la fase 0: verifica desde el navegador la cadena
 * completa navegador → proxy de Astro → FastAPI.
 * Se reemplaza en la fase 3 por el formulario de ingreso.
 */
export default function PruebaConexion() {
  const [estado, setEstado] = useState<Estado>('inicial');
  const [detalle, setDetalle] = useState<string>('');

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

  const colores: Record<Estado, string> = {
    inicial: 'bg-brand-600 active:bg-brand-700',
    cargando: 'bg-slate-400',
    ok: 'bg-emerald-600 active:bg-emerald-700',
    error: 'bg-red-600 active:bg-red-700',
  };

  return (
    <div className="space-y-3">
      <button
        onClick={probar}
        disabled={estado === 'cargando'}
        className={`w-full rounded-xl px-4 py-4 text-lg font-semibold text-white transition ${colores[estado]}`}
      >
        {estado === 'cargando' ? 'Probando…' : 'Probar conexión con la API'}
      </button>
      {detalle && (
        <p
          className={`rounded-lg px-3 py-2 text-sm ${
            estado === 'ok'
              ? 'bg-emerald-50 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200'
              : 'bg-red-50 text-red-800 dark:bg-red-950 dark:text-red-200'
          }`}
        >
          {detalle}
        </p>
      )}
    </div>
  );
}
