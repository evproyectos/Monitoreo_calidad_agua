import { useState } from "react";
import { pedir } from "../api.js";
import { fechaHora } from "../formato.js";

// Envío de las alertas por correo (RF-003.3, CU-04 y CU-07): si el servidor de correo está
// configurado, cuántas personas reciben cada nivel, un correo de prueba y los últimos envíos.

const ESTADOS = {
  enviada: { texto: "Enviada", clase: "nivel-verde" },
  fallida: { texto: "No se pudo enviar", clase: "nivel-rojo" },
  sin_destinatarios: { texto: "Nadie la recibe", clase: "nivel-amarillo" },
};
const NIVELES = { rojo: "Crítica", amarillo: "Predictiva", resumen: "Resumen", prueba: "Prueba" };
const personas = (n) => `${n} persona${n === 1 ? "" : "s"}`;

export default function CorreoAlertas({ consulta, yo }) {
  const [prueba, setPrueba] = useState(null);
  const [enviando, setEnviando] = useState(false);
  const d = consulta.datos;
  if (!d) return null;
  const c = d.correo;
  const correos = (d.ultimas ?? []).filter((n) => n.canal === "correo");

  const probar = async () => {
    setEnviando(true);
    setPrueba(null);
    try {
      const r = await pedir("/api/notificaciones/prueba", { metodo: "POST" });
      setPrueba({ ok: `Correo de prueba enviado a ${r.enviado_a}. Si no aparece en un minuto, revisa la carpeta de spam.` });
    } catch (err) {
      setPrueba({ error: err.message });
    } finally {
      setEnviando(false);
      consulta.recargar();
    }
  };

  return (
    <section className="panel correo-alertas" aria-label="Alertas por correo">
      <div className="panel-cabeza">
        <div>
          <h2>Alertas por correo</h2>
          <p className="nota">Cada persona marcada arriba recibe su propio correo cuando el sistema detecta o anticipa un evento.</p>
        </div>
        {c.configurado
          ? <span className="pastilla nivel-verde"><i />Envío activo</span>
          : <span className="pastilla nivel-amarillo"><i />Sin configurar</span>}
      </div>

      <div className="correo-datos">
        <dl>
          {c.configurado ? (
            <>
              <div><dt>Remitente</dt><dd>{c.remitente}</dd></div>
              <div><dt>Servidor</dt><dd>{c.servidor} <small>({c.seguridad === "ninguna" ? "sin cifrar" : c.seguridad.toUpperCase()})</small></dd></div>
            </>
          ) : (
            <div className="sin-configurar">
              <dt>Cómo activarlo</dt>
              <dd>
                En el archivo <code>.env</code> del servicio, completa <code>SMTP_SERVIDOR</code>, <code>SMTP_USUARIO</code> y{" "}
                <code>SMTP_CONTRASENA</code>, y reinicia el servicio. Los pasos para Gmail están en el README.
              </dd>
            </div>
          )}
          <div>
            <dt><i className="punto rojo" aria-hidden="true" /> Críticas</dt>
            <dd className={d.destinatarios.rojo ? "" : "falta"}>{d.destinatarios.rojo ? personas(d.destinatarios.rojo) : "Nadie las recibe"}</dd>
          </div>
          <div>
            <dt><i className="punto amarillo" aria-hidden="true" /> Predictivas</dt>
            <dd className={d.destinatarios.amarillo ? "" : "falta"}>{d.destinatarios.amarillo ? personas(d.destinatarios.amarillo) : "Nadie las recibe"}</dd>
          </div>
        </dl>
        <div className="correo-prueba">
          <button className="boton" onClick={probar} disabled={!c.configurado || enviando || !yo.correo}>
            {enviando ? "Enviando…" : "Enviarme un correo de prueba"}
          </button>
          {yo.correo && <span className="nota">Llega a {yo.correo}</span>}
        </div>
      </div>
      {prueba?.ok && <p className="mensaje ok" role="status">{prueba.ok}</p>}
      {prueba?.error && <p className="mensaje error" role="alert">{prueba.error}</p>}

      <h3 className="subtitulo">Últimos correos</h3>
      {correos.length ? (
        <ul className="lista-bitacora lista-correos">
          {correos.map((n, i) => (
            <li key={i}>
              <time>{fechaHora(n.fecha)}</time>
              <span className="que">
                <i className={`punto ${n.nivel === "rojo" || n.nivel === "amarillo" ? n.nivel : "azul"}`} aria-hidden="true" />
                {n.asunto}
              </span>
              <span className="quien">
                <span className={`pastilla ${ESTADOS[n.estado]?.clase ?? ""}`}>{ESTADOS[n.estado]?.texto ?? n.estado}</span>
                {" "}{NIVELES[n.nivel] ?? n.nivel}
                {n.destinatarios ? ` · ${n.estado === "fallida" ? "faltó: " : ""}${n.destinatarios}` : ""}
                {n.intentos > 1 ? ` · ${n.intentos} intentos` : ""}
              </span>
              {n.error && n.estado !== "enviada" && <span className="detalle">{n.error}</span>}
            </li>
          ))}
        </ul>
      ) : <p className="vacio">Todavía no se ha enviado ningún correo.</p>}
    </section>
  );
}
