import { Area, CartesianGrid, ComposedChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useConsulta } from "../api.js";
import { useColores } from "../colores.js";
import { etiquetaEje, fechaHora, numero } from "../formato.js";

// Fugas (modelo del notebook 10): probabilidad de fuga de los últimos 7 días con su umbral, el
// tramo más probable (entre qué dos sensores) y cuánto caudal de más entrega la fuente.
function pct(x) {
  return x == null ? "—" : `${Math.round(100 * x)} %`;
}

function Burbuja({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  return (
    <div className="tooltip">
      <div className="fecha">{fechaHora(label)}</div>
      <div className="fila"><span>Probabilidad de fuga</span><b>{pct(d.probabilidad)}</b></div>
      <div className="fila"><span>Caudal de más</span><b>{numero(d.caudal_extra_Ls, 1)} L/s</b></div>
    </div>
  );
}

export default function Fugas() {
  const c = useColores();
  const { datos } = useConsulta("/api/fugas?horas=168", 5000);
  if (!datos?.disponible) return null;
  const a = datos.actual;
  const marcas = datos.serie.map((p) => p.fecha).filter((f) => f.slice(11, 16) === "00:00");
  const recientes = [...datos.fugas].reverse().slice(0, 3);

  return (
    <section id="fugas" className="panel fugas" aria-label="Fugas">
      <div className="grafico-cabeza">
        <h2>¿Hay una fuga?</h2>
        <span className="nota">
          Caudal de la fuente y presión de los sensores contra lo normal{datos.hora ? ` · ${fechaHora(datos.hora)}` : ""}
        </span>
      </div>
      {a ? (
        <p className={`anticipacion-estado${a.en_alarma ? " en-alarma" : ""}`}>
          {a.en_alarma
            ? `Posible fuga en el tramo ${a.tramo} · la fuente entrega ${numero(a.caudal_extra_Ls, 1)} L/s de más`
            : `Sin fuga: probabilidad ${pct(a.probabilidad)} (alarma desde ${pct(a.umbral)} durante ${datos.confirmar_h} h)`}
        </p>
      ) : (
        <p className="vacio">Esperando las primeras horas completas.</p>
      )}
      {datos.serie.length > 0 && (
        <ResponsiveContainer width="100%" height={150}>
          <ComposedChart data={datos.serie} margin={{ top: 6, right: 8, bottom: 0, left: -18 }}>
            <CartesianGrid stroke={c.rejilla} vertical={false} />
            <XAxis dataKey="fecha" ticks={marcas} tickFormatter={etiquetaEje} tick={{ fontSize: 11, fill: c["tinta-2"] }}
                   stroke={c.linea} />
            <YAxis domain={[0, 1]} ticks={[0, 0.5, 1]} tickFormatter={pct} tick={{ fontSize: 11, fill: c["tinta-2"] }}
                   stroke={c.linea} />
            <Tooltip content={<Burbuja />} />
            <ReferenceLine y={a?.umbral} stroke={c["tinta-2"]} strokeDasharray="4 3" />
            <Area type="stepAfter" dataKey="probabilidad" stroke={c.observado} fill={c.observado} fillOpacity={0.18}
                  strokeWidth={1.5} isAnimationActive={false} />
          </ComposedChart>
        </ResponsiveContainer>
      )}
      <p className="nota">
        Tramos posibles: {datos.tramos.join(" · ")}
        {recientes.length > 0 && <> · Recientes: {recientes.map((f) => `${f.tramo} (${fechaHora(f.inicio)}${f.fin ? "" : ", abierta"})`).join(" · ")}</>}
      </p>
    </section>
  );
}
