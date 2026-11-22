import { fechaHora } from "../formato.js";
import { NIVELES } from "../estado.js";

// Arriba del contenido: el estado de toda la red en una línea con su semáforo (verde, amarillo o
// rojo) y la hora de los últimos datos. Las vistas y la sesión están en el menú de la izquierda
// (Menu.jsx).
export default function Encabezado({ resumen, hora }) {
  return (
    <div className={`resumen-red nivel-${resumen.nivel}`} role="status">
      <span className="semaforo" aria-hidden="true"><i /><i /><i /></span>
      <div>
        <span className="nivel">{NIVELES[resumen.nivel].texto}</span>
        <h2>{resumen.texto}</h2>
      </div>
      {hora && <span className="hora">Actualizado: {fechaHora(hora)}</span>}
    </div>
  );
}
