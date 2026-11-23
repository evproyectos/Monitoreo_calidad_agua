import { NIVELES, nivelSensor } from "../estado.js";
import { Marca } from "./InicioSesion.jsx";
import { ordenRed } from "./RedSensores.jsx";

// Menú de la izquierda (estilo Velzon, variante "default"): el logo; Inicio (la vista sencilla),
// Alertas con cuántas faltan por atender y la Vista detallada (Toda la red y Por sensor, con sus
// puntos de medición y el estado de cada uno, que se despliegan al entrar en ella); para el
// administrador, Usuarios y Lugares. Quién tiene la sesión está en la barra de arriba
// (Estructura.jsx). En pantallas angostas lo abre el botón "Más" de la barra de abajo.

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
  adelante: <path d="M9.5 6l6 6-6 6" />,
  inicio: <path d="M4 11l8-7 8 7v8a1 1 0 0 1-1 1h-4v-6h-6v6H5a1 1 0 0 1-1-1z" />,
  detallada: <><path d="M4 19V5" /><path d="M4 19h16" /><path d="M7 15l4-5 3 3 5-6" /></>,
  ok: <path d="M5 12.5l4.5 4.5L19 7.5" />,
  aviso: <><path d="M12 8v5" /><path d="M12 16.5v.5" /><path d="M10.3 3.9L2.6 17.5A2 2 0 0 0 4.3 20.5h15.4a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z" /></>,
  gota: <path d="M12 3.5s-5 5.8-5 9.5a5 5 0 0 0 10 0c0-3.7-5-9.5-5-9.5z" />,
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
  const detallada = vista === "general" || vista === "sensor";
  const puntos = ordenRed(sensores);
  return (
    <nav ref={navRef} id="menu-principal" className={`menu${abierto ? " abierto" : ""}`} aria-label="Menú principal">
      <div className="menu-cabeza">
        <a href="#/inicio" className="menu-marca" aria-label="ASADA La Lucha: Inicio"><Marca /></a>
        <button className="boton-menu cerrar" onClick={onCerrar}>
          <Icono nombre="cerrar" /><span className="solo-lector">Cerrar el menú</span>
        </button>
      </div>

      <div className="menu-cuerpo">
        <p className="menu-titulo" aria-hidden="true">Menú</p>
        <ul className="menu-vistas">
          <li>
            <a ref={primeroRef} href="#/inicio" aria-current={actual("inicio") ?? (vista === "lugar" ? "true" : undefined)}>
              <Icono nombre="inicio" />Inicio
            </a>
          </li>
          <li>
            <a href="#/alertas" aria-current={actual("alertas")}>
              <Icono nombre="alertas" />Alertas
              {sinAtender > 0 && <span className="insignia" aria-label={`${sinAtender} sin atender`}>{sinAtender}</span>}
            </a>
          </li>
          <li>
            <a href="#/general" aria-current={detallada ? "true" : undefined}>
              <Icono nombre="detallada" />Vista detallada
            </a>
            {detallada && (
              <ul className="menu-sub" aria-label="Vista detallada">
                <li><a href="#/general" aria-current={actual("general")}>Toda la red</a></li>
                <li>
                  <a href={`#/sensor/${sensor ?? ""}`} aria-current={vista === "sensor" ? "true" : undefined}>Por sensor</a>
                  {puntos.length > 0 && (
                    <ul className="menu-puntos" aria-label="Puntos de medición">
                      {puntos.map((s) => (
                        <PuntoSensor key={s.nodo} s={s} nivel={desactualizado ? "gris" : nivelSensor(s, norma)}
                                     actual={vista === "sensor" && s.nodo === sensor} />
                      ))}
                    </ul>
                  )}
                </li>
              </ul>
            )}
          </li>
        </ul>
        {admin && (
          <>
            <p className="menu-titulo" aria-hidden="true">Administración</p>
            <ul className="menu-vistas">
              <li>
                <a href="#/usuarios" aria-current={actual("usuarios")}><Icono nombre="usuarios" />Usuarios</a>
              </li>
              <li>
                <a href="#/lugares" aria-current={actual("lugares")}><Icono nombre="sensor" />Lugares</a>
              </li>
            </ul>
          </>
        )}
      </div>
    </nav>
  );
}
