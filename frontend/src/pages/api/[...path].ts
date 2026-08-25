/**
 * BFF: reenvía todo /api/* al backend por la red interna de docker.
 *
 * Existe para que el navegador nunca hable directo con FastAPI. En la
 * fase 1 este mismo punto lee la cookie httpOnly de sesión y le añade
 * el Authorization al request antes de reenviarlo.
 */
import type { APIRoute } from 'astro';

export const prerender = false;

const INTERNAL_BASE = process.env.INTERNAL_API_BASE_URL ?? 'http://api:8000';

// Cabeceras que no deben viajar aguas arriba.
const OMITIR = new Set(['host', 'connection', 'content-length', 'accept-encoding']);

const handler: APIRoute = async ({ params, request }) => {
  const url = new URL(request.url);
  const destino = `${INTERNAL_BASE}/api/${params.path ?? ''}${url.search}`;

  const headers = new Headers();
  request.headers.forEach((valor, clave) => {
    if (!OMITIR.has(clave.toLowerCase())) headers.set(clave, valor);
  });

  const tieneCuerpo = !['GET', 'HEAD'].includes(request.method);

  try {
    const res = await fetch(destino, {
      method: request.method,
      headers,
      body: tieneCuerpo ? await request.arrayBuffer() : undefined,
      redirect: 'manual',
      signal: AbortSignal.timeout(15000),
    });

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
