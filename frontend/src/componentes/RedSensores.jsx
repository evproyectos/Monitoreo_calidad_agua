import { fueraDeNorma, numero } from "../formato.js";

// Estado de cada sensor, del más grave al menos grave.
export function estadoSensor(s, norma) {
  if (s.CL2 == null && s.TURB == null && s.PH == null) return "sin-dato";
  if (s.en_alarma) return "alarma";
  if (["CL2", "TURB", "PH"].some((p) => fueraDeNorma(p, s[p], norma))) return "atencion";
  if (["CL2", "TURB", "PH"].some((p) => fueraDeNorma(p, s[`pronostico_${p}`], norma))) return "riesgo";
  return "normal";
}

export const TEXTO_ESTADO = {
  alarma: "En alarma",
  atencion: "Fuera de norma ahora",
  riesgo: "Fuera de norma en 24 h (pronóstico)",
  normal: "Normal",
  "sin-dato": "Sin dato",
};
export const COLOR_ESTADO = { alarma: "--alarma", atencion: "--atencion", riesgo: "--atencion", normal: "--normal", "sin-dato": "--sin-dato" };

export default function RedSensores({ sensores, norma, elegido, onElegir }) {
  // de la fuente al extremo: el cloro típico baja a medida que el agua recorre la red
  const orden = [...sensores].sort((a, b) => b.cloro_tipico - a.cloro_tipico);
  const conteo = orden.reduce((c, s) => ({ ...c, [estadoSensor(s, norma)]: (c[estadoSensor(s, norma)] ?? 0) + 1 }), {});

  return (
    <section className="red" aria-label="Sensores de la red">
      <div className="red-cabeza">
        <h2>Sensores, de la fuente al extremo de la red</h2>
        <span className="nota">Valor actual de cloro libre (mg/L). Elige un sensor para ver su detalle.</span>
      </div>
      <div className="red-desplazable">
        <div className="tuberia">
          <span className="extremo izq">Fuente</span>
          <span className="extremo der">Extremo de la red</span>
          {orden.map((s) => {
            const est = estadoSensor(s, norma);
            return (
              <button
                key={s.nodo}
                className={`nodo${s.nodo === elegido ? " elegido" : ""}`}
                style={{ "--estado": `var(${COLOR_ESTADO[est]})` }}
                onClick={() => onElegir(s.nodo)}
                aria-pressed={s.nodo === elegido}
                title={`${s.nodo}: ${TEXTO_ESTADO[est]}`}
              >
                <span className={`punto${est === "riesgo" ? " riesgo" : ""}`} />
                <span className="id">{s.nodo}</span>
                <span className="valor">{numero(s.CL2, 2)}</span>
              </button>
            );
          })}
        </div>
      </div>
      <div className="leyenda">
        {["alarma", "atencion", "riesgo", "normal", "sin-dato"].map((e) => (
          <span key={e} style={{ "--estado": `var(${COLOR_ESTADO[e]})` }}>
            <i className={e === "riesgo" ? "riesgo" : ""} />
            {TEXTO_ESTADO[e]} {conteo[e] ? `(${conteo[e]})` : "(0)"}
          </span>
        ))}
      </div>
    </section>
  );
}
