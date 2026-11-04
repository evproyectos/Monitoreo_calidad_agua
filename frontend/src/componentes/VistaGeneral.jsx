import { useState } from "react";
import { useConsulta } from "../api.js";
import { PARAMETROS } from "../formato.js";
import GraficoRed, { EXTREMOS, TEXTO_EXTREMO, resumenRed } from "./GraficoRed.jsx";
import MapaCalor from "./MapaCalor.jsx";
import Anticipacion from "./Anticipacion.jsx";
import Fugas from "./Fugas.jsx";
import { estadoSensor, TEXTO_ESTADO, COLOR_ESTADO } from "./RedSensores.jsx";

const HORAS = 72;

export default function VistaGeneral({ sensores, referencias, onAbrir }) {
  const [par, setPar] = useState("CL2");
  const { datos: red } = useConsulta(`/api/red/series?horas=${HORAS}`, 3000);
  const norma = referencias?.norma;
  const conteo = sensores.reduce((acc, s) => {
    const e = estadoSensor(s, norma);
    return { ...acc, [e]: (acc[e] ?? 0) + 1 };
  }, {});
  const puntos = resumenRed(red, par, norma);
  const { nombre } = PARAMETROS[par];

  return (
    <section className="general" aria-label="Vista general de la red">
      <Anticipacion />
      <Fugas />
      <div className="panel">
        <div className="general-cabeza">
          <p className="resumen" aria-label="Sensores por estado">
            {["alarma", "atencion", "riesgo", "normal", "sin-dato"].filter((e) => conteo[e]).map((e) => (
              <span key={e} style={{ "--estado": `var(${COLOR_ESTADO[e]})` }}>
                <i className={e === "riesgo" ? "riesgo" : ""} />{conteo[e]} {TEXTO_ESTADO[e].toLowerCase()}
              </span>
            ))}
          </p>
          <div className="selector" role="radiogroup" aria-label="Parámetro">
            {Object.entries(PARAMETROS).map(([p, { nombre: n }]) => (
              <button key={p} role="radio" aria-checked={par === p} className={par === p ? "activo" : ""} onClick={() => setPar(p)}>
                {n}
              </button>
            ))}
          </div>
        </div>

        <div className="grafico-cabeza separado">
          <h2>{nombre} en toda la red</h2>
          <span className="nota">Últimas {HORAS} h y pronóstico de las próximas 24 h</span>
        </div>
        <div className="claves">
          <span><i className="linea" /> Mediana de los {sensores.length} sensores</span>
          <span><i className="banda obs" /> La mayoría (del 10 % al 90 %)</span>
          <span><i className="linea fina" /> {EXTREMOS[par].length > 1 ? "Sensores más bajo y más alto" : TEXTO_EXTREMO[EXTREMOS[par][0]]}</span>
          <span><i className="linea pron" /> Pronóstico</span>
          <span><i className="norma" /> Límites de la norma</span>
        </div>
        {puntos.length ? (
          <GraficoRed par={par} puntos={puntos} ahora={red?.ahora} norma={norma?.[par]} />
        ) : (
          <p className="vacio">Cargando las series de la red…</p>
        )}
      </div>

      <div className="panel">
        <div className="grafico-cabeza">
          <h2>Sensor por sensor</h2>
          <span className="nota">De la fuente (arriba) al extremo de la red (abajo). Toca un sensor para ver su detalle.</span>
        </div>
        <MapaCalor red={red} par={par} sensores={sensores} norma={norma} onAbrir={onAbrir} />
      </div>
    </section>
  );
}
