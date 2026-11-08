import { useState } from "react";
import { pedir } from "../api.js";

export function Marca() {
  return (
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
  );
}

// Inicio de sesión con correo y contraseña (CU-00). Si algo no coincide, el mensaje es el mismo
// para el correo y la contraseña: no dice cuál de los dos falló.
export default function InicioSesion({ onEntrar, vencida, sinServicio, onReintentar }) {
  const [correo, setCorreo] = useState("");
  const [contrasena, setContrasena] = useState("");
  const [ver, setVer] = useState(false);
  const [error, setError] = useState(null);
  const [enviando, setEnviando] = useState(false);

  const enviar = async (e) => {
    e.preventDefault();
    if (!correo.trim() || !contrasena) {
      setError("Escribe tu correo y tu contraseña.");
      return;
    }
    setEnviando(true);
    setError(null);
    try {
      onEntrar(await pedir("/api/sesion", { metodo: "POST", cuerpo: { correo: correo.trim(), contrasena } }));
    } catch (err) {
      setError(err.status ? err.message : "No hay conexión con el servicio de monitoreo. Intenta de nuevo en un momento.");
      setContrasena("");
    } finally {
      setEnviando(false);
    }
  };

  return (
    <div className="pantalla-sesion">
      <form className="tarjeta-sesion" onSubmit={enviar} noValidate>
        <Marca />
        <h1>Iniciar sesión</h1>
        {vencida && !error && <p className="mensaje info" role="status">Tu sesión terminó. Vuelve a entrar.</p>}
        {sinServicio && !error && (
          <p className="mensaje error" role="alert">
            No hay conexión con el servicio de monitoreo. <button type="button" className="enlace" onClick={onReintentar}>Reintentar</button>
          </p>
        )}
        {error && <p className="mensaje error" role="alert">{error}</p>}

        <label className="campo">
          <span>Correo</span>
          <input type="email" autoComplete="username" inputMode="email" value={correo} autoFocus
                 onChange={(e) => setCorreo(e.target.value)} />
        </label>
        <label className="campo">
          <span>Contraseña</span>
          <span className="con-boton">
            <input type={ver ? "text" : "password"} autoComplete="current-password" value={contrasena}
                   onChange={(e) => setContrasena(e.target.value)} />
            <button type="button" className="boton-texto" onClick={() => setVer(!ver)}
                    aria-pressed={ver}>{ver ? "Ocultar" : "Mostrar"}</button>
          </span>
        </label>
        <button className="boton primario ancho" disabled={enviando}>{enviando ? "Entrando…" : "Entrar"}</button>
        <p className="nota">¿Olvidaste tu contraseña? Pídele al administrador de la ASADA que la restablezca.</p>
      </form>
    </div>
  );
}
