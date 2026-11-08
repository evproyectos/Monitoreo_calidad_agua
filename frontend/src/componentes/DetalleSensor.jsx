import { useConsulta } from "../api.js";
import { enFrase, fueraDeNorma, numero, PARAMETROS, TIPOS } from "../formato.js";
import { GraficoParametro, GraficoProbabilidad } from "./Graficos.jsx";

export default function DetalleSensor({ sensor, referencias }) {
  const { datos: serie } = useConsulta(sensor ? `/api/sensores/${sensor.nodo}/serie?horas=168` : null, 3000);

  if (!sensor) return <section className="panel"><p className="vacio">Elige un sensor en la red para ver su detalle.</p></section>;

  return (
    <section className="panel" aria-label={`Detalle del sensor ${sensor.nodo}`}>
      <div className="detalle-cabeza">
        <div>
          <h2>Sensor {sensor.nodo}</h2>
          <div className="sub">
            {sensor.en_alarma
              ? `En alarma. Tipo sugerido: ${enFrase(TIPOS[sensor.tipo_sugerido]) ?? "sin determinar"}`
              : `Cloro típico en este punto: ${numero(sensor.cloro_tipico, 2)} mg/L`}
          </div>
        </div>
        <div className="lecturas">
          {Object.entries(PARAMETROS).map(([par, { nombre, unidad, decimales }]) => (
            <div className="lectura" key={par}>
              <div className="etq">{nombre}</div>
              <div className={`num${fueraDeNorma(par, sensor[par], referencias?.norma) ? " fuera" : ""}`}>
                {numero(sensor[par], decimales)}<small>{unidad}</small>
              </div>
              <div className="etq">en 24 h: {numero(sensor[`pronostico_${par}`], decimales)}</div>
            </div>
          ))}
        </div>
      </div>

      {serie?.puntos?.length ? (
        <>
          <div className="claves">
            <span><i className="linea" /> Observado, últimos 7 días (promedio horario)</span>
            <span><i className="linea pron" /> Pronóstico a 24 h</span>
            <span><i className="banda" /> Margen de acierto</span>
            <span><i className="norma" /> Límites de la norma</span>
          </div>
          {Object.keys(PARAMETROS).map((par) => (
            <GraficoParametro key={par} par={par} serie={serie} referencias={referencias} />
          ))}
          <GraficoProbabilidad serie={serie} referencias={referencias} />
        </>
      ) : (
        <p className="vacio">Cargando la serie del sensor…</p>
      )}
    </section>
  );
}
