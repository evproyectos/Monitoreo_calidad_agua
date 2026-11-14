import { useEffect, useRef, useState } from "react";

// En desarrollo Vite redirige /api al backend (vite.config.js); en producción el backend sirve
// este mismo dashboard, así que la ruta relativa funciona en los dos casos.

// Si la sesión venció (401) o hay que cambiar la contraseña temporal (403 con debe_cambiar),
// se avisa a Sesion.jsx para que muestre la pantalla que corresponde.
function avisarSesion(status, cuerpo) {
  if (status === 401) window.dispatchEvent(new Event("sesion:vencida"));
  if (status === 403 && cuerpo?.detail?.debe_cambiar) window.dispatchEvent(new Event("sesion:cambiar"));
}

export class ErrorApi extends Error {
  constructor(status, mensaje) {
    super(mensaje);
    this.status = status;
  }
}

// La respuesta que index.html ya pidió para esta ruta (RNF-001), una sola vez y solo en los
// primeros 15 s; null si no hay.
function precargada(ruta) {
  const p = window.__precarga;
  if (!p || Date.now() - p.t > 15000) return null;
  const r = p.r[ruta];
  delete p.r[ruta];
  return r ?? null;
}

// Sin sesión (o con la contraseña temporal) lo demás que se pidió por adelantado no sirve: después
// de entrar se pide de nuevo.
export function descartarPrecarga() {
  window.__precarga = null;
}

// GET, POST, PATCH o DELETE con JSON. Lanza ErrorApi con el mensaje del servidor.
export async function pedir(ruta, { metodo = "GET", cuerpo } = {}) {
  const previa = metodo === "GET" ? precargada(ruta) : null;
  let ok, status, datos;
  if (previa) {
    ({ ok, status, d: datos } = await previa);
  } else {
    const r = await fetch(ruta, {
      method: metodo,
      credentials: "same-origin",
      headers: cuerpo ? { "Content-Type": "application/json" } : undefined,
      body: cuerpo ? JSON.stringify(cuerpo) : undefined,
    });
    ({ ok, status } = r);
    try { datos = await r.json(); } catch { datos = null; }
  }
  if (!ok) {
    if (ruta !== "/api/sesion") avisarSesion(status, datos);
    const d = datos?.detail;
    throw new ErrorApi(status, (typeof d === "string" ? d : d?.error) ?? `Error ${status}`);
  }
  return datos;
}

export function obtener(ruta) {
  return pedir(ruta);
}

// Consulta una ruta cada `cadaMs` milisegundos. Devuelve { datos, error, recargar }.
export function useConsulta(ruta, cadaMs = 2000) {
  const [estado, setEstado] = useState({ datos: null, error: null });
  const [vuelta, setVuelta] = useState(0);
  const vivo = useRef(true);

  useEffect(() => {
    vivo.current = true;
    if (!ruta) return undefined;
    let temporizador;
    const ciclo = async () => {
      try {
        const datos = await obtener(ruta);
        if (vivo.current) setEstado({ datos, error: null });
      } catch (e) {
        if (vivo.current) setEstado((s) => ({ datos: s.datos, error: e }));
      }
      if (vivo.current && cadaMs) temporizador = setTimeout(ciclo, cadaMs);
    };
    ciclo();
    return () => {
      vivo.current = false;
      clearTimeout(temporizador);
    };
  }, [ruta, cadaMs, vuelta]);

  return { ...estado, recargar: () => setVuelta((v) => v + 1) };
}
