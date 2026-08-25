/**
 * Cliente de la API para uso en el servidor (SSR y endpoints del BFF).
 *
 * Habla con FastAPI por la red interna de docker. El navegador nunca ve
 * esta URL: sus peticiones pasan por /api/*.
 *
 * `llamarApi` renueva el token de acceso sola cuando caduca: si la API
 * responde 401 y hay refresh, lo rota, actualiza las cookies y reintenta
 * una vez. Así ninguna pantalla tiene que preocuparse por la expiración.
 */
import type { AstroCookies } from 'astro';

import { borrarSesion, guardarSesion, leerSesion } from './session';

const INTERNAL_BASE = process.env.INTERNAL_API_BASE_URL ?? 'http://api:8000';

export type Resultado<T> =
  | { ok: true; data: T }
  | { ok: false; status: number; error: string };

async function leerError(res: Response): Promise<string> {
  try {
    const cuerpo = await res.json();
    if (typeof cuerpo?.detail === 'string') return cuerpo.detail;
    if (Array.isArray(cuerpo?.detail)) return cuerpo.detail[0]?.msg ?? 'Datos inválidos';
  } catch {
    /* respuesta sin JSON */
  }
  return `La API respondió ${res.status}`;
}

/** Petición sin sesión (salud, metadatos, login). */
export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  return fetch(`${INTERNAL_BASE}${path}`, {
    ...init,
    headers: { accept: 'application/json', ...(init.headers ?? {}) },
    signal: AbortSignal.timeout(10_000),
  });
}

export async function apiGet<T>(path: string): Promise<Resultado<T>> {
  try {
    const res = await apiFetch(path);
    if (!res.ok) return { ok: false, status: res.status, error: await leerError(res) };
    return { ok: true, data: (await res.json()) as T };
  } catch (e) {
    return { ok: false, status: 0, error: e instanceof Error ? e.message : 'error desconocido' };
  }
}

/** Rota el refresh y deja las cookies al día. Devuelve el nuevo access. */
export async function renovarSesion(
  cookies: AstroCookies,
  tenant: string,
  refresh: string,
): Promise<string | null> {
  const res = await apiFetch(`/api/v1/t/${tenant}/auth/refresh`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ refresh_token: refresh }),
  });

  if (!res.ok) {
    borrarSesion(cookies);
    return null;
  }

  const datos = await res.json();
  guardarSesion(cookies, {
    access: datos.access_token,
    refresh: datos.refresh_token,
    tenant,
    refreshExpiraEn: new Date(datos.refresh_expires_at),
  });
  return datos.access_token as string;
}

/**
 * Petición autenticada, con renovación automática.
 * `path` va sin el prefijo del tenant: se antepone aquí.
 */
export async function llamarApi(
  cookies: AstroCookies,
  tenant: string,
  path: string,
  init: RequestInit = {},
): Promise<Response | null> {
  const sesion = leerSesion(cookies);
  if (!sesion || sesion.tenant !== tenant) return null;

  const ruta = `/api/v1/t/${tenant}${path}`;
  const conToken = (token: string) => ({
    ...init,
    headers: { ...(init.headers ?? {}), authorization: `Bearer ${token}` },
  });

  let res = await apiFetch(ruta, conToken(sesion.access));
  if (res.status !== 401) return res;

  const nuevo = await renovarSesion(cookies, tenant, sesion.refresh);
  if (!nuevo) return null;

  res = await apiFetch(ruta, conToken(nuevo));
  return res;
}
