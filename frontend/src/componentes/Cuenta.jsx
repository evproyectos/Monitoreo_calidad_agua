import { useState } from "react";
import { pedir } from "../api.js";

// Mi cuenta, como la página de ajustes de perfil de Velzon: portada, la tarjeta de la persona y, a
// la derecha, pestañas con sus datos y el cambio de contraseña. Con `obligatoria`, es solo el
// formulario que aparece al entrar con una contraseña temporal: hasta cambiarla no se ve el tablero.

const PUEDE = {
  junta: "Ve el tablero y el registro de alertas.",
  operador: "Ve el tablero y atiende las alertas: las toma, anota lo que hizo en campo y las cierra.",
  administrador: "Todo lo del operador técnico, y además crea y administra los usuarios y elige quién recibe las alertas por correo.",
};
export default function Cuenta({ usuario, obligatoria, onListo, onSalir }) {
  const [actual, setActual] = useState("");
  const [nueva, setNueva] = useState("");
  const [repetida, setRepetida] = useState("");
  const [mensaje, setMensaje] = useState(null);
  const [enviando, setEnviando] = useState(false);
  const [pestana, setPestana] = useState("datos");

  const enviar = async (e) => {
    e.preventDefault();
    if (nueva.length < 10) return setMensaje({ error: "La contraseña nueva debe tener al menos 10 caracteres." });
    if (nueva !== repetida) return setMensaje({ error: "Las dos contraseñas nuevas no coinciden." });
    setEnviando(true);
    try {
      const datos = await pedir("/api/sesion/contrasena", { metodo: "POST", cuerpo: { actual, nueva } });
      setActual(""); setNueva(""); setRepetida("");
      setMensaje({ ok: "Contraseña cambiada." });
      onListo?.(datos);
    } catch (err) {
      setMensaje({ error: err.message });
    } finally {
      setEnviando(false);
    }
  };

  const formulario = (
    <form className="formulario" onSubmit={enviar} noValidate>
      {obligatoria ? (
        <>
          <h1>Cambia tu contraseña temporal</h1>
          <p className="nota">
            Hola, {usuario.nombre}. El administrador te dio una contraseña temporal; elige una tuya para
            seguir. Debe tener al menos 10 caracteres.
          </p>
        </>
      ) : (
        <p className="nota">Al menos 10 caracteres. Una frase corta es más fácil de recordar y difícil de adivinar.</p>
      )}
      {mensaje?.error && <p className="mensaje error" role="alert">{mensaje.error}</p>}
      {mensaje?.ok && <p className="mensaje ok" role="status">{mensaje.ok}</p>}
      <label className="campo">
        <span>{obligatoria ? "Contraseña temporal" : "Contraseña actual"}</span>
        <input type="password" autoComplete="current-password" value={actual} onChange={(e) => setActual(e.target.value)} />
      </label>
      <label className="campo">
        <span>Contraseña nueva</span>
        <input type="password" autoComplete="new-password" value={nueva} onChange={(e) => setNueva(e.target.value)} />
      </label>
      <label className="campo">
        <span>Repite la contraseña nueva</span>
        <input type="password" autoComplete="new-password" value={repetida} onChange={(e) => setRepetida(e.target.value)} />
      </label>
      <div className="acciones">
        <button className="boton primario" disabled={enviando}>{enviando ? "Guardando…" : "Cambiar contraseña"}</button>
        {obligatoria && <button type="button" className="boton" onClick={onSalir}>Salir</button>}
      </div>
    </form>
  );

  if (obligatoria) return formulario;
  const pestanas = [["datos", "Mis datos"], ["contrasena", "Cambiar contraseña"]];
  const teclas = (e) => {
    const k = pestanas.findIndex(([v]) => v === pestana);
    const otra = e.key === "ArrowRight" ? k + 1 : e.key === "ArrowLeft" ? k - 1 : null;
    if (otra == null) return;
    const [v] = pestanas[(otra + pestanas.length) % pestanas.length];
    setPestana(v);
    document.getElementById(`pestana-${v}`)?.focus();
  };
  return (
    <div className="perfil">
      <div className="perfil-portada" aria-hidden="true" />
      <div className="perfil-cuerpo">
        <section className="panel perfil-tarjeta" aria-label="Tu perfil">
          <span className="perfil-inicial" aria-hidden="true">{usuario.nombre.trim()[0]?.toUpperCase()}</span>
          <h2>{usuario.nombre}</h2>
          <p className="nota">{usuario.rol_nombre}</p>
          <p className="perfil-puede">{PUEDE[usuario.rol] ?? ""}</p>
        </section>

        <section className="panel perfil-ajustes" aria-label="Mi cuenta">
          <div className="pestanas" role="tablist" aria-label="Mi cuenta" onKeyDown={teclas}>
            {pestanas.map(([v, texto]) => (
              <button key={v} id={`pestana-${v}`} role="tab" aria-selected={pestana === v} aria-controls={`panel-${v}`}
                      tabIndex={pestana === v ? 0 : -1} onClick={() => setPestana(v)}>{texto}</button>
            ))}
          </div>
          {pestana === "datos" && (
            <div id="panel-datos" role="tabpanel" aria-labelledby="pestana-datos" className="pestana-cuerpo">
              <dl className="datos-perfil">
                <div><dt>Nombre</dt><dd>{usuario.nombre}</dd></div>
                <div><dt>Correo</dt><dd>{usuario.correo}</dd></div>
                <div><dt>Rol</dt><dd>{usuario.rol_nombre}</dd></div>
              </dl>
              <p className="nota">Para cambiar tu nombre, correo o rol, pídeselo al administrador de la ASADA.</p>
            </div>
          )}
          {pestana === "contrasena" && (
            <div id="panel-contrasena" role="tabpanel" aria-labelledby="pestana-contrasena" className="pestana-cuerpo">
              {formulario}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
