/**
 * Inicio y cierre de sesión del panel de plataforma.
 *
 * Igual que /api/session pero con sus propias cookies: un administrador
 * puede tener el panel abierto y, a la vez, entrar a un parqueadero para
 * ver lo que ve su cliente.
 */
import type { APIRoute } from 'astro';

import { apiFetch } from '../../lib/api';
import { borrarSesionAdmin, guardarSesionAdmin, leerSesionAdmin } from '../../lib/session';

export const prerender = false;

function json(cuerpo: unknown, status = 200): Response {
  return new Response(JSON.stringify(cuerpo), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

export const POST: APIRoute = async ({ request, cookies }) => {
  let datos: Record<string, string>;
  try {
    datos = await request.json();
  } catch {
    return json({ detail: 'Cuerpo inválido' }, 400);
  }

  const res = await apiFetch('/api/v1/admin/auth/login', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ email: datos.email, password: datos.password }),
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
  guardarSesionAdmin(cookies, {
    access: tokens.access_token,
    refresh: tokens.refresh_token,
    refreshExpiraEn: new Date(tokens.refresh_expires_at),
  });

  const perfil = await apiFetch('/api/v1/admin/me', {
    headers: { authorization: `Bearer ${tokens.access_token}` },
  });
  return json(perfil.ok ? await perfil.json() : { email: datos.email });
};

export const DELETE: APIRoute = async ({ cookies }) => {
  const sesion = leerSesionAdmin(cookies);
  if (sesion) {
    await apiFetch('/api/v1/admin/auth/logout', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ refresh_token: sesion.refresh }),
    }).catch(() => undefined);
  }
  borrarSesionAdmin(cookies);
  return new Response(null, { status: 204 });
};
