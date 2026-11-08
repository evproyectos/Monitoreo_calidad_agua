import { useState } from "react";
import { PARAMETROS } from "../formato.js";
import GraficoRed, { EXTREMOS, TEXTO_EXTREMO, resumenRed } from "./GraficoRed.jsx";
import MapaCalor from "./MapaCalor.jsx";
import Anticipacion from "./Anticipacion.jsx";
import Fugas from "./Fugas.jsx";

const HORAS = 168;                        // RF-003.2 b: los últimos 7 días

export { HORAS };

export default function VistaGeneral({ sensores, referencias, red, anticipacion, fugas, onAbrir }) {
  const [par, setPar] = useState("CL2");
  const norma = referencias?.norma;
  const puntos = resumenRed(red, par, norma);
  const { nombre } = PARAMETROS[par];

  return (
    <section className="general" aria-label="Vista general de la red">
      <div className="panel">
        <div className="general-cabeza">
          <h2>{nombre} en toda la red</h2>
          <div className="selector" role="radiogroup" aria-label="Parámetro">
            {Object.entries(PARAMETROS).map(([p, { nombre: n }]) => (
              <button key={p} role="radio" aria-checked={par === p} className={par === p ? "activo" : ""} onClick={() => setPar(p)}>
                {n}
              </button>
            ))}
          </div>
        </div>

        <p className="nota">Últimos 7 días y pronóstico de las próximas 24 h, con el rango de los sensores</p>
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

      <div className="vigilancia">
        <Anticipacion datos={anticipacion} />
        <Fugas datos={fugas} />
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
