import { fechaHora } from "../formato.js";
import { NIVELES } from "../estado.js";

// Marca del acueducto, las dos vistas y, debajo, el estado de toda la red en una línea con su
// semáforo (verde, amarillo o rojo).
export default function Encabezado({ resumen, hora, vista, sensor }) {
  return (
    <>
      <header className="encabezado">
        <div className="marca">
          <svg viewBox="0 0 32 32" width="34" height="34" aria-hidden="true" className="gota">
            <path d="M16 3c5.5 7 9 12 9 16.5A9 9 0 0 1 7 19.5C7 15 10.5 10 16 3z" />
            <path d="M11.5 20.5a4.5 4.5 0 0 0 4.5 4.5" fill="none" strokeWidth="2" strokeLinecap="round" />
          </svg>
          <div>
            <strong>ASADA La Lucha</strong>
            <span>Alertas tempranas de calidad del agua</span>
          </div>
        </div>
        <nav className="vistas" aria-label="Vistas">
          <a href="#/general" aria-current={vista === "general" ? "page" : undefined}>Toda la red</a>
          <a href={`#/sensor/${sensor ?? ""}`} aria-current={vista === "sensor" ? "page" : undefined}>
            {sensor ? `Sensor ${sensor}` : "Por sensor"}
          </a>
        </nav>
      </header>

      <div className={`resumen-red nivel-${resumen.nivel}`} role="status">
        <span className="semaforo" aria-hidden="true"><i /><i /><i /></span>
        <div>
          <span className="nivel">{NIVELES[resumen.nivel].texto}</span>
          <h1>{resumen.texto}</h1>
        </div>
        {hora && <span className="hora">Actualizado: {fechaHora(hora)}</span>}
      </div>
    </>
  );
}
