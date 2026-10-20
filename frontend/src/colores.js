import { useEffect, useState } from "react";

// Recharts dibuja en SVG con atributos, que no entienden var(--...): se leen los valores reales
// de las variables CSS y se vuelven a leer si cambia el modo claro/oscuro.
const NOMBRES = ["observado", "pronostico", "alarma", "atencion", "normal", "sin-dato", "tinta", "tinta-2", "linea", "rejilla", "superficie"];

function leer() {
  const css = getComputedStyle(document.documentElement);
  return Object.fromEntries(NOMBRES.map((n) => [n, css.getPropertyValue(`--${n}`).trim()]));
}

export function useColores() {
  const [colores, setColores] = useState(leer);
  useEffect(() => {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const cambio = () => setColores(leer());
    mq.addEventListener("change", cambio);
    return () => mq.removeEventListener("change", cambio);
  }, []);
  return colores;
}
