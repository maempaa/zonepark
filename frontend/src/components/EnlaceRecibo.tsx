/**
 * Mandarle al cliente el recibo en vivo de su vehículo.
 *
 * Por WhatsApp o por correo, y en los dos casos el dato se pide una vez
 * por placa y se recuerda: quien parquea todos los días no tiene que
 * dictarlo cada mañana, y en la caseta eso es la diferencia entre usarlo
 * y no usarlo. Guardar uno no borra el otro.
 *
 * Los botones de enviar son enlaces de verdad, no `onClick` que navegan.
 * Guardar el dato y abrir WhatsApp o el redactor en el mismo gesto
 * obligaría a esperar la respuesta del servidor antes de navegar, y para
 * entonces el navegador ya considera que la apertura no viene de un toque
 * y la bloquea. Así se abre siempre, y el contacto se guarda de camino.
 */
import { useEffect, useState } from 'react';

import {
  MOTORES,
  type Motor,
  enlaceCorreo,
  motorRecordado,
  recordarMotor,
} from '../lib/correo';
import { comoSeLee, enlaceWhatsApp } from '../lib/whatsapp';

function Icono({ d }: { d: string }) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" className="h-5 w-5 shrink-0" fill="none"
         stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"
         strokeLinejoin="round">
      <path d={d} />
    </svg>
  );
}

const WHATSAPP = 'M21 11.5a8.4 8.4 0 0 1-12.6 7.3L3 20.5l1.8-5.3A8.4 8.4 0 1 1 21 11.5Z';
const SOBRE = 'M3 7a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7Zm0 .5 9 6 9-6';
const COPIAR = 'M9 9h9a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H9a1 1 0 0 1-1-1v-9a1 1 0 0 1 1-1ZM5 15H4a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1h9a1 1 0 0 1 1 1v1';
const BORRAR = 'M4 7h16M10 11v6M14 11v6M6 7l1 13a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1l1-13M9 7V4h6v3';

const BOTON_ENVIAR =
  'flex items-center justify-center gap-2 rounded-zp border-2 border-outline bg-primary ' +
  'px-5 py-3 text-zp-body font-extrabold uppercase tracking-wide text-on-primary ' +
  'active:bg-primary-container';

const BOTON_APAGADO =
  'flex items-center justify-center gap-2 rounded-zp border-2 border-outline-variant ' +
  'bg-surface-container px-5 py-3 text-zp-body font-extrabold uppercase tracking-wide ' +
  'text-on-surface-variant';

interface Props {
  tenant: string;
  token: string;
  codigo: string;
  placa: string | null;
  parqueadero?: string;
}

export default function EnlaceRecibo({
  tenant, token, codigo, placa, parqueadero,
}: Props) {
  const [aviso, setAviso] = useState<string | null>(null);
  const [via, setVia] = useState<'whatsapp' | 'correo'>('whatsapp');
  const [numero, setNumero] = useState('');
  const [correo, setCorreo] = useState('');
  const [motor, setMotor] = useState<Motor>(MOTORES[0]);
  const [recordado, setRecordado] = useState(false);
  const ruta = `/t/${tenant}/r/${token}`;

  const [url, setUrl] = useState(ruta);
  useEffect(() => {
    setUrl(`${window.location.origin}${ruta}`);
    setMotor(motorRecordado());
  }, [ruta]);

  // Si esta placa ya vino antes, el número aparece puesto.
  useEffect(() => {
    if (!placa) return;
    let vigente = true;
    fetch(`/api/v1/t/${tenant}/contactos/${encodeURIComponent(placa)}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((datos) => {
        if (!vigente || !datos) return;
        if (datos.telefono) setNumero(comoSeLee(datos.telefono));
        if (datos.correo) setCorreo(datos.correo);
        if (datos.telefono || datos.correo) setRecordado(true);
        // Se abre por donde se le escribió la última vez.
        if (datos.correo && !datos.telefono) setVia('correo');
      })
      .catch(() => undefined);
    return () => { vigente = false; };
  }, [tenant, placa]);

  const mensaje =
    `Hola, este es el recibo de tu vehículo${placa ? ` ${placa}` : ''}` +
    `${parqueadero ? ` en ${parqueadero}` : ''} (ticket ${codigo}). ` +
    `Ahí puedes ver cuánto llevas: ${url}`;
  const asunto = `Recibo de tu vehículo${placa ? ` ${placa}` : ''} · ${codigo}`;

  const enlace = enlaceWhatsApp(numero, mensaje);
  const enlaceMail = enlaceCorreo(motor, correo, asunto, mensaje);

  /** Se dispara al tocar "Enviar"; no bloquea la navegación. */
  function recordarContacto(campos: Record<string, string>) {
    if (!placa) return;
    void fetch(`/api/v1/t/${tenant}/contactos/${encodeURIComponent(placa)}`, {
      method: 'PUT',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(campos),
    }).catch(() => undefined);
    setRecordado(true);
  }

  async function olvidarNumero() {
    if (!placa) return;
    const res = await fetch(`/api/v1/t/${tenant}/contactos/${encodeURIComponent(placa)}`, {
      method: 'DELETE',
      headers: { 'content-type': 'application/json' },
    }).catch(() => null);
    if (res?.ok) {
      setNumero('');
      setCorreo('');
      setRecordado(false);
      setAviso('Número borrado');
      setTimeout(() => setAviso(null), 4000);
    }
  }

  async function copiar() {
    try {
      await navigator.clipboard.writeText(url);
      setAviso('Enlace copiado');
    } catch {
      setAviso('Copia el enlace de abajo a mano');
    }
    setTimeout(() => setAviso(null), 4000);
  }

  return (
    <div className="rounded-zp border-2 border-outline bg-surface-container-lowest p-4">
      <p className="text-zp-caption font-bold uppercase tracking-wide text-on-surface-variant">
        Recibo del cliente
      </p>
      <p className="mt-1 text-zp-body text-on-surface-variant">
        Podrá ver en su celular cuánto lleva corriendo.
      </p>

      {/* Por dónde se manda. Dos pestañas y no dos formularios: en la
          caseta se manda por uno de los dos, no por los dos. */}
      <div className="mt-4 grid grid-cols-2 gap-2 rounded-zp border-2 border-outline p-1">
        {(['whatsapp', 'correo'] as const).map((v) => (
          <button
            key={v}
            onClick={() => setVia(v)}
            aria-pressed={via === v}
            className={`flex items-center justify-center gap-2 rounded-zp px-3 py-2
                        text-zp-body font-bold transition ${
                          via === v
                            ? 'bg-primary text-on-primary'
                            : 'text-on-surface-variant active:bg-surface-container'
                        }`}
          >
            <Icono d={v === 'whatsapp' ? WHATSAPP : SOBRE} />
            {v === 'whatsapp' ? 'WhatsApp' : 'Correo'}
          </button>
        ))}
      </div>

      {via === 'whatsapp' ? (
        <>
          <label className="mt-4 block space-y-1.5">
            <span className="text-zp-caption font-bold uppercase tracking-wide
                             text-on-surface-variant">
              WhatsApp del cliente
            </span>
            <input
              value={numero}
              onChange={(e) => setNumero(e.target.value)}
              inputMode="tel"
              autoComplete="off"
              placeholder="310 555 0101"
              className="w-full rounded-zp border-2 border-outline bg-surface-container-lowest
                         px-3 py-3 text-zp-lg font-semibold tabular-nums text-on-surface"
            />
          </label>

          <div className="mt-4">
            {enlace ? (
              <a
                href={enlace}
                target="_blank"
                rel="noopener"
                onClick={() => recordarContacto({ telefono: numero })}
                className={BOTON_ENVIAR}
              >
                <Icono d={WHATSAPP} /> Enviar por WhatsApp
              </a>
            ) : (
              <span className={BOTON_APAGADO}>
                <Icono d={WHATSAPP} /> Enviar por WhatsApp
              </span>
            )}
          </div>

          {!enlace && numero.trim() !== '' && (
            <p className="mt-2 text-zp-caption font-bold">Ese número no parece completo.</p>
          )}
        </>
      ) : (
        <>
          <label className="mt-4 block space-y-1.5">
            <span className="text-zp-caption font-bold uppercase tracking-wide
                             text-on-surface-variant">
              Correo del cliente
            </span>
            <input
              value={correo}
              onChange={(e) => setCorreo(e.target.value)}
              inputMode="email"
              autoCapitalize="off"
              autoCorrect="off"
              spellCheck={false}
              autoComplete="off"
              placeholder="cliente@correo.com"
              className="w-full rounded-zp border-2 border-outline bg-surface-container-lowest
                         px-3 py-3 text-zp-body font-semibold text-on-surface"
            />
          </label>

          {/* Con qué se escribe, no a dónde llega: el correo sale del
              operario, así que se elige su propio redactor. */}
          <fieldset className="mt-4">
            <legend className="mb-2 text-zp-caption font-bold uppercase tracking-wide
                               text-on-surface-variant">
              Escribir desde
            </legend>
            <div className="flex flex-wrap gap-2">
              {MOTORES.map((m) => (
                <button
                  key={m.id}
                  onClick={() => { setMotor(m); recordarMotor(m); }}
                  aria-pressed={motor.id === m.id}
                  className={`rounded-zp border-2 border-outline px-3 py-2 text-zp-caption
                              font-bold transition ${
                                motor.id === m.id
                                  ? 'bg-primary text-on-primary'
                                  : 'bg-surface-container-lowest active:bg-surface-container'
                              }`}
                >
                  {m.nombre}
                </button>
              ))}
            </div>
          </fieldset>

          <div className="mt-4">
            {enlaceMail ? (
              <a
                href={enlaceMail}
                target="_blank"
                rel="noopener"
                onClick={() => recordarContacto({ correo })}
                className={BOTON_ENVIAR}
              >
                <Icono d={SOBRE} /> Enviar por {motor.nombre}
              </a>
            ) : (
              <span className={BOTON_APAGADO}>
                <Icono d={SOBRE} /> Enviar por {motor.nombre}
              </span>
            )}
          </div>

          {!enlaceMail && correo.trim() !== '' && (
            <p className="mt-2 text-zp-caption font-bold">Ese correo no parece completo.</p>
          )}
        </>
      )}

      {recordado && placa && (
        <p className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-zp-caption
                      text-on-surface-variant">
          <span>Guardado para {placa}. La próxima vez ya viene puesto.</span>
          <button onClick={olvidarNumero}
                  className="flex items-center gap-1 font-bold text-on-surface underline
                             underline-offset-4">
            <Icono d={BORRAR} /> Borrarlo
          </button>
        </p>
      )}

      <button onClick={copiar} className="mt-3 flex items-center gap-2 rounded-zp border-2
                                          border-outline bg-surface-container-lowest px-4 py-3
                                          text-zp-body font-bold active:bg-surface-container">
        <Icono d={COPIAR} /> Copiar enlace
      </button>

      {aviso && <p className="mt-2 text-zp-caption font-bold">{aviso}</p>}

      {/* Visible siempre: si el envío y el portapapeles fallan, esto se
          puede seleccionar con el dedo. `break-all` porque el token no
          tiene espacios donde cortar. */}
      <p className="mt-3 break-all rounded-zp border-2 border-outline-variant
                    bg-surface-container px-3 py-2 text-zp-caption
                    text-on-surface-variant">
        {url}
      </p>
    </div>
  );
}
