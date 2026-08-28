import { useEffect, useState } from 'react';

/**
 * Ingreso del operario.
 *
 * Dos modos. Con contraseña la primera vez en un dispositivo; con PIN de
 * seis dígitos las siguientes, sobre teclado numérico grande. En la
 * caseta se entra con una mano y a veces con guantes, así que el modo PIN
 * es el que se ofrece por defecto cuando el dispositivo ya se conoce.
 *
 * Estilo: sistema de alto contraste de ZonePark. Bordes negros de 2px en
 * vez de sombras, porque una sombra suave desaparece con el reflejo del
 * sol y un borde no.
 */

const LLAVE_DISPOSITIVO = 'zp_device';
const LLAVE_ULTIMO_CORREO = 'zp_last_email';

function obtenerHuella(): string {
  try {
    let huella = localStorage.getItem(LLAVE_DISPOSITIVO);
    if (!huella) {
      huella = idUnico();
      localStorage.setItem(LLAVE_DISPOSITIVO, huella);
    }
    return huella;
  } catch {
    // Navegación privada o almacenamiento bloqueado: se entra con contraseña.
    return '';
  }
}

const CAMPO =
  'w-full rounded-zp border-2 border-outline bg-surface-container-lowest px-4 py-3 ' +
  'text-zp-lg text-on-surface placeholder:text-outline-variant';

const BOTON_PRIMARIO =
  'w-full rounded-zp border-2 border-outline bg-primary px-4 py-4 text-zp-lg ' +
  'font-extrabold uppercase tracking-wide text-on-primary transition ' +
  'active:bg-primary-container disabled:border-outline-variant ' +
  'disabled:bg-surface-container-high disabled:text-on-surface-variant';

const BOTON_SECUNDARIO =
  'w-full rounded-zp border-2 border-outline bg-surface-container-lowest px-4 py-4 ' +
  'text-zp-body font-bold text-on-surface transition active:bg-surface-container';

function IconoError() {
  return (
    <svg
      viewBox="0 0 24 24"
      aria-hidden="true"
      className="h-6 w-6 shrink-0"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.5"
      strokeLinecap="round"
    >
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v6" />
      <path d="M12 16.5v.01" />
    </svg>
  );
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
    <form onSubmit={enviar} className="space-y-4">
      <label className="block space-y-2">
        <span className="text-zp-caption font-bold uppercase tracking-wide text-on-surface-variant">
          Correo
        </span>
        <input
          type="email"
          inputMode="email"
          autoComplete="username"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className={CAMPO}
        />
      </label>

      {modo === 'password' ? (
        <label className="block space-y-2">
          <span className="text-zp-caption font-bold uppercase tracking-wide text-on-surface-variant">
            Contraseña
          </span>
          <input
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className={CAMPO}
          />
        </label>
      ) : (
        <div className="space-y-4">
          <p className="text-zp-caption font-bold uppercase tracking-wide text-on-surface-variant">
            PIN
          </p>

          <div
            className="flex justify-center gap-3"
            role="status"
            aria-label={`${pin.length} de 6 dígitos`}
          >
            {Array.from({ length: 6 }, (_, i) => (
              <span
                key={i}
                className={`h-5 w-5 rounded-full border-2 border-outline transition ${
                  i < pin.length ? 'bg-secondary' : 'bg-surface-container-lowest'
                }`}
              />
            ))}
          </div>

          <div className="grid grid-cols-3 gap-3">
            {teclas.map((tecla, i) =>
              tecla === '' ? (
                <span key={i} />
              ) : (
                <button
                  key={i}
                  type="button"
                  disabled={enviando}
                  aria-label={tecla === '⌫' ? 'Borrar' : tecla}
                  onClick={() =>
                    setPin((actual) =>
                      tecla === '⌫' ? actual.slice(0, -1) : (actual + tecla).slice(0, 6),
                    )
                  }
                  className="rounded-zp border-2 border-outline bg-surface-container-lowest
                             py-4 text-zp-xl font-extrabold text-on-surface transition
                             active:bg-primary disabled:opacity-40"
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
          className="flex items-start gap-3 rounded-zp border-2 border-error bg-surface-container-lowest
                     px-4 py-3 text-zp-body font-semibold text-error"
        >
          <IconoError />
          <span>{error}</span>
        </p>
      )}

      {modo === 'password' && (
        <button type="submit" disabled={enviando} className={BOTON_PRIMARIO}>
          {enviando ? 'Entrando…' : 'Entrar'}
        </button>
      )}

      {modo === 'pin' && enviando && (
        <p className="text-center text-zp-body font-bold text-on-surface-variant">Entrando…</p>
      )}

      <button
        type="button"
        onClick={() => {
          setModo(modo === 'pin' ? 'password' : 'pin');
          setError('');
          setPin('');
          setPassword('');
        }}
        className={BOTON_SECUNDARIO}
      >
        {modo === 'pin' ? 'Entrar con contraseña' : 'Entrar con PIN'}
      </button>
    </form>
  );
}
