import { useEffect, useRef, useState } from "react";
import Menu, { Icono } from "./Menu.jsx";

// Estructura de cada página (estilo Velzon, variante "default"): menú a la izquierda, barra de
// arriba con las alertas sin atender y quién tiene la sesión, la barra con el título de la página y
// dónde está, el contenido y el pie. En pantallas angostas el menú queda escondido y lo abre el botón
// de la barra; se cierra al elegir una vista, con Escape o tocando fuera, y mientras está abierto el
// foco no sale de él.

const TITULOS = { general: "Toda la red", sensor: "Por sensor", alertas: "Alertas", usuarios: "Usuarios", cuenta: "Mi cuenta" };

function MenuUsuario({ sesion, onSalir, vista }) {
  const [abierto, setAbierto] = useState(false);
  const caja = useRef(null);
  useEffect(() => {
    if (!abierto) return undefined;
    const fuera = (e) => { if (!caja.current?.contains(e.target)) setAbierto(false); };
    const tecla = (e) => { if (e.key === "Escape") { setAbierto(false); caja.current?.querySelector("button")?.focus(); } };
    document.addEventListener("mousedown", fuera);
    document.addEventListener("keydown", tecla);
    return () => { document.removeEventListener("mousedown", fuera); document.removeEventListener("keydown", tecla); };
  }, [abierto]);
  useEffect(() => { setAbierto(false); }, [vista]);
  if (!sesion.inicio_sesion) return <span className="nota">Sin inicio de sesión (INICIO_SESION=no)</span>;
  const u = sesion.usuario;
  return (
    <div className="usuario-barra" ref={caja}>
      <button className="usuario-boton" aria-expanded={abierto} aria-controls="menu-usuario" onClick={() => setAbierto(!abierto)}>
        <span className="inicial" aria-hidden="true">{u.nombre.trim()[0]?.toUpperCase()}</span>
        <span className="usuario-texto"><b>{u.nombre}</b><small>{u.rol_nombre}</small></span>
        <Icono nombre="abajo" tam={16} />
      </button>
      {abierto && (
        <div id="menu-usuario" className="usuario-desplegable">
          <p className="saludo">Hola, {u.nombre.split(" ")[0]}</p>
          <a href="#/cuenta" aria-current={vista === "cuenta" ? "page" : undefined}><Icono nombre="cuenta" tam={18} />Mi cuenta</a>
          <button onClick={onSalir}><Icono nombre="salir" tam={18} />Salir</button>
        </div>
      )}
    </div>
  );
}

export default function Estructura({ vista, sensor, sensores, norma, desactualizado, sesion, onSalir, sinAtender = 0,
                                     pie, children }) {
  const [abierto, setAbierto] = useState(false);
  const boton = useRef(null);
  const nav = useRef(null);
  const primero = useRef(null);
  const admin = sesion.permisos.gestionar_usuarios && sesion.inicio_sesion;

  // al cambiar de vista (o de sensor) el menú del teléfono se cierra solo
  useEffect(() => {
    const cerrar = () => setAbierto(false);
    window.addEventListener("hashchange", cerrar);
    return () => window.removeEventListener("hashchange", cerrar);
  }, []);
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

  const titulo = vista === "sensor" && sensor ? `Sensor ${sensor}` : TITULOS[vista] ?? "";
  return (
    <div className="app">
      <Menu vista={vista} sensor={sensor} sensores={sensores} norma={norma} desactualizado={desactualizado}
            admin={admin} sinAtender={sinAtender} abierto={abierto} navRef={nav} primeroRef={primero}
            onCerrar={() => { setAbierto(false); boton.current?.focus(); }} />
      {abierto && <button className="menu-fondo" tabIndex={-1} aria-hidden="true" onClick={() => setAbierto(false)} />}

      <div className="pagina">
        <header className="barra-superior">
          <button ref={boton} className="boton-menu abrir" aria-expanded={abierto} aria-controls="menu-principal"
                  onClick={() => setAbierto(true)}>
            <Icono nombre="menu" tam={22} /><span className="solo-lector">Abrir el menú</span>
          </button>
          <a href="#/general" className="barra-marca">ASADA La Lucha</a>
          <div className="barra-derecha">
            <a href="#/alertas" className="campana"
               aria-label={sinAtender ? `Alertas: ${sinAtender} sin atender` : "Alertas: ninguna sin atender"}>
              <Icono nombre="alertas" tam={22} />
              {sinAtender > 0 && <span className="insignia" aria-hidden="true">{sinAtender > 99 ? "99+" : sinAtender}</span>}
            </a>
            <MenuUsuario sesion={sesion} onSalir={onSalir} vista={vista} />
          </div>
        </header>

        <div className="titulo-pagina">
          <h1>{titulo}</h1>
          <nav aria-label="Ubicación" className="migas">
            <ol>
              <li><a href="#/general">ASADA La Lucha</a></li>
              {vista === "sensor" && <li><a href={`#/sensor/${sensor ?? ""}`}>Por sensor</a></li>}
              <li aria-current="page">{vista === "sensor" ? sensor : titulo}</li>
            </ol>
          </nav>
        </div>

        <main className="contenido">{children}</main>
        <footer className="pie-pagina">{pie}</footer>
      </div>
    </div>
  );
}
