import {
  Area, CartesianGrid, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { useColores } from "../colores.js";
import { etiquetaEje, fechaHora, numero, PARAMETROS } from "../formato.js";
import { EXTREMOS, TEXTO_EXTREMO } from "./serieRed.js";

function marcas(puntos) {
  const horas = window.innerWidth < 700 || puntos.length > 120 ? ["00:00"] : ["00:00", "12:00"];
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

