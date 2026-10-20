import { useState } from "react";
import { Line, LineChart, ReferenceLine, ResponsiveContainer, YAxis } from "recharts";
import { useConsulta } from "../api.js";
import { useColores } from "../colores.js";
import { numero, PARAMETROS, TIPOS } from "../formato.js";
import { estadoSensor, TEXTO_ESTADO, COLOR_ESTADO } from "./RedSensores.jsx";

const TEXTO_CORTO = { alarma: "En alarma", atencion: "Fuera de norma", riesgo: "Riesgo en 24 h", normal: "Normal", "sin-dato": "Sin dato" };

// Escala común por parámetro, para poder comparar sensores entre sí.
function dominio(par, series) {
  const valores = Object.values(series).flatMap((s) => [...s[par], ...s[`pronostico_${par}`]]).filter((v) => v != null);
  if (!valores.length) return ["auto", "auto"];
  const min = Math.min(...valores);
  const max = Math.max(...valores);
  if (par === "CL2") return [0, Math.max(1.1, max)];
  if (par === "TURB") return [0, Math.max(1.5, max)];
  return [Math.min(min, 7.0) - 0.05, Math.max(max, 7.5) + 0.05];
}

function MiniGrafico({ par, datos, ahora, dom, norma }) {
  const c = useColores();
  const lineas = !norma ? [] : par === "TURB" ? [norma.recomendado] : [norma.minimo, norma.maximo];
  return (
    <div className="mini" aria-hidden="true">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={datos} margin={{ top: 4, right: 2, bottom: 2, left: 2 }}>
          <YAxis hide domain={dom} />
          {lineas.map((y) => (
            <ReferenceLine key={y} y={y} stroke={c["tinta-2"]} strokeDasharray="3 3" strokeWidth={1} ifOverflow="hidden" />
          ))}
          <ReferenceLine x={ahora} stroke={c.linea} strokeWidth={1} />
          <Line dataKey="pron" stroke={c.pronostico} strokeWidth={1.5} strokeDasharray="4 3" dot={false} isAnimationActive={false} />
          <Line dataKey="obs" stroke={c.observado} strokeWidth={1.75} dot={false} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

function TarjetaSensor({ s, serie, fechas, ahora, par, dom, referencias, onAbrir }) {
  const est = estadoSensor(s, referencias?.norma);
  // en la mini-gráfica: lo observado hasta ahora y el pronóstico solo hacia adelante
  const datos = fechas.map((f, i) => ({
    f,
    obs: serie?.[par]?.[i] ?? null,
    pron: f >= ahora ? serie?.[`pronostico_${par}`]?.[i] ?? null : null,
  }));
  return (
    <button className={`tarjeta ${est}`} style={{ "--estado": `var(${COLOR_ESTADO[est]})` }} onClick={() => onAbrir(s.nodo)}
            title={`Abrir el sensor ${s.nodo}`}>
      <div className="tarjeta-cabeza">
        <span className="nombre">{s.nodo}</span>
        <span className="etiqueta-estado" title={TEXTO_ESTADO[est]}>
          <i />{est === "alarma" && TIPOS[s.tipo_sugerido] ? TIPOS[s.tipo_sugerido] : TEXTO_CORTO[est]}
        </span>
      </div>
      <div className="valores">
        {Object.entries(PARAMETROS).map(([p, { nombre, unidad, decimales }]) => (
          <span key={p} className={p === par ? "activo" : ""}>
            <span className="etq">{nombre === "Cloro libre" ? "Cloro" : nombre}</span>
            <span><b>{numero(s[p], decimales)}</b>{unidad && <small> {unidad}</small>}</span>
          </span>
        ))}
      </div>
      <MiniGrafico par={par} datos={datos} ahora={ahora} dom={dom} norma={referencias?.norma?.[par]} />
    </button>
  );
}

export default function VistaGeneral({ sensores, referencias, onAbrir }) {
  const [par, setPar] = useState("CL2");
  const { datos: red } = useConsulta("/api/red/series?horas=48", 3000);
  const norma = referencias?.norma;
  const orden = [...sensores].sort((a, b) => b.cloro_tipico - a.cloro_tipico);
  const conteo = orden.reduce((acc, s) => {
    const e = estadoSensor(s, norma);
    return { ...acc, [e]: (acc[e] ?? 0) + 1 };
  }, {});
  const dom = red ? dominio(par, red.sensores) : ["auto", "auto"];

  return (
    <section aria-label="Vista general de los sensores">
      <div className="general-cabeza">
        <p className="resumen">
          {["alarma", "atencion", "riesgo", "normal", "sin-dato"].filter((e) => conteo[e]).map((e, i, arr) => (
            <span key={e} style={{ "--estado": `var(${COLOR_ESTADO[e]})` }}>
              <i />{conteo[e]} {TEXTO_ESTADO[e].toLowerCase()}{i < arr.length - 1 ? "" : ""}
            </span>
          ))}
        </p>
        <div className="selector" role="radiogroup" aria-label="Parámetro de las gráficas">
          {Object.entries(PARAMETROS).map(([p, { nombre }]) => (
            <button key={p} role="radio" aria-checked={par === p} className={par === p ? "activo" : ""} onClick={() => setPar(p)}>
              {nombre}
            </button>
          ))}
        </div>
      </div>
      <p className="nota-general">
        De la fuente al extremo de la red. Cada gráfica muestra las últimas 48 h
        <span className="muestra obs" /> y el pronóstico de las próximas 24 h <span className="muestra pron" />, todas en la
        misma escala. Elige un sensor para ver su detalle.
      </p>
      <div className="rejilla-sensores">
        {orden.map((s) => (
          <TarjetaSensor key={s.nodo} s={s} serie={red?.sensores?.[s.nodo]} fechas={red?.fechas ?? []} ahora={red?.ahora}
                         par={par} dom={dom} referencias={referencias} onAbrir={onAbrir} />
        ))}
      </div>
    </section>
  );
}
