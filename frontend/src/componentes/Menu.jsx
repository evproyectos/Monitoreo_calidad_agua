import { useEffect, useRef, useState } from "react";
import { NIVELES, nivelSensor } from "../estado.js";
import { Marca } from "./InicioSesion.jsx";
import { ordenRed } from "./RedSensores.jsx";

// Menú de la izquierda: las vistas (Toda la red, Por sensor con sus puntos de medición y el estado
// de cada uno, Alertas con cuántas faltan por atender y, para el administrador, Usuarios) y abajo
// quién tiene la sesión, Mi cuenta y Salir. En pantallas angostas queda escondido y lo abre el
// botón de la barra de arriba; se cierra al elegir una vista, con Escape o tocando fuera.

const ICONOS = {
  red: <><rect x="3" y="3" width="7" height="7" rx="1.5" /><rect x="14" y="3" width="7" height="7" rx="1.5" /><rect x="3" y="14" width="7" height="7" rx="1.5" /><rect x="14" y="14" width="7" height="7" rx="1.5" /></>,
  sensor: <><path d="M12 21s-6.5-5.6-6.5-11a6.5 6.5 0 0 1 13 0c0 5.4-6.5 11-6.5 11z" /><circle cx="12" cy="10" r="2.4" /></>,
  alertas: <><path d="M6 16V11a6 6 0 0 1 12 0v5l1.5 2h-15z" /><path d="M10 20.5a2.2 2.2 0 0 0 4 0" /></>,
  usuarios: <><circle cx="9" cy="8.5" r="3.2" /><path d="M3 19.5c.6-3.3 3-5 6-5s5.4 1.7 6 5" /><path d="M15.5 5.6a3 3 0 0 1 0 5.8" /><path d="M17.5 14.8c1.9.6 3.1 2.2 3.5 4.7" /></>,
  salir: <><path d="M14 4h4a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-4" /><path d="M10 16l-4-4 4-4" /><path d="M6 12h10" /></>,
  menu: <><path d="M4 7h16" /><path d="M4 12h16" /><path d="M4 17h16" /></>,
  cerrar: <><path d="M6 6l12 12" /><path d="M18 6L6 18" /></>,
};

function Icono({ nombre }) {
  return (
    <svg className="icono" viewBox="0 0 24 24" width="20" height="20" aria-hidden="true" fill="none"
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

export default function Menu({ vista, sensor, sensores = [], norma, desactualizado, sesion, onSalir, sinAtender = 0 }) {
  const [abierto, setAbierto] = useState(false);
  const boton = useRef(null);
  const primero = useRef(null);
  const u = sesion.usuario;
  const admin = sesion.permisos.gestionar_usuarios && sesion.inicio_sesion;

  // al cambiar de vista (o de sensor) el menú del teléfono se cierra solo
  useEffect(() => {
    const cerrar = () => setAbierto(false);
    window.addEventListener("hashchange", cerrar);
    return () => window.removeEventListener("hashchange", cerrar);
  }, []);
  // abierto: Escape lo cierra, el foco entra al menú y no sale de él con Tab (lo de atrás queda
  // tapado), la página de atrás no se desplaza, y si la ventana se agranda a escritorio se cierra
  const nav = useRef(null);
  useEffect(() => {
    if (!abierto) return undefined;
    const tecla = (e) => {
      if (e.key === "Escape") { setAbierto(false); boton.current?.focus(); return; }
      if (e.key !== "Tab" || !nav.current) return;
      const f = [...nav.current.querySelectorAll("a[href], button:not([disabled])")];
      if (!f.length) return;
      if (e.shiftKey && document.activeElement === f[0]) { e.preventDefault(); f.at(-1).focus(); }
      else if (!e.shiftKey && document.activeElement === f.at(-1)) { e.preventDefault(); f[0].focus(); }
    };
    const escritorio = window.matchMedia("(min-width: 1100px)");
    const alAgrandar = () => { if (escritorio.matches) setAbierto(false); };
    window.addEventListener("keydown", tecla);
    escritorio.addEventListener("change", alAgrandar);
    document.body.classList.add("menu-abierto");
    primero.current?.focus();
    return () => {
      window.removeEventListener("keydown", tecla);
      escritorio.removeEventListener("change", alAgrandar);
      document.body.classList.remove("menu-abierto");
    };
  }, [abierto]);

  const actual = (v) => (vista === v ? "page" : undefined);
  const puntos = ordenRed(sensores);
  return (
    <>
      <header className="barra-movil">
        <button ref={boton} className="boton-menu" aria-expanded={abierto} aria-controls="menu-principal"
                onClick={() => setAbierto(true)}>
          <Icono nombre="menu" /><span className="solo-lector">Abrir el menú</span>
        </button>
        <Marca />
        {sinAtender > 0 && (
          <a href="#/alertas" className="insignia insignia-movil" aria-label={`${sinAtender} alertas sin atender`}>
            {sinAtender}
          </a>
        )}
      </header>

      {abierto && <button className="menu-fondo" tabIndex={-1} aria-hidden="true" onClick={() => setAbierto(false)} />}

      <nav ref={nav} id="menu-principal" className={`menu${abierto ? " abierto" : ""}`} aria-label="Menú principal">
        <div className="menu-cabeza">
          <Marca />
          <button className="boton-menu cerrar" onClick={() => { setAbierto(false); boton.current?.focus(); }}>
            <Icono nombre="cerrar" /><span className="solo-lector">Cerrar el menú</span>
          </button>
        </div>

        <ul className="menu-vistas">
          <li>
            <a ref={primero} href="#/general" aria-current={actual("general")}>
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
          {admin && (
            <li>
              <a href="#/usuarios" aria-current={actual("usuarios")}><Icono nombre="usuarios" />Usuarios</a>
            </li>
          )}
        </ul>

        <div className="menu-pie">
          {sesion.inicio_sesion ? (
            <>
              <a href="#/cuenta" className="persona" aria-current={actual("cuenta")}>
                <span className="inicial" aria-hidden="true">{u.nombre.trim()[0]?.toUpperCase()}</span>
                <span><b>{u.nombre}</b><small>{u.rol_nombre} · Mi cuenta</small></span>
              </a>
              <button className="salir" onClick={onSalir}><Icono nombre="salir" />Salir</button>
            </>
          ) : <span className="nota">Sin inicio de sesión (INICIO_SESION=no)</span>}
        </div>
      </nav>
    </>
  );
}
