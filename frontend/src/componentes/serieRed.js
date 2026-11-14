import { fueraDeNorma } from "../formato.js";

// Lo que la vista general calcula de las series de la red, aparte del gráfico: así la página no
// espera a la librería de gráficos (recharts), que se carga después (RNF-001).

// Qué sensor es "el peor" según el parámetro: el cloro preocupa cuando baja, la turbidez
// cuando sube y el pH en los dos sentidos.
export const EXTREMOS = { CL2: ["min"], TURB: ["max"], PH: ["min", "max"] };
export const TEXTO_EXTREMO = { min: "Sensor más bajo", max: "Sensor más alto" };

function cuantil(ordenados, q) {
  const pos = (ordenados.length - 1) * q;
  const i = Math.floor(pos);
  const r = pos - i;
  return ordenados[i + 1] === undefined ? ordenados[i] : ordenados[i] + r * (ordenados[i + 1] - ordenados[i]);
}

// Resume los 21 sensores en cada hora: mediana, rango del 10 % al 90 % y los extremos (con su
// sensor). En el pasado resume lo observado; desde "ahora", los pronósticos.
export function resumenRed(red, par, norma) {
  if (!red?.fechas?.length) return [];
  const nodos = Object.keys(red.sensores);
  return red.fechas.map((fecha, i) => {
    const futuro = fecha > red.ahora;
    const clave = futuro ? `pronostico_${par}` : par;
    const v = nodos.map((n) => ({ n, x: red.sensores[n][clave]?.[i] })).filter((d) => d.x != null);
    // el pronóstico arranca en "ahora" para que las dos líneas se toquen
    const pv = fecha === red.ahora
      ? nodos.map((n) => ({ n, x: red.sensores[n][`pronostico_${par}`]?.[i] })).filter((d) => d.x != null) : [];
    const punto = { fecha, futuro };
    const llenar = (lista, pre) => {
      if (lista.length < 3) return;
      const ord = lista.map((d) => d.x).sort((a, b) => a - b);
      const min = lista.reduce((a, b) => (b.x < a.x ? b : a));
      const max = lista.reduce((a, b) => (b.x > a.x ? b : a));
      Object.assign(punto, {
        [`${pre}med`]: cuantil(ord, 0.5),
        [`${pre}banda`]: [cuantil(ord, 0.1), cuantil(ord, 0.9)],
        [`${pre}min`]: min.x, [`${pre}min_nodo`]: min.n,
        [`${pre}max`]: max.x, [`${pre}max_nodo`]: max.n,
        [`${pre}n`]: lista.length,
        [`${pre}fuera`]: lista.filter((d) => fueraDeNorma(par, d.x, norma)).length,
      });
    };
    llenar(v, futuro ? "p_" : "o_");
    if (pv.length) llenar(pv, "p_");
    return punto;
  });
}
