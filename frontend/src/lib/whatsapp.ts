/**
 * Cómo se arma un enlace de WhatsApp a partir de un número dictado.
 *
 * `wa.me` exige el número en formato internacional y sin adornos. Quien
 * teclea en la caseta escribe lo que el cliente le dicta: "310 555 0101",
 * "(310) 555-0101", a veces con indicativo y a veces sin él.
 */

/** Colombia. Es donde opera el parqueadero; se aplica solo si falta. */
const INDICATIVO_POR_DEFECTO = '57';

/** Un celular colombiano son 10 dígitos y empieza por 3. */
const LARGO_NACIONAL = 10;

export function aNumeroInternacional(valor: string): string | null {
  const crudo = (valor ?? '').trim();
  const digitos = crudo.replace(/\D/g, '');
  if (digitos.length < 7) return null;

  // Un "+" delante significa que quien lo escribió ya puso el indicativo.
  if (crudo.startsWith('+')) return digitos;

  // Sin "+", solo se antepone el indicativo si el número tiene el largo
  // de uno nacional. Uno más largo ya lo trae, y agregárselo lo rompería.
  if (digitos.length === LARGO_NACIONAL) return INDICATIVO_POR_DEFECTO + digitos;
  return digitos;
}

/** Cómo se lee en pantalla: 310 555 0101. */
export function comoSeLee(valor: string): string {
  const d = (valor ?? '').replace(/\D/g, '');
  if (d.length === LARGO_NACIONAL) return `${d.slice(0, 3)} ${d.slice(3, 6)} ${d.slice(6)}`;
  return valor;
}

export function enlaceWhatsApp(numero: string, mensaje: string): string | null {
  const destino = aNumeroInternacional(numero);
  if (!destino) return null;
  return `https://wa.me/${destino}?text=${encodeURIComponent(mensaje)}`;
}
