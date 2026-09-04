/**
 * Abrir el redactor de correo con el recibo ya escrito.
 *
 * Quien manda el recibo es el operario desde su propio correo, así que lo
 * que se elige aquí no es el correo del cliente sino **con qué** se
 * escribe: la web de Gmail, la de Outlook, la de Yahoo, o la aplicación
 * que el dispositivo tenga puesta por defecto.
 *
 * `mailto:` es el que siempre funciona y por eso queda de último recurso
 * visible; los demás son atajos para quien trabaja con el correo en el
 * navegador, que en una caseta con un computador es lo habitual.
 */

export interface Motor {
  id: string;
  nombre: string;
  /** Arma la URL del redactor ya con destinatario, asunto y cuerpo. */
  redactar(para: string, asunto: string, cuerpo: string): string;
}

const q = encodeURIComponent;

export const MOTORES: Motor[] = [
  {
    id: 'gmail',
    nombre: 'Gmail',
    redactar: (para, asunto, cuerpo) =>
      `https://mail.google.com/mail/?view=cm&fs=1&to=${q(para)}` +
      `&su=${q(asunto)}&body=${q(cuerpo)}`,
  },
  {
    id: 'outlook',
    nombre: 'Outlook',
    redactar: (para, asunto, cuerpo) =>
      `https://outlook.live.com/mail/0/deeplink/compose?to=${q(para)}` +
      `&subject=${q(asunto)}&body=${q(cuerpo)}`,
  },
  {
    id: 'yahoo',
    nombre: 'Yahoo',
    redactar: (para, asunto, cuerpo) =>
      `https://compose.mail.yahoo.com/?to=${q(para)}` +
      `&subject=${q(asunto)}&body=${q(cuerpo)}`,
  },
  {
    id: 'app',
    nombre: 'App de correo',
    redactar: (para, asunto, cuerpo) =>
      `mailto:${q(para)}?subject=${q(asunto)}&body=${q(cuerpo)}`,
  },
];

/** Laxa a propósito: la misma comprobación que hace el servidor. */
const FORMA = /^[^@\s]+@[^@\s]+\.[^@\s]{2,}$/;

export function pareceCorreo(valor: string): boolean {
  return FORMA.test((valor ?? '').trim().toLowerCase());
}

export function enlaceCorreo(
  motor: Motor, para: string, asunto: string, cuerpo: string,
): string | null {
  const limpio = (para ?? '').trim().toLowerCase();
  if (!FORMA.test(limpio)) return null;
  return motor.redactar(limpio, asunto, cuerpo);
}

/** El motor que usó la última vez quien está en la caseta. */
const CLAVE = 'zonepark:motor-correo';

export function motorRecordado(): Motor {
  try {
    const id = localStorage.getItem(CLAVE);
    return MOTORES.find((m) => m.id === id) ?? MOTORES[0];
  } catch {
    // Navegador con el almacenamiento bloqueado: no es motivo para
    // quedarse sin el botón.
    return MOTORES[0];
  }
}

export function recordarMotor(motor: Motor): void {
  try {
    localStorage.setItem(CLAVE, motor.id);
  } catch {
    /* da igual: solo se pierde la comodidad */
  }
}
