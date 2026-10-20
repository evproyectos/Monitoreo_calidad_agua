import { useEffect, useRef, useState } from "react";

// En desarrollo Vite redirige /api al backend (vite.config.js); en producción el backend sirve
// este mismo dashboard, así que la ruta relativa funciona en los dos casos.
export async function obtener(ruta) {
  const r = await fetch(ruta);
  if (!r.ok) throw new Error(`${ruta}: ${r.status}`);
  return r.json();
}

// Consulta una ruta cada `cadaMs` milisegundos. Devuelve { datos, error }.
export function useConsulta(ruta, cadaMs = 2000) {
  const [estado, setEstado] = useState({ datos: null, error: null });
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
      if (vivo.current) temporizador = setTimeout(ciclo, cadaMs);
    };
    ciclo();
    return () => {
      vivo.current = false;
      clearTimeout(temporizador);
    };
  }, [ruta, cadaMs]);

  return estado;
}
