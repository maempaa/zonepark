import { useState } from 'react';

/** Acceso al panel de plataforma. Escritorio, no caseta. */
export default function IngresoPlataforma() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [enviando, setEnviando] = useState(false);

  async function enviar(e: React.FormEvent) {
    e.preventDefault();
    setError('');
    setEnviando(true);
    try {
      const res = await fetch('/api/admin-session', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ email, password }),
      });
      const datos = await res.json();
      if (!res.ok) {
        setError(datos.detail ?? 'No se pudo iniciar sesión');
        return;
      }
      window.location.href = '/admin';
    } catch {
      setError('Sin conexión con el servidor');
    } finally {
      setEnviando(false);
    }
  }

  const campo =
    'w-full rounded-zp border-2 border-outline bg-surface-container-lowest px-4 py-3 ' +
    'text-zp-body text-on-surface';

  return (
    <form onSubmit={enviar} className="space-y-4">
      <label className="block space-y-1.5">
        <span className="text-zp-caption font-bold uppercase tracking-wide text-on-surface-variant">
          Correo
        </span>
        <input
          type="email" autoComplete="username" required autoFocus
          value={email} onChange={(e) => setEmail(e.target.value)} className={campo}
        />
      </label>

      <label className="block space-y-1.5">
        <span className="text-zp-caption font-bold uppercase tracking-wide text-on-surface-variant">
          Contraseña
        </span>
        <input
          type="password" autoComplete="current-password" required
          value={password} onChange={(e) => setPassword(e.target.value)} className={campo}
        />
      </label>

      {error && (
        <p role="alert"
           className="flex items-start gap-3 rounded-zp border-2 border-error
                      bg-surface-container-lowest px-4 py-3 text-zp-body font-semibold text-error">
          <svg viewBox="0 0 24 24" className="h-6 w-6 shrink-0" fill="none"
               stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" aria-hidden="true">
            <circle cx="12" cy="12" r="9" /><path d="M12 7v6" /><path d="M12 16.5v.01" />
          </svg>
          <span>{error}</span>
        </p>
      )}

      <button
        type="submit" disabled={enviando}
        className="w-full rounded-zp border-2 border-outline bg-primary px-4 py-3 text-zp-body
                   font-extrabold uppercase tracking-wide text-on-primary
                   active:bg-primary-container disabled:border-outline-variant
                   disabled:bg-surface-container-high disabled:text-on-surface-variant"
      >
        {enviando ? 'Entrando…' : 'Entrar'}
      </button>
    </form>
  );
}
