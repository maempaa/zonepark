/**
 * Cliente de la API para uso *en el servidor* (SSR).
 *
 * Usa INTERNAL_API_BASE_URL, que apunta al contenedor `api` por la red
 * interna de docker. El navegador nunca ve esta URL: sus peticiones van
 * a /api/* y las reenvía el proxy de src/pages/api/[...path].ts.
 */

const INTERNAL_BASE =
  process.env.INTERNAL_API_BASE_URL ?? 'http://api:8000';

export type ApiResult<T> =
  | { ok: true; data: T }
  | { ok: false; error: string };

export async function apiGet<T>(path: string): Promise<ApiResult<T>> {
  try {
    const res = await fetch(`${INTERNAL_BASE}${path}`, {
      headers: { accept: 'application/json' },
      signal: AbortSignal.timeout(5000),
    });
    if (!res.ok) {
      return { ok: false, error: `La API respondió ${res.status}` };
    }
    return { ok: true, data: (await res.json()) as T };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : 'error desconocido' };
  }
}
