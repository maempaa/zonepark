import { useEffect, useState } from 'react';

/**
 * Ingreso del operario.
 *
 * Dos modos. Con contraseña la primera vez en un dispositivo; con PIN de
 * seis dígitos las siguientes, sobre teclado numérico grande. En la
 * caseta se entra con una mano y a veces con guantes, así que el modo PIN
 * es el que se ofrece por defecto cuando el dispositivo ya se conoce.
 */

const LLAVE_DISPOSITIVO = 'zp_device';
const LLAVE_ULTIMO_CORREO = 'zp_last_email';

function obtenerHuella(): string {
  try {
    let huella = localStorage.getItem(LLAVE_DISPOSITIVO);
    if (!huella) {
      huella = crypto.randomUUID();
      localStorage.setItem(LLAVE_DISPOSITIVO, huella);
    }
    return huella;
  } catch {
    // Navegación privada o almacenamiento bloqueado: se entra con contraseña.
    return '';
  }
}

interface Props {
  tenant: string;
}

export default function FormularioIngreso({ tenant }: Props) {
  const [modo, setModo] = useState<'password' | 'pin'>('password');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [pin, setPin] = useState('');
  const [huella, setHuella] = useState('');
  const [error, setError] = useState('');
  const [enviando, setEnviando] = useState(false);

  useEffect(() => {
    setHuella(obtenerHuella());
    try {
      const ultimo = localStorage.getItem(LLAVE_ULTIMO_CORREO);
      if (ultimo) {
        setEmail(ultimo);
        setModo('pin');
      }
    } catch {
      /* sin almacenamiento */
    }
  }, []);

  async function enviar(e?: React.FormEvent) {
    e?.preventDefault();
    setError('');
    setEnviando(true);
    try {
      const cuerpo =
        modo === 'pin'
          ? { tenant, email, pin, device_fingerprint: huella }
          : {
              tenant,
              email,
              password,
              device_fingerprint: huella || undefined,
              device_nombre: navigator.platform || 'Dispositivo',
            };

      const res = await fetch('/api/session', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(cuerpo),
      });
      const datos = await res.json();

      if (!res.ok) {
        setError(datos.detail ?? 'No se pudo iniciar sesión');
        setPin('');
        return;
      }

      try {
        localStorage.setItem(LLAVE_ULTIMO_CORREO, email);
      } catch {
        /* sin almacenamiento */
      }
      window.location.href = `/t/${tenant}`;
    } catch {
      setError('No hay conexión con el servidor');
    } finally {
      setEnviando(false);
    }
  }

  // Envía solo cuando el PIN está completo.
  useEffect(() => {
    if (modo === 'pin' && pin.length === 6 && !enviando) void enviar();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pin]);

  const teclas = ['1', '2', '3', '4', '5', '6', '7', '8', '9', '', '0', '⌫'];

  return (
    <form onSubmit={enviar} className="space-y-5">
      <label className="block space-y-1.5">
        <span className="text-sm font-medium text-slate-600 dark:text-slate-300">
          Correo
        </span>
        <input
          type="email"
          inputMode="email"
          autoComplete="username"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className="w-full rounded-xl border border-slate-300 bg-white px-4 py-3 text-base
                     text-slate-900 outline-none focus:border-brand-500 focus:ring-2
                     focus:ring-brand-500/30 dark:border-slate-700 dark:bg-slate-900
                     dark:text-slate-100"
        />
      </label>

      {modo === 'password' ? (
        <label className="block space-y-1.5">
          <span className="text-sm font-medium text-slate-600 dark:text-slate-300">
            Contraseña
          </span>
          <input
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="w-full rounded-xl border border-slate-300 bg-white px-4 py-3 text-base
                       text-slate-900 outline-none focus:border-brand-500 focus:ring-2
                       focus:ring-brand-500/30 dark:border-slate-700 dark:bg-slate-900
                       dark:text-slate-100"
          />
        </label>
      ) : (
        <div className="space-y-4">
          <div className="flex justify-center gap-2.5" aria-label="PIN de seis dígitos">
            {Array.from({ length: 6 }, (_, i) => (
              <span
                key={i}
                className={`h-4 w-4 rounded-full transition ${
                  i < pin.length
                    ? 'bg-brand-600'
                    : 'bg-slate-300 dark:bg-slate-700'
                }`}
              />
            ))}
          </div>

          <div className="grid grid-cols-3 gap-2.5">
            {teclas.map((tecla, i) =>
              tecla === '' ? (
                <span key={i} />
              ) : (
                <button
                  key={i}
                  type="button"
                  disabled={enviando}
                  onClick={() =>
                    setPin((actual) =>
                      tecla === '⌫' ? actual.slice(0, -1) : (actual + tecla).slice(0, 6),
                    )
                  }
                  className="rounded-xl bg-white py-4 text-2xl font-semibold text-slate-900
                             shadow-sm active:bg-slate-100 disabled:opacity-50
                             dark:bg-slate-900 dark:text-slate-100 dark:active:bg-slate-800"
                >
                  {tecla}
                </button>
              ),
            )}
          </div>
        </div>
      )}

      {error && (
        <p
          role="alert"
          className="rounded-lg bg-red-50 px-3 py-2.5 text-sm text-red-800
                     dark:bg-red-950 dark:text-red-200"
        >
          {error}
        </p>
      )}

      {modo === 'password' && (
        <button
          type="submit"
          disabled={enviando}
          className="w-full rounded-xl bg-brand-600 px-4 py-4 text-lg font-semibold text-white
                     transition active:bg-brand-700 disabled:bg-slate-400"
        >
          {enviando ? 'Entrando…' : 'Entrar'}
        </button>
      )}

      <button
        type="button"
        onClick={() => {
          setModo(modo === 'pin' ? 'password' : 'pin');
          setError('');
          setPin('');
          setPassword('');
        }}
        className="w-full text-sm font-medium text-brand-600 underline-offset-4 hover:underline
                   dark:text-brand-500"
      >
        {modo === 'pin' ? 'Entrar con contraseña' : 'Entrar con PIN'}
      </button>
    </form>
  );
}
