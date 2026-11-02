import { fechaHora, hora, TIPOS } from "../formato.js";

// "12/09/2026 20:00:00 (1 h)" · "05/09/2026 11:00:00 a 16:00:00 (6 h)"
// · "05/09/2026 20:00:00 a 06/09/2026 03:00:00 (8 h)"
function periodo(a) {
  const ini = fechaHora(a.inicio);
  if (a.fin == null) return `Desde ${ini} (${a.horas} h)`;
  if (a.horas === 1) return `${ini} (1 h)`;
  const mismoDia = a.inicio.slice(0, 10) === a.fin.slice(0, 10);
  const fin = mismoDia ? hora(a.fin) : fechaHora(a.fin);
  return `${ini} a ${fin} (${a.horas} h)`;
}

export default function Alarmas({ alarmas, confirmarH, onElegir }) {
  return (
    <section className="panel" aria-label="Alarmas">
      <h2>Alarmas</h2>
      {!alarmas?.length ? (
        <p className="vacio">Sin alarmas por ahora. Aparecen aquí cuando un sensor supera el umbral del detector durante {confirmarH ?? 2} horas seguidas.</p>
      ) : (
        <div className="alarmas">
          {alarmas.map((a) => {
            const abierta = a.fin == null;
            const sensores = a.sensores.split(", ");
            return (
              <button key={a.id} className={`alarma${abierta ? " abierta" : ""}`} onClick={() => onElegir(sensores[0])}
                      title={`Ver el sensor ${sensores[0]}`}>
                <div className="titulo">
                  <span>{TIPOS[a.tipo_sugerido] ?? "Evento sin clasificar"}</span>
                  {abierta && <span className="en-curso">en curso</span>}
                </div>
                <div className="cuando">{periodo(a)}</div>
                <div className="donde">
                  {sensores.length === 1 ? `Sensor ${sensores[0]}` : `${sensores.length} sensores: ${a.sensores}`}
                </div>
              </button>
            );
          })}
        </div>
      )}
    </section>
  );
}
