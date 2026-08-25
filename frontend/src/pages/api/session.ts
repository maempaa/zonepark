/**
 * Inicio y cierre de sesión.
 *
 * Es lo único que el navegador llama para autenticarse. Los tokens no
 * vuelven en la respuesta: se quedan en cookies httpOnly que pone este
 * endpoint. El cliente solo recibe quién es y qué puede hacer.
 */
import type { APIRoute } from 'astro';

import { apiFetch } from '../../lib/api';
import { borrarSesion, guardarSesion, leerSesion } from '../../lib/session';

export const prerender = false;

function json(cuerpo: unknown, status = 200): Response {
  return new Response(JSON.stringify(cuerpo), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

export const POST: APIRoute = async ({ request, cookies }) => {
  let datos: Record<string, string | undefined>;
  try {
    datos = await request.json();
  } catch {
    return json({ detail: 'Cuerpo inválido' }, 400);
  }

  const tenant = (datos.tenant ?? '').toLowerCase().trim();
  if (!tenant) return json({ detail: 'Falta el parqueadero' }, 400);

  const conPin = Boolean(datos.pin);
  const ruta = conPin
    ? `/api/v1/t/${tenant}/auth/pin-login`
    : `/api/v1/t/${tenant}/auth/login`;

  const cuerpo = conPin
    ? {
        email: datos.email,
        pin: datos.pin,
        device_fingerprint: datos.device_fingerprint,
      }
    : {
        email: datos.email,
        password: datos.password,
        device_fingerprint: datos.device_fingerprint ?? null,
        device_nombre: datos.device_nombre ?? null,
      };

  const res = await apiFetch(ruta, {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
      'user-agent': request.headers.get('user-agent') ?? '',
    },
    body: JSON.stringify(cuerpo),
  });

  if (!res.ok) {
    let detalle = 'No se pudo iniciar sesión';
    try {
      const error = await res.json();
      if (typeof error.detail === 'string') detalle = error.detail;
      else if (Array.isArray(error.detail)) detalle = error.detail[0]?.msg ?? detalle;
    } catch {
      /* sin JSON */
    }
    return json({ detail: detalle }, res.status);
  }

  const tokens = await res.json();
  guardarSesion(cookies, {
    access: tokens.access_token,
    refresh: tokens.refresh_token,
    tenant,
    refreshExpiraEn: new Date(tokens.refresh_expires_at),
  });

  // Se devuelve el perfil para que la pantalla pinte sin otra vuelta.
  const perfil = await apiFetch(`/api/v1/t/${tenant}/auth/me`, {
    headers: { authorization: `Bearer ${tokens.access_token}` },
  });

  return json(perfil.ok ? await perfil.json() : { tenant_slug: tenant });
};

export const DELETE: APIRoute = async ({ cookies }) => {
  const sesion = leerSesion(cookies);
  if (sesion) {
    // Revoca también del lado del servidor; si falla, igual se borra la cookie.
    await apiFetch(`/api/v1/t/${sesion.tenant}/auth/logout`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ refresh_token: sesion.refresh }),
    }).catch(() => undefined);
  }
  borrarSesion(cookies);
  return new Response(null, { status: 204 });
};
