import { lazy, Suspense } from "react";
import { useColores } from "../colores.js";
import { numero, PARAMETROS } from "../formato.js";
import { NIVELES, nivelSensor } from "../estado.js";
import { ordenRed } from "./RedSensores.jsx";

// Una tarjeta por punto de medición, de la fuente al extremo de la red, con su semáforo, el
// cloro actual y su curva de 7 días, y la turbidez y el pH. Al final, la tarjeta de fugas.

// La curva se carga aparte (recharts); mientras tanto queda su espacio, para que nada se mueva.
const CurvaGrafico = lazy(() => import("./Curva.jsx"));

function Curva(props) {
  return (
    <Suspense fallback={<div className="curva" style={{ height: props.alto ?? 44 }} aria-hidden="true" />}>
      <CurvaGrafico {...props} />
    </Suspense>
  );
}

function Semaforo({ nivel }) {
  const n = NIVELES[nivel];
  return <span className={`pastilla nivel-${nivel}`} title={n.texto}><i aria-hidden="true" />{n.corto ?? n.texto}</span>;
}

function TarjetaSensor({ s, red, norma, elegido, onAbrir, posicion }) {
  const nivel = nivelSensor(s, norma);
  const serie = red?.sensores?.[s.nodo]?.CL2 ?? [];
  const pasado = red?.fechas ? serie.filter((_, i) => red.fechas[i] <= red.ahora) : [];
  return (
    <button className={`tarjeta nivel-${nivel}${elegido ? " elegida" : ""}`} onClick={() => onAbrir(s.nodo)}
            aria-pressed={elegido} aria-label={`Sensor ${s.nodo}, ${NIVELES[nivel].texto}. Abrir su detalle`}>
      <span className="tarjeta-cabeza">
        <span className="nodo">{s.nodo}<small>{posicion}</small></span>
        <Semaforo nivel={nivel} />
      </span>
      <span className="principal">
        <span className="etq">Cloro libre</span>
        <span className="valor">{numero(s.CL2, 2)}<small>mg/L</small></span>
      </span>
      {pasado.length > 1 && <Curva valores={pasado} minimo={norma?.CL2?.minimo} />}
      <span className="secundarios">
        {["TURB", "PH"].map((p) => (
          <span key={p}>
            <span className="etq">{PARAMETROS[p].nombre}</span>
            <b>{numero(s[p], 2)}{PARAMETROS[p].unidad && <small> {PARAMETROS[p].unidad}</small>}</b>
          </span>
        ))}
        <span>
          <span className="etq">Cloro en 24 h</span>
          <b>{numero(s.pronostico_CL2, 2)}</b>
        </span>
      </span>
    </button>
  );
}

function TarjetaFugas({ fugas, estado }) {
  const c = useColores();
  if (!fugas?.disponible || !fugas.actual) return null;
  const a = fugas.actual;
  const nivel = estado?.fuga_activa ? "rojo" : a.probabilidad >= a.umbral ? "amarillo" : "verde";
  return (
    <a className={`tarjeta tarjeta-fugas nivel-${nivel}`} href="#/fugas">
      <span className="tarjeta-cabeza">
        <span className="nodo">Fugas<small>Caudal de la fuente</small></span>
        <Semaforo nivel={nivel} />
      </span>
      <span className="principal">
        <span className="etq">Probabilidad de fuga</span>
        <span className="valor">{Math.round(100 * a.probabilidad)}<small>%</small></span>
      </span>
      <Curva valores={fugas.serie.map((p) => p.probabilidad)} minimo={a.umbral} color={c.pronostico} />
      <span className="secundarios">
        <span><span className="etq">Tramo más probable</span><b>{a.tramo.replace(" – ", " y ")}</b></span>
        <span><span className="etq">Caudal de más</span><b>{numero(a.caudal_extra_Ls, 1)}<small> L/s</small></b></span>
      </span>
    </a>
  );
}

export default function Tarjetas({ sensores, red, norma, fugas, estado, elegido, onAbrir }) {
  const orden = ordenRed(sensores);
  const posicion = (i) => (i === 0 ? "Cerca de la fuente" : i === orden.length - 1 ? "Extremo de la red" : "Intermedio");
  return (
    <section className="tarjetas" aria-label="Puntos de medición, de la fuente al extremo de la red">
      {orden.map((s, i) => (
        <TarjetaSensor key={s.nodo} s={s} red={red} norma={norma} elegido={s.nodo === elegido} onAbrir={onAbrir}
                       posicion={posicion(i)} />
      ))}
      <TarjetaFugas fugas={fugas} estado={estado} />
    </section>
  );
}
