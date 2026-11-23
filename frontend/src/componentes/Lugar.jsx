import { useConsulta } from "../api.js";
import { fechaDia } from "../formato.js";
import { estadoLugar, futuroEnFrase, nombreDe, problemaEnFrase, QUE_ES, NOMBRE } from "../sencillo.js";
import Medidor from "./Medidor.jsx";
import { Icono } from "./Menu.jsx";

// Un lugar (vista sencilla): cómo está el agua ahí, cloro, claridad y pH con su zona normal, y el
// cloro de la última semana. Los gráficos completos están en la vista detallada (#/sensor/...).

const ICONO = { normal: "ok", atencion: "aviso", alarma: "aviso", "sin-dato": "reloj" };

function veredictoLugar(s, e, norma, nombres) {
  if (e.clave === "sin_dato") return { titulo: "No hay datos de este lugar", texto: "El sensor no ha enviado lecturas." };
  if (e.clave === "revisar") return { titulo: "Hay que revisar este lugar", texto: problemaEnFrase(s, norma) };
  if (e.clave === "vigilar") {
    const f = futuroEnFrase(s, norma, nombres);
    return { titulo: "El agua está bien, pero hay que vigilar", texto: f ? `${f.replace(` en ${nombreDe(nombres, s.nodo)}`, "")} en las próximas 24 horas.` : "" };
  }
  if (e.clave === "aviso") {
    const p = e.parametros.find((x) => x.habitual);
    const que = p?.par === "TURB" ? "El agua sigue turbia" : `${p?.par === "PH" ? "El pH" : "El cloro"} sigue ${p?.palabra.replace(" (de siempre)", "")}`;
    return { titulo: `${que}, como de costumbre`, texto: "Pasa casi siempre en este punto. No es algo nuevo, pero conviene revisarlo." };
  }
  return { titulo: "El agua está bien aquí", texto: "Próximas 24 horas: se espera que siga bien." };
}

// el cloro de los últimos 7 días sobre la franja normal
function Semana({ puntos, norma }) {
  const n = norma?.CL2;
  const obs = (puntos ?? []).filter((p) => p.CL2 != null);
  if (!n || obs.length < 2) return <p className="vacio">Todavía no hay una semana de datos.</p>;
  const W = 320, H = 110, max = Math.max(n.maximo * 1.2, ...obs.map((p) => p.CL2));
  const y = (v) => H - (v / max) * H;
  const x = (i) => (i / (puntos.length - 1)) * W;
  const linea = puntos.map((p, i) => (p.CL2 == null ? null : `${x(i).toFixed(1)},${y(p.CL2).toFixed(1)}`));
  const tramos = [];                      // la línea se corta donde no hubo dato
  let actual = [];
  linea.forEach((pt) => {
    if (pt) actual.push(pt);
    else if (actual.length) { tramos.push(actual); actual = []; }
  });
  if (actual.length) tramos.push(actual);
  const fuera = obs.some((p) => p.CL2 < n.minimo || p.CL2 > n.maximo);
  return (
    <>
      <p className="nota-semana">{fuera ? "Hubo horas fuera de lo normal." : "Siempre dentro de lo normal."}</p>
      <svg className="grafico-semana" viewBox={`0 0 ${W} ${H + 18}`} role="img"
           aria-label={`Cloro de los últimos 7 días; lo normal es entre ${n.minimo} y ${n.maximo} mg/L. ${fuera ? "Hubo horas fuera de lo normal." : "Siempre dentro de lo normal."}`}>
        <rect className="franja" x="0" y={y(n.maximo)} width={W} height={y(n.minimo) - y(n.maximo)} />
        {tramos.filter((t) => t.length > 1).map((t, i) => <polyline key={i} className="linea" points={t.join(" ")} />)}
        <text x="0" y={H + 15}>{fechaDia(obs[0].fecha)}</text>
        <text x={W} y={H + 15} textAnchor="end">{fechaDia(obs.at(-1).fecha)}</text>
      </svg>
      <span className="nota">Franja verde: de {String(n.minimo).replace(".", ",")} a {String(n.maximo).replace(".", ",")} mg/L</span>
    </>
  );
}

export default function Lugar({ s, norma, nombres }) {
  const serie = useConsulta(s ? `/api/sensores/${s.nodo}/serie?horas=168` : null, 60000);
  if (!s) return <section className="panel"><p className="vacio">No existe ese lugar.</p><a href="#/inicio">Volver al inicio</a></section>;
  const e = estadoLugar(s, norma);
  const v = veredictoLugar(s, e, norma, nombres);
  const ahora = serie.datos?.ahora;
  const puntos = (serie.datos?.puntos ?? []).filter((p) => !ahora || p.fecha <= ahora);
  return (
    <div className="lugar">
      <a href="#/inicio" className="volver"><Icono nombre="atras" tam={18} />Volver al inicio</a>
      <p className="lugar-zona">{nombres?.[s.nodo]?.zona ? `${nombres[s.nodo].zona} · ` : ""}punto de medición {s.nodo}</p>

      <section className={`panel veredicto compacto tono-${e.tono}`} aria-labelledby="lugar-veredicto">
        <div className="veredicto-principal">
          <span className="veredicto-icono" aria-hidden="true"><Icono nombre={ICONO[e.tono]} tam={26} /></span>
          <div>
            <h2 id="lugar-veredicto">{v.titulo}</h2>
            {v.texto && <p>{v.texto}</p>}
          </div>
        </div>
      </section>

      <div className="lugar-medidas">
        {e.parametros.map((x) => (
          <section key={x.par} className="panel medida" aria-labelledby={`medida-${x.par}`}>
            <div className="medida-cabeza">
              <h2 id={`medida-${x.par}`} className="titulo-tarjeta">{NOMBRE[x.par]} <span>· {QUE_ES[x.par]}</span></h2>
              <span className={`chip tono-${x.tono} fuerte`}>{x.palabra[0].toUpperCase() + x.palabra.slice(1)}</span>
            </div>
            <Medidor par={x.par} valor={x.valor} norma={norma} tono={x.tono} />
          </section>
        ))}
        <section className="panel medida semana" aria-labelledby="semana-titulo">
          <h2 id="semana-titulo" className="titulo-tarjeta">El cloro en la última semana</h2>
          <Semana puntos={puntos} norma={norma} />
        </section>
      </div>

      <p className="panel enlace-detallada">
        ¿Necesitas los gráficos completos y el pronóstico hora por hora? <a href={`#/sensor/${s.nodo}`}>Ver este lugar en la vista detallada</a>
      </p>
    </div>
  );
}
