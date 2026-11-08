import { fechaHora } from "../formato.js";
import { NIVELES } from "../estado.js";
import { Marca } from "./InicioSesion.jsx";

// Marca del acueducto, las vistas (Alertas, con cuántas faltan por atender; Usuarios solo para el
// administrador), quién tiene la sesión y, debajo, el estado de toda la red en una línea con su
// semáforo (verde, amarillo o rojo).
export default function Encabezado({ resumen, hora, vista, sensor, sesion, onSalir, sinAtender = 0 }) {
  const u = sesion.usuario;
  return (
    <>
      <header className="encabezado">
        <Marca />
        <nav className="vistas" aria-label="Vistas">
          <a href="#/general" aria-current={vista === "general" ? "page" : undefined}>Toda la red</a>
          <a href={`#/sensor/${sensor ?? ""}`} aria-current={vista === "sensor" ? "page" : undefined}>
            {sensor ? `Sensor ${sensor}` : "Por sensor"}
          </a>
          <a href="#/alertas" aria-current={vista === "alertas" ? "page" : undefined}>
            Alertas{sinAtender > 0 && <span className="insignia" aria-label={`${sinAtender} sin atender`}>{sinAtender}</span>}
          </a>
          {sesion.permisos.gestionar_usuarios && sesion.inicio_sesion && (
            <a href="#/usuarios" aria-current={vista === "usuarios" ? "page" : undefined}>Usuarios</a>
          )}
        </nav>
        <div className="quien">
          {sesion.inicio_sesion ? (
            <>
              <a href="#/cuenta" className="persona" aria-current={vista === "cuenta" ? "page" : undefined}
                 title="Mi cuenta">
                <span className="inicial" aria-hidden="true">{u.nombre.trim()[0]?.toUpperCase()}</span>
                <span><b>{u.nombre}</b><small>{u.rol_nombre}</small></span>
              </a>
              <button className="boton chico" onClick={onSalir}>Salir</button>
            </>
          ) : <span className="nota">Sin inicio de sesión (INICIO_SESION=no)</span>}
        </div>
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
