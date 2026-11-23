import { useEffect, useState } from "react";
import { pedir, useConsulta } from "../api.js";

// Para el administrador: el nombre y la zona de cada punto de medición, como los conoce la
// comunidad. Son los que salen en la vista sencilla y en los mensajes de alerta (/api/lugares).
export default function Lugares({ orden, onGuardado }) {
  const consulta = useConsulta("/api/lugares", 0);
  const [filas, setFilas] = useState(null);
  const [msj, setMsj] = useState(null);
  const [ocupado, setOcupado] = useState(false);
  const datos = consulta.datos;

  useEffect(() => {
    if (!datos || filas) return;
    const pos = (c) => (orden.indexOf(c) + 1 || 999);
    setFilas([...datos.lugares].sort((a, b) => pos(a.codigo) - pos(b.codigo)));
  }, [datos, filas, orden]);

  if (consulta.error && !datos) return <section className="panel"><p className="mensaje error" role="alert">{consulta.error.message}</p></section>;
  if (!filas) return <section className="panel"><p className="vacio">Cargando…</p></section>;

  const cambiar = (i, campo) => (e) => {
    setFilas(filas.map((f, j) => (j === i ? { ...f, [campo]: e.target.value } : f)));
    setMsj(null);
  };
  const guardar = async (e) => {
    e.preventDefault();
    setOcupado(true);
    setMsj(null);
    try {
      const r = await pedir("/api/lugares", { metodo: "PUT", cuerpo: { lugares: filas.map(({ codigo, nombre, zona }) => ({ codigo, nombre, zona })) } });
      const pos = (c) => (orden.indexOf(c) + 1 || 999);
      setFilas([...r.lugares].sort((a, b) => pos(a.codigo) - pos(b.codigo)));
      setMsj({ ok: "Cambios guardados. Ya se ven en el tablero y en las próximas alertas." });
      onGuardado?.();
    } catch (err) {
      setMsj({ error: err.message });
    } finally {
      setOcupado(false);
    }
  };

  return (
    <form className="lugares-admin" onSubmit={guardar}>
      <p className="intro">Así aparecen los puntos de medición en el tablero y en los mensajes de alerta. Usa los nombres que
        reconoce la comunidad, para que cualquiera sepa dónde queda cada uno.</p>
      <section className="panel sin-relleno" aria-label="Nombres de los lugares">
        <div className="tabla-desplazable">
          <table className="tabla tabla-lugares">
            <thead>
              <tr><th scope="col">Sensor</th><th scope="col">Nombre</th><th scope="col">Zona o referencia</th></tr>
            </thead>
            <tbody>
              {filas.map((f, i) => (
                <tr key={f.codigo}>
                  <td className="codigo">{f.codigo}</td>
                  <td data-etq="Nombre">
                    <input aria-label={`Nombre del lugar del sensor ${f.codigo}`} value={f.nombre} required
                           maxLength={datos.nombre_max} onChange={cambiar(i, "nombre")} />
                  </td>
                  <td data-etq="Zona o referencia">
                    <input aria-label={`Zona o referencia del sensor ${f.codigo}`} value={f.zona ?? ""}
                           maxLength={datos.zona_max} onChange={cambiar(i, "zona")} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="pie-formulario">
          <span className="nota">El orden es el del agua: de la naciente al final de la red.</span>
          <button className="boton primario" disabled={ocupado}>{ocupado ? "Guardando…" : "Guardar cambios"}</button>
        </div>
      </section>
      {msj?.ok && <p className="mensaje ok" role="status">{msj.ok}</p>}
      {msj?.error && <p className="mensaje error" role="alert">{msj.error}</p>}
    </form>
  );
}
