import { Line, LineChart, ReferenceLine, ResponsiveContainer, YAxis } from "recharts";
import { useColores } from "../colores.js";

// La curva de 7 días de una tarjeta. Va en su propio archivo para que las tarjetas se vean antes
// de que llegue la librería de gráficos (RNF-001).
export default function Curva({ valores, minimo, color, alto = 44 }) {
  const c = useColores();
  const datos = valores.map((v, i) => ({ i, v }));
  return (
    <div className="curva" aria-hidden="true">
      <ResponsiveContainer width="100%" height={alto}>
        <LineChart data={datos} margin={{ top: 4, right: 0, bottom: 4, left: 0 }}>
          <YAxis hide domain={["dataMin - 0.05", "dataMax + 0.05"]} />
          {minimo != null && <ReferenceLine y={minimo} stroke={c["tinta-2"]} strokeDasharray="3 3" strokeOpacity={0.6} />}
          <Line dataKey="v" stroke={color ?? c.observado} strokeWidth={1.6} dot={false} isAnimationActive={false} connectNulls />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
