/**
 * Sesión del operario, guardada en cookies httpOnly.
 *
 * El navegador nunca ve los tokens: los pone y los lee este servidor. Por
 * eso un XSS en la página no basta para robar la sesión.
 *
 * Se mantiene **una sesión por navegador**. La cookie `zp_tenant` dice a
 * qué parqueadero pertenece; si alguien abre la URL de otro, el token no
 * se adjunta y termina en su pantalla de ingreso. Es lo que corresponde:
 * un operario trabaja en un parqueadero a la vez.
 */
import type { AstroCookies } from 'astro';

export const COOKIE_ACCESS = 'zp_access';
export const COOKIE_REFRESH = 'zp_refresh';
export const COOKIE_TENANT = 'zp_tenant';

const EN_PRODUCCION = process.env.APP_ENV === 'production';

const BASE = {
  httpOnly: true,
  secure: EN_PRODUCCION,
  sameSite: 'lax' as const,
  path: '/',
};

export interface Sesion {
  access: string;
  refresh: string;
  tenant: string;
}

export function leerSesion(cookies: AstroCookies): Sesion | null {
  const access = cookies.get(COOKIE_ACCESS)?.value;
  const refresh = cookies.get(COOKIE_REFRESH)?.value;
  const tenant = cookies.get(COOKIE_TENANT)?.value;
  if (!access || !refresh || !tenant) return null;
  return { access, refresh, tenant };
}

export function guardarSesion(
  cookies: AstroCookies,
  datos: { access: string; refresh: string; tenant: string; refreshExpiraEn: Date },
): void {
  const segundos = Math.max(
    60,
    Math.floor((datos.refreshExpiraEn.getTime() - Date.now()) / 1000),
  );
  // Ambas viven lo mismo: si el access caduca, el proxy lo renueva solo.
  cookies.set(COOKIE_ACCESS, datos.access, { ...BASE, maxAge: segundos });
  cookies.set(COOKIE_REFRESH, datos.refresh, { ...BASE, maxAge: segundos });
  cookies.set(COOKIE_TENANT, datos.tenant, { ...BASE, maxAge: segundos });
}

export function borrarSesion(cookies: AstroCookies): void {
  for (const nombre of [COOKIE_ACCESS, COOKIE_REFRESH, COOKIE_TENANT]) {
    cookies.delete(nombre, { path: '/' });
  }
}
