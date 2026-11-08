import { fechaDia, hora, TIPOS } from "../formato.js";

// Historial de alarmas del detector: de la más reciente a la más antigua, con el día y la hora a la izquierda,
// como el cuaderno del operador. Cada entrada abre el primer sensor que la vio.
function duracion(a) {
  if (a.fin == null) return `En curso, ${a.horas} h`;
  if (a.horas === 1) return "1 h";
  const mismoDia = a.inicio.slice(0, 10) === a.fin.slice(0, 10);
  return `${a.horas} h, hasta ${mismoDia ? hora(a.fin).slice(0, 5) : `el ${fechaDia(a.fin).slice(0, 5)} a las ${hora(a.fin).slice(0, 5)}`}`;
}

export default function Alarmas({ alarmas, confirmarH, onElegir }) {
  return (
    <section className="panel bitacora" aria-label="Historial de alarmas">
      <div className="panel-cabeza"><h2>Historial de alarmas</h2></div>
      {!alarmas?.length ? (
        <p className="vacio">
          Sin alarmas por ahora. Una alarma se anota aquí cuando un sensor supera el umbral del detector
          durante {confirmarH ?? 2} {confirmarH === 1 ? "hora" : "horas seguidas"}.
        </p>
      ) : (
        <ol className="entradas">
          {alarmas.map((a) => {
            const abierta = a.fin == null;
            const sensores = a.sensores.split(", ");
            return (
              <li key={a.id} className={abierta ? "abierta" : ""}>
                <time dateTime={a.inicio.replace(" ", "T")}>
                  <span className="dia">{fechaDia(a.inicio).slice(0, 5)}</span>
                  <span className="hh">{hora(a.inicio).slice(0, 5)}</span>
                </time>
                <button onClick={() => onElegir(sensores[0])} aria-label={`${TIPOS[a.tipo_sugerido] ?? "Evento"}: abrir el sensor ${sensores[0]}`}>
                  <span className="que">{TIPOS[a.tipo_sugerido] ?? "Evento sin clasificar"}</span>
                  <span className="cuanto">{duracion(a)}</span>
                  <span className="donde">{sensores.length === 1 ? `Sensor ${sensores[0]}` : `Sensores ${a.sensores}`}</span>
                </button>
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}
