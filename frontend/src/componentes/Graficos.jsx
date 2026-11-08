import {
  Area, CartesianGrid, ComposedChart, Line, ReferenceArea, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { useColores } from "../colores.js";
import { etiquetaEje, fechaHora, numero, PARAMETROS, tolerancia } from "../formato.js";

// marcas del eje: medianoche y mediodía; en pantallas angostas, solo medianoche
function marcas(puntos) {
  const horas = window.innerWidth < 700 || puntos.length > 120 ? ["00:00"] : ["00:00", "12:00"];
  return puntos.map((p) => p.fecha).filter((f) => horas.includes(f.slice(11, 16)));
}

function Burbuja({ active, payload, label, par }) {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  const { unidad, decimales } = PARAMETROS[par];
  return (
    <div className="tooltip">
      <div className="fecha">{fechaHora(label)}</div>
      <div className="fila"><span>Observado</span><b>{numero(d[par], decimales)} {unidad}</b></div>
      <div className="fila"><span>Pronóstico (hecho 24 h antes)</span><b>{numero(d[`pronostico_${par}`], decimales)} {unidad}</b></div>
    </div>
  );
}

export function GraficoParametro({ par, serie, referencias }) {
  const c = useColores();
  const oscuro = window.matchMedia("(prefers-color-scheme: dark)").matches;
  const { nombre, unidad } = PARAMETROS[par];
  const norma = referencias?.norma?.[par];
  const puntos = serie.puntos.map((p) => {
    const pron = p[`pronostico_${par}`];
    const t = tolerancia(par, pron, referencias?.tolerancia);
    return { ...p, banda: pron == null ? null : [pron - t, pron + t] };
  });
  const lineasNorma = !norma ? [] : par === "TURB"
    ? [{ y: norma.recomendado, txt: "recomendado" }, { y: norma.maximo, txt: "máximo" }]
    : [{ y: norma.minimo, txt: "mínimo" }, { y: norma.maximo, txt: "máximo" }];

  return (
    <div className="grafico">
      <div className="grafico-cabeza">
        <h3>{nombre}{unidad ? ` (${unidad})` : ""}</h3>
        <span className="nota">Últimos 7 días y pronóstico de las próximas 24 h</span>
      </div>
      <div className="lienzo">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={puntos} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid stroke={c.rejilla} vertical={false} />
            <XAxis dataKey="fecha" ticks={marcas(puntos)} tickFormatter={etiquetaEje} tick={{ fill: c["tinta-2"], fontSize: 11 }}
                   stroke={c.linea} tickLine={false} minTickGap={8} />
            <YAxis width={44} tick={{ fill: c["tinta-2"], fontSize: 11 }} stroke={c.linea} tickLine={false} axisLine={false}
                   domain={["auto", "auto"]} padding={{ top: 14 }} tickFormatter={(v) => numero(v, par === "PH" ? 2 : 1)} />
            <Tooltip content={<Burbuja par={par} />} cursor={{ stroke: c["tinta-2"], strokeDasharray: "3 3" }} />
            {lineasNorma.map((l) => (
              <ReferenceLine key={l.txt} y={l.y} stroke={c["tinta-2"]} strokeDasharray="4 4" strokeWidth={1}
                             label={{ value: `${l.txt} ${numero(l.y, par === "TURB" ? 0 : 1)}`, position: "insideBottomRight", fill: c["tinta-2"], fontSize: 10 }} />
            ))}
            <Area dataKey="banda" stroke="none" fill={c.pronostico} fillOpacity={oscuro ? 0.22 : 0.14} isAnimationActive={false} connectNulls={false} />
            <Line dataKey={`pronostico_${par}`} stroke={c.pronostico} strokeWidth={2} strokeDasharray="5 4" dot={false}
                  isAnimationActive={false} connectNulls={false} />
            <Line dataKey={par} stroke={c.observado} strokeWidth={2} dot={false} isAnimationActive={false} connectNulls={false} />
            {serie.ahora && (
              <ReferenceLine x={serie.ahora} stroke={c.tinta} strokeWidth={1}
                             label={{ value: "ahora", position: "insideTopRight", fill: c.tinta, fontSize: 11 }} />
            )}
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function tramosDeAlarma(puntos) {
  const tramos = [];
  let inicio = null;
  puntos.forEach((p, i) => {
    if (p.en_alarma && inicio == null) inicio = p.fecha;
    if (inicio != null && (!p.en_alarma || i === puntos.length - 1)) {
      tramos.push([inicio, p.en_alarma ? p.fecha : puntos[i - 1].fecha]);
      inicio = null;
    }
  });
  return tramos;
}

export function GraficoProbabilidad({ serie, referencias }) {
  const c = useColores();
  const umbral = referencias?.umbral_detector ?? 0.8;
  const puntos = serie.puntos;
  return (
    <div className="grafico">
      <div className="grafico-cabeza">
        <h3>Probabilidad de evento</h3>
        <span className="nota">
          La alarma salta desde {numero(umbral, 2)}{(referencias?.confirmar_h ?? 2) === 1 ? " en una hora" : ` durante ${referencias?.confirmar_h ?? 2} horas seguidas`}
        </span>
      </div>
      <div className="lienzo bajo">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={puntos} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid stroke={c.rejilla} vertical={false} />
            <XAxis dataKey="fecha" ticks={marcas(puntos)} tickFormatter={etiquetaEje} tick={{ fill: c["tinta-2"], fontSize: 11 }}
                   stroke={c.linea} tickLine={false} />
            <YAxis width={44} domain={[0, 1]} ticks={[0, 0.5, 1]} tick={{ fill: c["tinta-2"], fontSize: 11 }}
                   tickFormatter={(v) => numero(v, 1)} axisLine={false} tickLine={false} />
            {tramosDeAlarma(puntos).map(([a, b]) => (
              <ReferenceArea key={a} x1={a} x2={b} fill={c.alarma} fillOpacity={0.12} stroke="none" />
            ))}
            <ReferenceLine y={umbral} stroke={c.alarma} strokeDasharray="4 4" strokeWidth={1}
                           label={{ value: "umbral", position: "insideTopLeft", fill: c.alarma, fontSize: 10 }} />
            <Area dataKey="p_evento" stroke={c["tinta-2"]} strokeWidth={1.5} fill={c["tinta-2"]} fillOpacity={0.12}
                  isAnimationActive={false} connectNulls={false} />
            <Tooltip formatter={(v) => [numero(v, 2), "probabilidad"]} labelFormatter={fechaHora}
                     contentStyle={{ background: c.superficie, border: `1px solid ${c.linea}`, borderRadius: 8, fontSize: 12 }} />
            {serie.ahora && <ReferenceLine x={serie.ahora} stroke={c.tinta} strokeWidth={1} />}
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
