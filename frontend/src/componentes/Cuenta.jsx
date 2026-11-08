import { useState } from "react";
import { pedir } from "../api.js";

// Cambiar la propia contraseña. Con `obligatoria`, es la pantalla que aparece al entrar con una
// contraseña temporal: hasta cambiarla no se ve el tablero.
export default function Cuenta({ usuario, obligatoria, onListo, onSalir }) {
  const [actual, setActual] = useState("");
  const [nueva, setNueva] = useState("");
  const [repetida, setRepetida] = useState("");
  const [mensaje, setMensaje] = useState(null);
  const [enviando, setEnviando] = useState(false);

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
        <>
          <h2>Cambiar contraseña</h2>
          <p className="nota">Al menos 10 caracteres. Una frase corta es más fácil de recordar y difícil de adivinar.</p>
        </>
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
  return (
    <section className="panel cuenta" aria-label="Mi cuenta">
      <div className="cuenta-datos">
        <h2>Mi cuenta</h2>
        <dl>
          <div><dt>Nombre</dt><dd>{usuario.nombre}</dd></div>
          <div><dt>Correo</dt><dd>{usuario.correo}</dd></div>
          <div><dt>Rol</dt><dd>{usuario.rol_nombre}</dd></div>
        </dl>
      </div>
      {formulario}
    </section>
  );
}
