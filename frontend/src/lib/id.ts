/**
 * Identificadores únicos que también funcionan fuera de contexto seguro.
 *
 * `crypto.randomUUID` solo existe en HTTPS o en localhost. En la caseta se
 * entra por IP —`http://192.168.x.x:4321`— y ahí vale `undefined`:
 * llamarlo lanza un TypeError que mata el manejador del clic sin dejar
 * rastro visible. El botón simplemente deja de responder.
 *
 * `crypto.getRandomValues` sí está disponible en cualquier contexto, así
 * que el respaldo sigue siendo aleatoriedad criptográfica de 128 bits, no
 * un `Math.random()` disfrazado.
 */
export function idUnico(): string {
  const c = globalThis.crypto;

  try {
    if (typeof c?.randomUUID === 'function') return c.randomUUID();
  } catch {
    /* sigue al respaldo */
  }

  try {
    if (typeof c?.getRandomValues === 'function') {
      const b = new Uint8Array(16);
      c.getRandomValues(b);
      b[6] = (b[6] & 0x0f) | 0x40; // versión 4
      b[8] = (b[8] & 0x3f) | 0x80; // variante RFC 4122
      const h = Array.from(b, (x) => x.toString(16).padStart(2, '0')).join('');
      return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
    }
  } catch {
    /* sigue al último recurso */
  }

  // Último recurso. Peor entropía, pero un cobro sin llave de idempotencia
  // es peor que una llave imperfecta: el servidor igual protege el
  // reintento por el estado del ticket.
  return `zp-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
}
