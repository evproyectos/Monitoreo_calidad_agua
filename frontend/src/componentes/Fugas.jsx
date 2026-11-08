import { useState } from "react";
import { useColores } from "../colores.js";
import { fechaDia, fechaHora, numero } from "../formato.js";

// Riesgo de fuga por tramo de la red (RF-003.2 e): una fila por tramo (entre qué dos sensores) y
// una columna por hora de los últimos 7 días. El riesgo de un tramo es la probabilidad de fuga por
// la probabilidad de que la fuga esté en ese tramo.
function pct(x) {
  return x == null ? "—" : `${Math.round(100 * x)} %`;
}

// de casi blanco a rojo, pasando por ámbar
const RAMPA = {
  claro: ["#fbf6ee", "#f8e3bf", "#f3c784", "#ec9f4c", "#df6c2f", "#c7401f", "#9e2416"],
  oscuro: ["#1d2a30", "#4a3a22", "#7a5524", "#a8692a", "#cf6f2d", "#e5532a", "#ff6b4a"],
};
function mezclar(rampa, t) {
  const x = Math.max(0, Math.min(1, t)) * (rampa.length - 1);
  const i = Math.min(rampa.length - 2, Math.floor(x));
  const f = x - i;
  const a = rampa[i].match(/\w\w/g).map((h) => parseInt(h, 16));
  const b = rampa[i + 1].match(/\w\w/g).map((h) => parseInt(h, 16));
  return `rgb(${a.map((v, k) => Math.round(v + f * (b[k] - v))).join(",")})`;
}

export default function Fugas({ datos }) {
  const c = useColores();
  const [punta, setPunta] = useState(null);
  if (!datos?.disponible) return null;
  const a = datos.actual;
  const oscuro = window.matchMedia("(prefers-color-scheme: dark)").matches;
  const rampa = RAMPA[oscuro ? "oscuro" : "claro"];
  const serie = datos.serie;
  const tramos = datos.tramos;
  // la escala satura en el umbral de alarma: a partir de ahí, rojo
  const tope = a?.umbral ?? 0.5;
  const marcas = serie.map((p, i) => [p.fecha, i]).filter(([f]) => f.slice(11, 16) === "00:00");

  return (
    <section id="fugas" className="panel fugas" aria-label="Riesgo de fuga por tramo">
      <div className="panel-cabeza">
        <h2>Riesgo de fuga por tramo</h2>
        <span className="nota">Últimos 7 días</span>
      </div>
      {a ? (
        <p className={`estado-linea${a.en_alarma ? " en-alarma" : ""}`}>
          {a.en_alarma
            ? `Posible fuga entre ${a.tramo.replace(" – ", " y ")}: la fuente entrega ${numero(a.caudal_extra_Ls, 1)} L/s de más`
            : `Sin fuga: ${pct(a.probabilidad)} de probabilidad. La alarma salta desde ${pct(a.umbral)} durante ${datos.confirmar_h} h.`}
        </p>
      ) : (
        <p className="vacio">Esperando las primeras horas completas.</p>
      )}
      {serie.length > 0 && (
        <div className="calor-tramos" onMouseLeave={() => setPunta(null)}>
          <div className="filas" style={{ "--horas": serie.length }}>
            {tramos.map((t) => (
              <div className="fila" key={t}>
                <span className="tramo">{t.replace(" – ", " y ")}</span>
                <span className="celdas">
                  {serie.map((p, i) => {
                    const r = p.riesgo?.[t];
                    return (
                      <i key={i} style={{ background: r == null ? "transparent" : mezclar(rampa, r / tope) }}
                         onMouseEnter={(e) => setPunta({ t, i, x: e.currentTarget.offsetLeft })} />
                    );
                  })}
                </span>
              </div>
            ))}
            <div className="fila eje">
              <span className="tramo" />
              <span className="celdas marcas">
                {marcas.map(([f, i]) => (
                  <span key={f} style={{ left: `${(100 * i) / serie.length}%` }}>{fechaDia(f).slice(0, 5)}</span>
                ))}
              </span>
            </div>
          </div>
          {punta && (
            <div className="tooltip punta-tramo" style={{ left: Math.max(0, punta.x - 60) }}>
              <div className="fecha">{fechaHora(serie[punta.i].fecha)}</div>
              <div className="fila"><span>Riesgo en {punta.t.replace(" – ", " y ")}</span><b>{pct(serie[punta.i].riesgo?.[punta.t])}</b></div>
              <div className="fila"><span>Probabilidad de fuga</span><b>{pct(serie[punta.i].probabilidad)}</b></div>
              <div className="fila"><span>Caudal de más</span><b>{numero(serie[punta.i].caudal_extra_Ls, 1)} L/s</b></div>
            </div>
          )}
        </div>
      )}
      <div className="mapa-leyenda">
        <span className="escala">
          0 %<i style={{ background: `linear-gradient(90deg, ${rampa.join(",")})` }} />{pct(tope)} o más
        </span>
        <span style={{ color: c["tinta-2"] }}>Riesgo = probabilidad de fuga × probabilidad de que esté en ese tramo</span>
      </div>
    </section>
  );
}
