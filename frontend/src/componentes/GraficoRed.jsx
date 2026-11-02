import {
  Area, CartesianGrid, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { useColores } from "../colores.js";
import { etiquetaEje, fechaHora, fueraDeNorma, numero, PARAMETROS } from "../formato.js";

// Qué sensor es "el peor" según el parámetro: el cloro preocupa cuando baja, la turbidez
// cuando sube y el pH en los dos sentidos.
export const EXTREMOS = { CL2: ["min"], TURB: ["max"], PH: ["min", "max"] };
const TEXTO_EXTREMO = { min: "Sensor más bajo", max: "Sensor más alto" };

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

function marcas(puntos) {
  const horas = window.innerWidth < 700 ? ["00:00"] : ["00:00", "12:00"];
  return puntos.map((p) => p.fecha).filter((f) => horas.includes(f.slice(11, 16)));
}

function Burbuja({ active, payload, label, par }) {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  const { unidad, decimales } = PARAMETROS[par];
  const pre = d.futuro ? "p_" : "o_";
  if (d[`${pre}n`] == null) return null;
  const u = unidad ? ` ${unidad}` : "";
  return (
    <div className="tooltip">
      <div className="fecha">{fechaHora(label)}{d.futuro ? " · pronóstico" : ""}</div>
      <div className="fila"><span>Mediana de la red</span><b>{numero(d[`${pre}med`], decimales)}{u}</b></div>
      <div className="fila">
        <span>La mayoría (10 % a 90 %)</span>
        <b>{numero(d[`${pre}banda`][0], decimales)} a {numero(d[`${pre}banda`][1], decimales)}</b>
      </div>
      {EXTREMOS[par].map((e) => (
        <div className="fila" key={e}>
          <span>{TEXTO_EXTREMO[e]} ({d[`${pre}${e}_nodo`]})</span><b>{numero(d[`${pre}${e}`], decimales)}{u}</b>
        </div>
      ))}
      <div className="fila"><span>Fuera de norma</span><b>{d[`${pre}fuera`]} de {d[`${pre}n`]} sensores</b></div>
    </div>
  );
}

export default function GraficoRed({ par, puntos, ahora, norma }) {
  const c = useColores();
  const oscuro = window.matchMedia("(prefers-color-scheme: dark)").matches;
  const { unidad } = PARAMETROS[par];
  const lineasNorma = !norma ? [] : par === "TURB"
    ? [{ y: norma.recomendado, txt: "recomendado" }, { y: norma.maximo, txt: "máximo" }]
    : [{ y: norma.minimo, txt: "mínimo" }, { y: norma.maximo, txt: "máximo" }];

  return (
    <div className="grafico-red">
      <div className="lienzo alto">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={puntos} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid stroke={c.rejilla} vertical={false} />
            <XAxis dataKey="fecha" ticks={marcas(puntos)} tickFormatter={etiquetaEje} tick={{ fill: c["tinta-2"], fontSize: 11 }}
                   stroke={c.linea} tickLine={false} minTickGap={8} />
            <YAxis width={48} tick={{ fill: c["tinta-2"], fontSize: 11 }} stroke={c.linea} tickLine={false} axisLine={false}
                   domain={["auto", "auto"]} padding={{ top: 14 }} tickFormatter={(v) => numero(v, par === "PH" ? 2 : 1)}
                   label={unidad ? { value: unidad, angle: -90, position: "insideLeft", fill: c["tinta-2"], fontSize: 11, dy: 16 } : undefined} />
            <Tooltip content={<Burbuja par={par} />} cursor={{ stroke: c["tinta-2"], strokeDasharray: "3 3" }} />
            {lineasNorma.map((l) => (
              <ReferenceLine key={l.txt} y={l.y} stroke={c["tinta-2"]} strokeDasharray="4 4" strokeWidth={1}
                             label={{ value: `${l.txt} ${numero(l.y, par === "TURB" ? 0 : 1)}`, position: "insideBottomRight", fill: c["tinta-2"], fontSize: 10 }} />
            ))}
            <Area dataKey="o_banda" stroke="none" fill={c.observado} fillOpacity={oscuro ? 0.24 : 0.16} isAnimationActive={false} />
            <Area dataKey="p_banda" stroke="none" fill={c.pronostico} fillOpacity={oscuro ? 0.22 : 0.14} isAnimationActive={false} />
            {EXTREMOS[par].map((e) => (
              <Line key={`o_${e}`} dataKey={`o_${e}`} stroke={c.observado} strokeWidth={1} strokeOpacity={0.9} dot={false}
                    isAnimationActive={false} />
            ))}
            {EXTREMOS[par].map((e) => (
              <Line key={`p_${e}`} dataKey={`p_${e}`} stroke={c.pronostico} strokeWidth={1} strokeOpacity={0.9} dot={false}
                    isAnimationActive={false} />
            ))}
            <Line dataKey="p_med" stroke={c.pronostico} strokeWidth={2} strokeDasharray="5 4" dot={false} isAnimationActive={false} />
            <Line dataKey="o_med" stroke={c.observado} strokeWidth={2.25} dot={false} isAnimationActive={false} />
            {ahora && (
              <ReferenceLine x={ahora} stroke={c.tinta} strokeWidth={1}
                             label={{ value: "ahora", position: "insideTopRight", fill: c.tinta, fontSize: 11 }} />
            )}
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

export { TEXTO_EXTREMO };
