import { NIVELES } from "../estado.js";

// Alertas activas ordenadas por severidad (crítica primero) y antelación (RF-003.2 c).
const ANTELACION = { 0: "Ahora", 24: "En 24 h", 48: "En 48 h" };

// El contador toma el color de la más grave: rojo solo si hay una crítica; las "habituales" no son
// eventos nuevos y van en gris. El enlace de abajo es otra cosa: las alertas registradas que alguien
// tiene que atender y cerrar (el mismo número que la insignia de "Alertas" en el menú).
export default function AlertasActivas({ alertas, onAbrir, sinAtender = 0, enAtencion = 0, desactualizado }) {
  const peor = alertas[0]?.nivel ?? "cero";
  const atender = [sinAtender > 0 && `${sinAtender} sin atender`, enAtencion > 0 && `${enAtencion} en atención`]
    .filter(Boolean).join(" y ");
  return (
    <section className="panel alertas-activas" aria-label="Alertas activas">
      <div className="panel-cabeza">
        <h2>Alertas activas</h2>
        <span className={`contador nivel-${peor}`} aria-label={`${alertas.length} activas ahora`}>{alertas.length}</span>
      </div>
      {desactualizado && <p className="mensaje info">{desactualizado}: la lista puede no estar al día.</p>}
      {atender && (
        <a className="ir-gestion" href="#/alertas">Ver el registro de alertas ({atender})</a>
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
