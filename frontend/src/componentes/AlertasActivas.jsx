import { NIVELES } from "../estado.js";

// Alertas activas ordenadas por severidad (crítica primero) y antelación (RF-003.2 c).
const ANTELACION = { 0: "Ahora", 24: "En 24 h", 48: "En 48 h" };

export default function AlertasActivas({ alertas, onAbrir, pendientes }) {
  return (
    <section className="panel alertas-activas" aria-label="Alertas activas">
      <div className="panel-cabeza">
        <h2>Alertas activas</h2>
        <span className={`contador${alertas.length ? "" : " cero"}`}>{alertas.length}</span>
      </div>
      {pendientes > 0 && (
        <a className="ir-gestion" href="#/alertas">
          {pendientes === 1 ? "1 alerta por atender" : `${pendientes} alertas por atender`} →
        </a>
      )}
      {!alertas.length ? (
        <p className="vacio">
          No hay alertas. Si un sensor sale de norma o los modelos anticipan un evento para las próximas
          24 o 48 h, aparece aquí.
        </p>
      ) : (
        <ul className="lista-alertas">
          {alertas.map((a, i) => {
            const contenido = (
              <>
                <span className="cuando">{ANTELACION[a.antelacion_h] ?? `En ${a.antelacion_h} h`}</span>
                <span className="titulo">{a.titulo}</span>
                <span className="detalle">{a.detalle}</span>
                <span className="tipo">{NIVELES[a.nivel].texto}</span>
              </>
            );
            return (
              <li key={i} className={`nivel-${a.nivel}`}>
                {a.sensor ? (
                  <button onClick={() => onAbrir(a.sensor)} aria-label={`${a.titulo}: abrir el sensor ${a.sensor}`}>{contenido}</button>
                ) : <div>{contenido}</div>}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
