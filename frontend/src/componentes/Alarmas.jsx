import { fechaCorta, TIPOS } from "../formato.js";

// "12 sep, 20:00 (1 h)" · "5 sep, 11:00 a 16:00 (6 h)" · "5 sep, 20:00 a 6 sep, 03:00 (8 h)"
function periodo(a) {
  const ini = fechaCorta(a.inicio);
  if (a.fin == null) return `Desde ${ini} (${a.horas} h)`;
  if (a.horas === 1) return `${ini} (1 h)`;
  const mismoDia = a.inicio.slice(0, 10) === a.fin.slice(0, 10);
  const fin = mismoDia ? fechaCorta(a.fin).split(", ")[1] : fechaCorta(a.fin);
  return `${ini} a ${fin} (${a.horas} h)`;
}

export default function Alarmas({ alarmas, onElegir }) {
  return (
    <section className="panel" aria-label="Alarmas">
      <h2>Alarmas</h2>
      {!alarmas?.length ? (
        <p className="vacio">Sin alarmas por ahora. Aparecen aquí cuando un sensor supera el umbral del detector durante 3 horas seguidas.</p>
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
