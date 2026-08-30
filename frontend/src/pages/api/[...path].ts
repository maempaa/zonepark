/**
 * BFF: reenvía /api/* al backend por la red interna de docker.
 *
 * Añade el token de la cookie httpOnly y, si caducó, lo renueva y
 * reintenta una sola vez. De cara al navegador la sesión simplemente
 * dura; nunca ve un token ni tiene que refrescar nada.
 */
import type { APIRoute } from 'astro';

import { renovarSesion, renovarSesionAdmin } from '../../lib/api';
import { leerSesion, leerSesionAdmin } from '../../lib/session';

export const prerender = false;

const INTERNAL_BASE = process.env.INTERNAL_API_BASE_URL ?? 'http://api:8000';

// Cabeceras que no deben viajar aguas arriba.
const OMITIR = new Set([
  'host',
  'connection',
  'content-length',
  'accept-encoding',
  'cookie',
  'authorization',
]);

/** Saca el slug de rutas tipo /api/v1/t/{slug}/... */
function tenantDeLaRuta(path: string): string | null {
  const partes = path.split('/');
  const i = partes.indexOf('t');
  return i >= 0 && partes[i + 1] ? partes[i + 1] : null;
}

const handler: APIRoute = async ({ params, request, cookies }) => {
  const url = new URL(request.url);
  const path = params.path ?? '';
  const destino = `${INTERNAL_BASE}/api/${path}${url.search}`;

  const headers = new Headers();
  request.headers.forEach((valor, clave) => {
    if (!OMITIR.has(clave.toLowerCase())) headers.set(clave, valor);
  });

  // Las rutas de plataforma llevan su propia sesión; las de tenant, la
  // suya, y solo si el token es de ese mismo parqueadero.
  const esPlataforma = path.startsWith('v1/admin/') || path === 'v1/admin';
  const sesion = esPlataforma ? null : leerSesion(cookies);
  const sesionAdmin = esPlataforma ? leerSesionAdmin(cookies) : null;
  const tenant = esPlataforma ? null : tenantDeLaRuta(path);

  const autenticada = esPlataforma
    ? sesionAdmin !== null
    : Boolean(sesion && tenant && sesion.tenant === tenant);

  if (autenticada) {
    const token = esPlataforma ? sesionAdmin!.access : sesion!.access;
    headers.set('authorization', `Bearer ${token}`);
  }

  const cuerpo = ['GET', 'HEAD'].includes(request.method)
    ? undefined
    : await request.arrayBuffer();

  const enviar = (h: Headers) =>
    fetch(destino, {
      method: request.method,
      headers: h,
      body: cuerpo,
      redirect: 'manual',
      signal: AbortSignal.timeout(15_000),
    });

  try {
    let res = await enviar(headers);

    // Token vencido: se rota y se reintenta una vez.
    if (res.status === 401 && autenticada) {
      const nuevo = esPlataforma
        ? await renovarSesionAdmin(cookies, sesionAdmin!.refresh)
        : await renovarSesion(cookies, tenant!, sesion!.refresh);
      if (nuevo) {
        headers.set('authorization', `Bearer ${nuevo}`);
        res = await enviar(headers);
      }
    }

    const salida = new Headers(res.headers);
    salida.delete('content-encoding');
    salida.delete('content-length');
    return new Response(res.body, { status: res.status, headers: salida });
  } catch (e) {
    return new Response(
      JSON.stringify({
        detail: 'No se pudo contactar el backend',
        causa: e instanceof Error ? e.message : String(e),
      }),
      { status: 502, headers: { 'content-type': 'application/json' } },
    );
  }
};

export const GET = handler;
export const POST = handler;
export const PUT = handler;
export const PATCH = handler;
export const DELETE = handler;
