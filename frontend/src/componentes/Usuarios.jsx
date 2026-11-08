import { useMemo, useState } from "react";
import { pedir, useConsulta } from "../api.js";
import { fechaHora } from "../formato.js";

// Gestión de usuarios, roles y destinatarios de las notificaciones (CU-07), solo para el
// administrador, con la bitácora de accesos y cambios.

const ACCIONES = {
  inicio_sesion: "Inició sesión",
  inicio_fallido: "Intento fallido de inicio de sesión",
  inicio_bloqueado: "Inicio bloqueado por intentos fallidos",
  inicio_cuenta_inactiva: "Intento con cuenta desactivada",
  cierre_sesion: "Cerró sesión",
  usuario_creado: "Creó un usuario",
  usuario_modificado: "Modificó un usuario",
  contrasena_cambiada: "Cambió su contraseña",
};

function detalleLegible(d) {
  if (!d) return "";
  return d.replace("activo=False", "desactivado").replace("activo=True", "activado")
    .replace("notificar_rojo=True", "recibe alertas críticas").replace("notificar_rojo=False", "no recibe alertas críticas")
    .replace("notificar_amarillo=True", "recibe alertas predictivas")
    .replace("notificar_amarillo=False", "no recibe alertas predictivas")
    .replace(/rol=(\w+)/, (_, r) => `rol ${r}`).replace(/nombre=/, "nombre ");
}

function NuevoUsuario({ roles, minimo, onCreado, onCancelar }) {
  const [f, setF] = useState({ nombre: "", correo: "", rol: "operador", contrasena: "" });
  const [error, setError] = useState(null);
  const cambiar = (k) => (e) => setF({ ...f, [k]: e.target.value });

  const enviar = async (e) => {
    e.preventDefault();
    if (!f.nombre.trim() || !f.correo.trim()) return setError("El nombre y el correo son obligatorios.");
    if (f.contrasena.length < minimo) return setError(`La contraseña temporal debe tener al menos ${minimo} caracteres.`);
    try {
      onCreado(await pedir("/api/usuarios", { metodo: "POST", cuerpo: f }));
    } catch (err) {
      setError(err.message);
    }
  };

  return (
    <form className="formulario nuevo-usuario" onSubmit={enviar} noValidate>
      <h3>Nuevo usuario</h3>
      {error && <p className="mensaje error" role="alert">{error}</p>}
      <div className="campos">
        <label className="campo"><span>Nombre</span><input value={f.nombre} onChange={cambiar("nombre")} autoFocus /></label>
        <label className="campo"><span>Correo</span><input type="email" value={f.correo} onChange={cambiar("correo")} /></label>
        <label className="campo">
          <span>Rol</span>
          <select value={f.rol} onChange={cambiar("rol")}>
            {Object.entries(roles).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </label>
        <label className="campo">
          <span>Contraseña temporal</span>
          <input value={f.contrasena} onChange={cambiar("contrasena")} autoComplete="off" />
        </label>
      </div>
      <p className="nota">La persona deberá cambiar la contraseña temporal la primera vez que entre. Dásela en persona o por teléfono.</p>
      <div className="acciones">
        <button className="boton primario">Crear usuario</button>
        <button type="button" className="boton" onClick={onCancelar}>Cancelar</button>
      </div>
    </form>
  );
}

function Restablecer({ usuario, minimo, onListo, onCancelar }) {
  const [clave, setClave] = useState("");
  const [error, setError] = useState(null);
  const enviar = async (e) => {
    e.preventDefault();
    if (clave.length < minimo) return setError(`Al menos ${minimo} caracteres.`);
    try {
      onListo(await pedir(`/api/usuarios/${usuario.id}`, { metodo: "PATCH", cuerpo: { contrasena: clave } }));
    } catch (err) {
      setError(err.message);
    }
  };
  return (
    <form className="restablecer" onSubmit={enviar} noValidate>
      <label className="campo">
        <span>Contraseña temporal nueva para {usuario.nombre}</span>
        <input value={clave} onChange={(e) => setClave(e.target.value)} autoFocus autoComplete="off" />
      </label>
      {error && <p className="mensaje error" role="alert">{error}</p>}
      <div className="acciones">
        <button className="boton primario">Restablecer</button>
        <button type="button" className="boton" onClick={onCancelar}>Cancelar</button>
      </div>
    </form>
  );
}

export default function Usuarios({ yo }) {
  const lista = useConsulta("/api/usuarios", 0);
  const bitacora = useConsulta("/api/bitacora?limite=60", 15000);
  const [filtro, setFiltro] = useState({ texto: "", rol: "", estado: "activos" });
  const [creando, setCreando] = useState(false);
  const [restableciendo, setRestableciendo] = useState(null);
  const [aviso, setAviso] = useState(null);

  const d = lista.datos;
  const visibles = useMemo(() => (d?.usuarios ?? []).filter((u) => {
    const t = filtro.texto.trim().toLowerCase();
    return (!t || u.nombre.toLowerCase().includes(t) || u.correo.includes(t))
      && (!filtro.rol || u.rol === filtro.rol)
      && (filtro.estado === "todos" || (filtro.estado === "activos") === u.activo);
  }), [d, filtro]);

  const listo = (texto) => {
    setAviso({ ok: texto });
    lista.recargar();
    bitacora.recargar();
  };

  const cambiar = async (u, cambios, texto) => {
    try {
      await pedir(`/api/usuarios/${u.id}`, { metodo: "PATCH", cuerpo: cambios });
      listo(texto);
    } catch (err) {
      setAviso({ error: err.message });
    }
  };

  if (!d) return <section className="panel"><p className="vacio">Cargando usuarios…</p></section>;

  return (
    <div className="administracion">
      <section className="panel usuarios" aria-label="Usuarios">
        <div className="panel-cabeza">
          <div>
            <h2>Usuarios</h2>
            <p className="nota">Quién entra al tablero, con qué rol y qué alertas recibe por correo.</p>
          </div>
          {!creando && <button className="boton primario" onClick={() => { setCreando(true); setAviso(null); }}>Agregar usuario</button>}
        </div>

        {aviso?.ok && <p className="mensaje ok" role="status">{aviso.ok}</p>}
        {aviso?.error && <p className="mensaje error" role="alert">{aviso.error}</p>}
        {creando && (
          <NuevoUsuario roles={d.roles} minimo={d.minimo_contrasena} onCancelar={() => setCreando(false)}
                        onCreado={(u) => { setCreando(false); listo(`Usuario creado: ${u.nombre}.`); }} />
        )}

        <div className="filtros">
          <label className="campo"><span>Buscar</span>
            <input value={filtro.texto} placeholder="Nombre o correo" onChange={(e) => setFiltro({ ...filtro, texto: e.target.value })} />
          </label>
          <label className="campo"><span>Rol</span>
            <select value={filtro.rol} onChange={(e) => setFiltro({ ...filtro, rol: e.target.value })}>
              <option value="">Todos</option>
              {Object.entries(d.roles).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </label>
          <label className="campo"><span>Estado</span>
            <select value={filtro.estado} onChange={(e) => setFiltro({ ...filtro, estado: e.target.value })}>
              <option value="activos">Activos</option>
              <option value="inactivos">Desactivados</option>
              <option value="todos">Todos</option>
            </select>
          </label>
        </div>

        <table className="tabla-usuarios">
          <thead>
            <tr>
              <th scope="col">Persona</th>
              <th scope="col">Rol</th>
              <th scope="col">Recibe por correo</th>
              <th scope="col">Último acceso</th>
              <th scope="col"><span className="solo-lector">Acciones</span></th>
            </tr>
          </thead>
          <tbody>
            {visibles.map((u) => (
              <tr key={u.id} className={u.activo ? "" : "inactivo"}>
                <td data-etq="Persona">
                  <b>{u.nombre}{u.id === yo.id && <small className="tu"> (tú)</small>}</b>
                  <span>{u.correo}</span>
                  {!u.activo && <span className="pastilla">Desactivado</span>}
                  {u.activo && u.debe_cambiar && <span className="pastilla nivel-amarillo">Contraseña temporal</span>}
                </td>
                <td data-etq="Rol">
                  <select value={u.rol} aria-label={`Rol de ${u.nombre}`} disabled={u.id === yo.id}
                          title={u.id === yo.id ? "Otro administrador puede cambiar tu rol" : undefined}
                          onChange={(e) => cambiar(u, { rol: e.target.value }, `Rol de ${u.nombre}: ${d.roles[e.target.value]}.`)}>
                    {Object.entries(d.roles).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                  </select>
                </td>
                <td data-etq="Recibe por correo">
                  <label className="casilla">
                    <input type="checkbox" checked={u.notificar_rojo}
                           onChange={(e) => cambiar(u, { notificar_rojo: e.target.checked },
                                                    `${u.nombre} ${e.target.checked ? "recibirá" : "ya no recibirá"} las alertas críticas.`)} />
                    <i className="punto rojo" aria-hidden="true" />Críticas
                  </label>
                  <label className="casilla">
                    <input type="checkbox" checked={u.notificar_amarillo}
                           onChange={(e) => cambiar(u, { notificar_amarillo: e.target.checked },
                                                    `${u.nombre} ${e.target.checked ? "recibirá" : "ya no recibirá"} las alertas predictivas.`)} />
                    <i className="punto amarillo" aria-hidden="true" />Predictivas
                  </label>
                </td>
                <td data-etq="Último acceso">{u.ultimo_acceso ? fechaHora(u.ultimo_acceso) : "Nunca"}</td>
                <td className="acciones-fila">
                  {u.id === yo.id ? <a className="boton chico" href="#/cuenta">Cambiar mi contraseña</a> : (
                    <>
                      <button className="boton chico" onClick={() => { setRestableciendo(u); setAviso(null); }}>Restablecer contraseña</button>
                      <button className="boton chico" onClick={() => cambiar(u, { activo: !u.activo },
                        `${u.nombre} quedó ${u.activo ? "desactivado: ya no puede entrar" : "activo de nuevo"}.`)}>
                        {u.activo ? "Desactivar" : "Activar"}
                      </button>
                    </>
                  )}
                </td>
              </tr>
            ))}
            {!visibles.length && <tr><td colSpan={5} className="vacio">Ningún usuario coincide con el filtro.</td></tr>}
          </tbody>
        </table>
        {restableciendo && (
          <Restablecer usuario={restableciendo} minimo={d.minimo_contrasena} onCancelar={() => setRestableciendo(null)}
                       onListo={(u) => { setRestableciendo(null); listo(`Contraseña de ${u.nombre} restablecida. Deberá cambiarla al entrar.`); }} />
        )}
        <p className="nota">
          Los correos se enviarán cuando el servicio tenga configurado el envío por SMTP. Desactivar a
          alguien cierra sus sesiones abiertas.
        </p>
      </section>

      <section className="panel bitacora-sistema" aria-label="Bitácora de accesos y cambios">
        <div className="panel-cabeza"><h2>Bitácora de accesos y cambios</h2><span className="nota">Últimos 60</span></div>
        <ul className="lista-bitacora">
          {(bitacora.datos ?? []).map((b, i) => (
            <li key={i} className={b.accion.startsWith("inicio_") && b.accion !== "inicio_sesion" ? "alerta" : ""}>
              <time>{fechaHora(b.fecha)}</time>
              <span className="que">{ACCIONES[b.accion] ?? b.accion}</span>
              <span className="quien">{b.correo ?? "sistema"}{b.origen ? `, desde ${b.origen}` : ""}</span>
              {b.detalle && <span className="detalle">{detalleLegible(b.detalle)}</span>}
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
