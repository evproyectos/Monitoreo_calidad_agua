import { useState } from "react";
import { useColores } from "../colores.js";
import { etiquetaEje, fechaCorta, fueraDeNorma, numero, PARAMETROS } from "../formato.js";
import { estadoSensor, TEXTO_ESTADO, COLOR_ESTADO } from "./RedSensores.jsx";

// Escala de un solo tono (azul): claro = poco, oscuro = mucho. En modo oscuro se invierte para
// que "poco" se funda con el fondo. Los valores fuera de norma van en el color de alarma.
const RAMPA = {
  claro: ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"],
  oscuro: ["#1a3247", "#184f95", "#256abf", "#3987e5", "#6da7ec", "#9ec5f4", "#cde2fb"],
};
// rango de la escala por parámetro (lo que queda fuera se satura en el extremo)
export const ESCALA = { CL2: [0.3, 1.0], TURB: [0, 2], PH: [7.0, 7.6] };

const hex = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
function mezclar(rampa, t) {
  const x = Math.min(1, Math.max(0, t)) * (rampa.length - 1);
  const i = Math.min(rampa.length - 2, Math.floor(x));
  const a = hex(rampa[i]);
  const b = hex(rampa[i + 1]);
  const r = x - i;
  return `rgb(${a.map((v, k) => Math.round(v + r * (b[k] - v))).join(",")})`;
}

export default function MapaCalor({ red, par, sensores, norma, onAbrir }) {
  const c = useColores();
  const oscuro = window.matchMedia("(prefers-color-scheme: dark)").matches;
  const rampa = RAMPA[oscuro ? "oscuro" : "claro"];
  const [punta, setPunta] = useState(null);
  if (!red?.fechas?.length) return null;

  const { unidad, decimales } = PARAMETROS[par];
  const [lo, hi] = ESCALA[par];
  const pasado = red.fechas.map((f, i) => i).filter((i) => red.fechas[i] <= red.ahora);
  const futuro = red.fechas.map((f, i) => i).filter((i) => red.fechas[i] > red.ahora);
  const orden = [...sensores].sort((a, b) => b.cloro_tipico - a.cloro_tipico);

  const valor = (nodo, i) => {
    const s = red.sensores[nodo];
    return red.fechas[i] > red.ahora ? s?.[`pronostico_${par}`]?.[i] : s?.[par]?.[i];
  };
  const color = (v) => (v == null ? "transparent" : fueraDeNorma(par, v, norma) ? c.alarma : mezclar(rampa, (v - lo) / (hi - lo)));

  // columnas: etiqueta · horas pasadas · separación "ahora" · horas pronosticadas
  const plantilla = `var(--etq-mapa) repeat(${pasado.length}, minmax(0, 1fr)) 6px repeat(${futuro.length}, minmax(0, 1fr))`;
  const columna = (i) => (red.fechas[i] > red.ahora ? pasado.length + 3 + futuro.indexOf(i) : 2 + pasado.indexOf(i));
  const total = pasado.length + futuro.length + 2;
  const medianoches = red.fechas.map((f, i) => i).filter((i) => red.fechas[i].slice(11, 13) === "00");

  const mover = (e) => {
    const celda = e.target.closest("[data-i]");
    if (!celda) return setPunta(null);
    const caja = e.currentTarget.getBoundingClientRect();
    setPunta({ nodo: celda.dataset.nodo, i: Number(celda.dataset.i), x: e.clientX - caja.left, y: e.clientY - caja.top, ancho: caja.width });
  };

  return (
    <div className="mapa">
      <div className="mapa-desplazable">
        <div className="mapa-rejilla" style={{ gridTemplateColumns: plantilla }} onMouseMove={mover} onMouseLeave={() => setPunta(null)}>
          {/* encabezado: tramo observado y tramo pronosticado */}
          <span className="mapa-tramo" style={{ gridRow: 1, gridColumn: `2 / span ${pasado.length}` }}>Observado<span className="largo"> · últimas {pasado.length} h</span></span>
          <span className="mapa-tramo pron" style={{ gridRow: 1, gridColumn: `${pasado.length + 3} / span ${futuro.length}` }}>Pronóstico<span className="largo"> · 24 h</span></span>

          {orden.map((s, k) => {
            const est = estadoSensor(s, norma);
            return [
              <button key={`${s.nodo}-e`} className="mapa-etq" onClick={() => onAbrir(s.nodo)}
                      title={`${s.nodo}: ${TEXTO_ESTADO[est]}. Abrir el sensor`}
                      style={{ gridRow: k + 2, gridColumn: 1, "--estado": `var(${COLOR_ESTADO[est]})` }}>
                <i className={est === "riesgo" ? "riesgo" : ""} />{s.nodo}
              </button>,
              ...[...pasado, ...futuro].map((i) => (
                <span key={`${s.nodo}-${i}`} className="celda" data-nodo={s.nodo} data-i={i}
                      style={{ gridRow: k + 2, gridColumn: columna(i), background: color(valor(s.nodo, i)) }} />
              )),
            ];
          })}

          {/* línea de "ahora" entre los dos tramos */}
          <span className="mapa-ahora" style={{ gridColumn: pasado.length + 2, gridRow: `2 / span ${orden.length}` }} />

          {/* eje de tiempo: una marca por medianoche */}
          {medianoches.map((i) => (
            <span key={`m-${i}`} className="mapa-eje" style={{ gridRow: orden.length + 2, gridColumn: `${columna(i)} / span ${Math.min(12, total - columna(i) + 1)}` }}>{etiquetaEje(red.fechas[i])}</span>
          ))}
        </div>
      </div>

      {punta && (() => {
        const v = valor(punta.nodo, punta.i);
        const fut = red.fechas[punta.i] > red.ahora;
        return (
          <div className="tooltip mapa-punta" style={{ left: Math.min(punta.x + 14, punta.ancho - 200), top: punta.y + 14 }}>
            <div className="fecha">{punta.nodo} · {fechaCorta(red.fechas[punta.i])}</div>
            <div className="fila">
              <span>{fut ? "Pronóstico" : "Observado"}</span>
              <b>{numero(v, decimales)}{unidad ? ` ${unidad}` : ""}</b>
            </div>
            {fueraDeNorma(par, v, norma) && <div className="fila"><span>Fuera de norma</span></div>}
          </div>
        );
      })()}

      <div className="mapa-leyenda">
        <span className="escala">
          {numero(lo, 1)}
          <i style={{ background: `linear-gradient(90deg, ${rampa.join(",")})` }} />
          {numero(hi, 1)}{par === "TURB" ? " o más" : ""}{unidad ? ` ${unidad}` : ""}
        </span>
        <span><i style={{ background: c.alarma }} />Fuera de norma</span>
        <span><i className="vacia" />Sin dato</span>
      </div>
    </div>
  );
}
