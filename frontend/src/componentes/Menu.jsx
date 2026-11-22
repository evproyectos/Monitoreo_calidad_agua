import { NIVELES, nivelSensor } from "../estado.js";
import { Marca } from "./InicioSesion.jsx";
import { ordenRed } from "./RedSensores.jsx";

// Menú de la izquierda (estilo Velzon, variante "default"): el logo, las vistas (Toda la red, Por
// sensor con sus puntos de medición y el estado de cada uno, Alertas con cuántas faltan por atender
// y, para el administrador, Usuarios). Quién tiene la sesión está en la barra de arriba (Barra.jsx).
// En pantallas angostas lo abre el botón de esa barra (Estructura.jsx).

export const ICONOS = {
  red: <><rect x="3" y="3" width="7" height="7" rx="1.5" /><rect x="14" y="3" width="7" height="7" rx="1.5" /><rect x="3" y="14" width="7" height="7" rx="1.5" /><rect x="14" y="14" width="7" height="7" rx="1.5" /></>,
  sensor: <><path d="M12 21s-6.5-5.6-6.5-11a6.5 6.5 0 0 1 13 0c0 5.4-6.5 11-6.5 11z" /><circle cx="12" cy="10" r="2.4" /></>,
  alertas: <><path d="M6 16V11a6 6 0 0 1 12 0v5l1.5 2h-15z" /><path d="M10 20.5a2.2 2.2 0 0 0 4 0" /></>,
  usuarios: <><circle cx="9" cy="8.5" r="3.2" /><path d="M3 19.5c.6-3.3 3-5 6-5s5.4 1.7 6 5" /><path d="M15.5 5.6a3 3 0 0 1 0 5.8" /><path d="M17.5 14.8c1.9.6 3.1 2.2 3.5 4.7" /></>,
  cuenta: <><circle cx="12" cy="8" r="3.6" /><path d="M5 20c.8-3.6 3.6-5.6 7-5.6s6.2 2 7 5.6" /></>,
  salir: <><path d="M14 4h4a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-4" /><path d="M10 16l-4-4 4-4" /><path d="M6 12h10" /></>,
  menu: <><path d="M4 7h16" /><path d="M4 12h16" /><path d="M4 17h16" /></>,
  cerrar: <><path d="M6 6l12 12" /><path d="M18 6L6 18" /></>,
  abajo: <path d="M7 10l5 5 5-5" />,
  reloj: <><circle cx="12" cy="12" r="8.5" /><path d="M12 7.5V12l3 2" /></>,
  listo: <><circle cx="12" cy="12" r="8.5" /><path d="M8.2 12.3l2.5 2.5 5-5.3" /></>,
  campo: <><path d="M9 3h6" /><path d="M10 3v5.2L5.2 17a2.4 2.4 0 0 0 2.1 3.5h9.4a2.4 2.4 0 0 0 2.1-3.5L14 8.2V3" /><path d="M7.5 14h9" /></>,
  atras: <path d="M14.5 6l-6 6 6 6" />,
};

export function Icono({ nombre, tam = 20 }) {
  return (
    <svg className="icono" viewBox="0 0 24 24" width={tam} height={tam} aria-hidden="true" fill="none"
         stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      {ICONOS[nombre]}
    </svg>
  );
}

const ETIQUETA = { rojo: "Crítica", amarillo: "Predictiva", habitual: "Habitual", gris: "Sin dato" };

function PuntoSensor({ s, nivel, actual }) {
  return (
    <li>
      <a href={`#/sensor/${s.nodo}`} className={`punto-menu nivel-${nivel}`}
         aria-current={actual ? "page" : undefined}>
        <i aria-hidden="true" />
        <span className="nodo">{s.nodo}</span>
        {/* verde no lleva texto (es lo normal); lo demás, para no depender solo del color */}
        {nivel === "verde" ? <span className="solo-lector">: {NIVELES.verde.texto}</span>
          : <span className="estado-punto">{ETIQUETA[nivel]}</span>}
      </a>
    </li>
  );
}

export default function Menu({ vista, sensor, sensores = [], norma, desactualizado, admin, sinAtender = 0,
                               abierto, onCerrar, navRef, primeroRef }) {
  const actual = (v) => (vista === v ? "page" : undefined);
  const puntos = ordenRed(sensores);
  return (
    <nav ref={navRef} id="menu-principal" className={`menu${abierto ? " abierto" : ""}`} aria-label="Menú principal">
      <div className="menu-cabeza">
        <a href="#/general" className="menu-marca" aria-label="ASADA La Lucha: Toda la red"><Marca /></a>
        <button className="boton-menu cerrar" onClick={onCerrar}>
          <Icono nombre="cerrar" /><span className="solo-lector">Cerrar el menú</span>
        </button>
      </div>

      <div className="menu-cuerpo">
        <p className="menu-titulo" aria-hidden="true">Menú</p>
        <ul className="menu-vistas">
          <li>
            <a ref={primeroRef} href="#/general" aria-current={actual("general")}>
              <Icono nombre="red" />Toda la red
            </a>
          </li>
          <li>
            <a href={`#/sensor/${sensor ?? ""}`} aria-current={vista === "sensor" ? "true" : undefined}>
              <Icono nombre="sensor" />Por sensor
            </a>
            {puntos.length > 0 && (
              <ul className="menu-puntos" aria-label="Puntos de medición">
                {puntos.map((s) => (
                  <PuntoSensor key={s.nodo} s={s} nivel={desactualizado ? "gris" : nivelSensor(s, norma)}
                               actual={vista === "sensor" && s.nodo === sensor} />
                ))}
              </ul>
            )}
          </li>
          <li>
            <a href="#/alertas" aria-current={actual("alertas")}>
              <Icono nombre="alertas" />Alertas
              {sinAtender > 0 && <span className="insignia" aria-label={`${sinAtender} sin atender`}>{sinAtender}</span>}
            </a>
          </li>
        </ul>
        {admin && (
          <>
            <p className="menu-titulo" aria-hidden="true">Administración</p>
            <ul className="menu-vistas">
              <li>
                <a href="#/usuarios" aria-current={actual("usuarios")}><Icono nombre="usuarios" />Usuarios</a>
              </li>
            </ul>
          </>
        )}
      </div>
    </nav>
  );
}
