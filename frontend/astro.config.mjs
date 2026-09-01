import { defineConfig } from 'astro/config';
import node from '@astrojs/node';
import react from '@astrojs/react';
import tailwindcss from '@tailwindcss/vite';

/* Astro valida el `Host` que llega contra esta lista. Si no configuras
   ninguna, descarta el host real y arma TODA url como `http://localhost`,
   con lo que su propia defensa CSRF se vuelve en contra: el `Origin` del
   navegador nunca coincide y rechaza los POST legítimos que no llevan
   content-type (los que van sin cuerpo, como publicar una tarifa).
   Se hornea al compilar, así que la variable entra también como build arg. */
const dominios = (process.env.DOMINIOS_PERMITIDOS ?? '')
  .split(',')
  .map((d) => d.trim())
  .filter(Boolean)
  .map((d) => {
    const u = new URL(d.includes('://') ? d : `https://${d}`);
    return {
      hostname: u.hostname,
      // Sin protocolo ni puerto el patrón acepta cualquiera; solo los
      // fijamos cuando quien despliega los escribió a propósito.
      ...(d.includes('://') ? { protocol: u.protocol.slice(0, -1) } : {}),
      ...(u.port ? { port: u.port } : {}),
    };
  });

export default defineConfig({
  output: 'server',
  security: {
    // localhost siempre: por ahí entran la sonda de salud y el desarrollo.
    allowedDomains: [{ hostname: 'localhost' }, { hostname: '127.0.0.1' }, ...dominios],
  },
  adapter: node({ mode: 'standalone' }),
  integrations: [react()],
  vite: {
    plugins: [tailwindcss()],
    // Los volúmenes de docker no propagan eventos inotify de forma fiable.
    server: { watch: { usePolling: true } },
  },
});
