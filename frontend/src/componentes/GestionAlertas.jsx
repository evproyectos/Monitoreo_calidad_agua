import { useEffect, useState } from "react";
import { pedir, useConsulta } from "../api.js";
import { fechaHora, TIPOS } from "../formato.js";

// Gestión de alertas (CU-06): lista filtrable por estado, tipo, nodo y fecha; el detalle con lo que
// hay que saber para actuar; reconocerla, anotar lo que se hizo en campo y cerrarla con su resultado.
// Arriba, el F1 de las alarmas de los últimos 7 días con lo verificado en campo (RF-004.2, RNF-003) y
// el registro de los eventos que ocurrieron sin alerta. Todos los roles la ven; solo el operador técnico
// y el administrador la atienden.

const ESTADOS = { nueva: "Nueva", en_atencion: "En atención", cerrada: "Cerrada" };
const CLASE_ESTADO = { nueva: "nivel-rojo", en_atencion: "nivel-amarillo", cerrada: "nivel-verde" };
const NIVEL = { rojo: "Crítica", amarillo: "Predictiva" };
const ACCIONES = {
  creada: "Creó la alerta", reconocida: "La tomó como responsable", nota: "Observación", cerrada: "La cerró",
  termino: "Dejó de detectar el evento", cerrada_sola: "Se cerró sola",
};
const RESULTADOS = [
  { valor: "confirmada", texto: "Confirmada", ayuda: "El evento ocurrió: se vio en campo o en el laboratorio." },
  { valor: "descartada", texto: "Falso positivo", ayuda: "No había evento: el sistema se equivocó." },
  { valor: "inconclusa", texto: "Inconclusa", ayuda: "No se pudo verificar. No cuenta para evaluar el modelo." },
];
const EVENTO = { ...TIPOS, CL2: "Cloro", TURB: "Turbidez", PH: "pH", anomalia: "Operación fuera de lo normal" };
const pct = (p) => (p == null ? "—" : `${Math.round(100 * p)} %`);
const ESTADO_F1 = {
  bien: { texto: "En la meta", clase: "nivel-verde" },
  bajo: { texto: "Debajo de la meta", clase: "nivel-rojo" },
  sin_datos: { texto: "Faltan casos verificados", clase: "" },
};
const FUENTES = { laboratorio: "Resultado de laboratorio", registro_asada: "Registro de la ASADA",
                  reporte: "Reporte de un abonado", otra: "Otra" };
const VACIO = { fecha: "", tipo: "", lugar: "", fuente: "", observaciones: "" };
const cuantos = (n, uno, varios) => `${n} ${n === 1 ? uno : varios}`;

function Rendimiento({ puede }) {
  const r = useConsulta("/api/rendimiento", 30000);
  const [abierto, setAbierto] = useState(false);
  const [f, setF] = useState(VACIO);
  const [msj, setMsj] = useState(null);
  const [ocupado, setOcupado] = useState(false);
  if (!r.datos) return null;
  const a = r.datos.actual;
  const est = ESTADO_F1[a.estado] ?? ESTADO_F1.sin_datos;
  const cambiar = (k) => (e) => setF({ ...f, [k]: e.target.value });
  const enviar = async (e) => {
    e.preventDefault();
    setOcupado(true);
    setMsj(null);
    try {
      await pedir("/api/rendimiento/no-detectados", { metodo: "POST", cuerpo: { ...f, lugar: f.lugar || null } });
      setMsj({ ok: "Registrado. Cuenta como evento no detectado en el F1." });
      setF(VACIO);
      r.recargar();
    } catch (err) {
      setMsj({ error: err.message });
    } finally {
      setOcupado(false);
    }
  };
  const listo = f.fecha && f.tipo && f.fuente && f.observaciones.trim().length >= 5;

  return (
    <div className={`rendimiento estado-${a.estado}`} role="group" aria-label="F1 de las alarmas">
      <div className="rend-cabeza">
        <span><b>F1 de las alarmas</b> · últimos {r.datos.ventana_dias} días</span>
        <span className={`pastilla ${est.clase}`}>{est.texto}</span>
      </div>
      <div className="rend-valores">
        <div><b>{pct(a.f1)}</b><span>F1 (meta ≥ {pct(r.datos.f1_minimo)})</span></div>
        <div><b>{pct(a.precision)}</b><span>Alarmas que eran eventos</span></div>
        <div><b>{pct(a.sensibilidad)}</b><span>Eventos con alarma</span></div>
      </div>
      <p className="nota">
        {cuantos(a.confirmadas, "confirmada", "confirmadas")} · {cuantos(a.descartadas, "falso positivo", "falsos positivos")}
        {" · "}{cuantos(a.no_detectados, "no detectado", "no detectados")}
        {a.sin_verificar ? ` · ${a.sin_verificar} sin verificar` : ""}
        {a.estado === "sin_datos" && ` · se necesitan al menos ${r.datos.minimo_casos} casos verificados`}
      </p>
      {puede && !abierto && (
        <button className="boton-texto" onClick={() => { setAbierto(true); setMsj(null); }}>
          Registrar un evento que no se detectó
        </button>
      )}
      {msj?.ok && <p className="mensaje ok" role="status">{msj.ok}</p>}
      {abierto && (
        <form className="formulario no-detectado" onSubmit={enviar}>
          <p className="nota">Un evento que ocurrió sin que el sistema avisara (lo dijo el laboratorio, un registro de
            la ASADA o un abonado). Cuenta en contra del F1: así se mide lo que el sistema deja pasar.</p>
          <div className="dos-columnas">
            <label className="campo"><span>Cuándo ocurrió</span>
              <input type="datetime-local" value={f.fecha} onChange={cambiar("fecha")} required /></label>
            <label className="campo"><span>Tipo de evento</span>
              <select value={f.tipo} onChange={cambiar("tipo")} required>
                <option value="">Elegir…</option>
                {Object.entries(TIPOS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select></label>
            <label className="campo"><span>Dónde</span>
              <input value={f.lugar} onChange={cambiar("lugar")} placeholder="Ej.: J224, calle de la escuela" /></label>
            <label className="campo"><span>Cómo se supo</span>
              <select value={f.fuente} onChange={cambiar("fuente")} required>
                <option value="">Elegir…</option>
                {Object.entries(FUENTES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select></label>
          </div>
          <label className="campo"><span>Observaciones (obligatorias)</span>
            <textarea rows={2} value={f.observaciones} onChange={cambiar("observaciones")} required
                      placeholder="Ej.: muestra semanal del Ministerio con cloro residual de 0,1 mg/L." /></label>
          {msj?.error && <p className="mensaje error" role="alert">{msj.error}</p>}
          <div className="acciones">
            <button className="boton primario chico" disabled={ocupado || !listo}>Registrar</button>
            <button type="button" className="boton chico" onClick={() => { setAbierto(false); setF(VACIO); setMsj(null); }}>
              Cancelar
            </button>
          </div>
        </form>
      )}
    </div>
  );
}

function Indicadores({ datos }) {
  if (!datos) return null;
  return (
    <div className="indicadores" role="group" aria-label="Resumen de las alertas">
      <div className={datos.rojas_sin_atender ? "urgente" : ""}>
        <b>{datos.nuevas}</b><span>Sin atender{datos.rojas_sin_atender ? ` (${datos.rojas_sin_atender} críticas)` : ""}</span>
      </div>
      <div><b>{datos.en_atencion}</b><span>En atención</span></div>
      <div><b>{datos.cerradas}</b><span>Cerradas en {datos.dias} días</span></div>
      <div>
        <b>{datos.confirmadas_pct == null ? "—" : `${datos.confirmadas_pct} %`}</b>
        <span>Confirmadas en campo</span>
      </div>
    </div>
  );
}

function Fila({ a, elegida }) {
  return (
    <li className={`nivel-${a.nivel}${elegida ? " elegida" : ""}`}>
      <a href={`#/alertas/${a.id}`} aria-current={elegida ? "true" : undefined}>
        <span className="titulo"><i className={`punto ${a.nivel}`} aria-hidden="true" />{a.titulo}</span>
        <span className="lugar">{a.tipo_nombre} · {a.lugar ?? "Toda la red"}</span>
        <span className="pie">
          <time>{fechaHora(a.inicio)}</time>
          <span className={`pastilla ${CLASE_ESTADO[a.estado]}`}>{a.estado === "cerrada" ? a.resultado_nombre : ESTADOS[a.estado]}</span>
          {a.estado === "en_atencion" && <span className="quien">{a.responsable_nombre}</span>}
        </span>
      </a>
    </li>
  );
}

function Detalle({ id, yo, puede, onCambio }) {
  const consulta = useConsulta(id ? `/api/alertas/${id}` : null, 10000);
  const [nota, setNota] = useState("");
  const [cierre, setCierre] = useState({ resultado: "", observaciones: "" });
  const [msj, setMsj] = useState(null);
  const [ocupado, setOcupado] = useState(false);
  useEffect(() => { setNota(""); setCierre({ resultado: "", observaciones: "" }); setMsj(null); }, [id]);

  const a = consulta.datos;
  if (!id) return <section className="panel detalle-alerta vacia"><p className="vacio">Elige una alerta de la lista para ver el detalle y atenderla.</p></section>;
  if (consulta.error?.status === 404) return <section className="panel detalle-alerta"><p className="vacio">Esa alerta no existe.</p></section>;
  if (!a) return <section className="panel detalle-alerta"><p className="vacio">Cargando…</p></section>;

  const hacer = async (ruta, cuerpo, ok) => {
    setOcupado(true);
    setMsj(null);
    try {
      await pedir(`/api/alertas/${id}/${ruta}`, { metodo: "POST", cuerpo });
      setMsj({ ok });
      consulta.recargar();
      onCambio();
      return true;
    } catch (err) {
      setMsj({ error: err.message });
      return false;
    } finally {
      setOcupado(false);
    }
  };
  const abierta = a.estado !== "cerrada";
  const deOtro = a.estado === "en_atencion" && a.responsable !== (yo.correo ?? "sin_sesion");

  return (
    <section className={`panel detalle-alerta nivel-${a.nivel}`} aria-label="Detalle de la alerta">
      <a href="#/alertas" className="volver">← Todas las alertas</a>
      <div className="cabeza-alerta">
        <span className={`pastilla nivel-${a.nivel}`}><i />{NIVEL[a.nivel]}</span>
        <span className={`pastilla ${CLASE_ESTADO[a.estado]}`}>{a.estado === "cerrada" ? `Cerrada: ${a.resultado_nombre}` : ESTADOS[a.estado]}</span>
        <span className="nota">#{a.id} · {a.activa ? "El sistema la sigue detectando" : `Terminó el ${fechaHora(a.fin)}`}</span>
      </div>
      <h2>{a.titulo}</h2>

      <dl className="datos-alerta">
        <div><dt>Tipo</dt><dd>{a.tipo_nombre}{a.evento && EVENTO[a.evento] && a.tipo !== "fuga" ? ` · ${EVENTO[a.evento]}` : ""}</dd></div>
        <div><dt>Dónde</dt><dd>{a.lugar ?? "Toda la red"}</dd></div>
        <div><dt>Probabilidad</dt><dd>{pct(a.probabilidad)}</dd></div>
        <div><dt>Antelación</dt><dd>{a.antelacion_h ? `${a.antelacion_h} h antes` : "Ya está ocurriendo"}</dd></div>
        <div><dt>Desde</dt><dd>{fechaHora(a.inicio)}</dd></div>
        <div><dt>Responsable</dt><dd>{a.responsable_nombre ?? "Nadie todavía"}</dd></div>
      </dl>
      {a.parametros && <p className="parametros"><b>Lecturas:</b> {a.parametros}.</p>}
      {a.accion && <p className="accion-recomendada"><b>Qué hacer:</b> {a.accion}.</p>}
      {a.nodos?.length > 0 && a.tipo !== "fuga" && (
        <p className="nota">Ver el sensor: {a.nodos.map((n, i) => <span key={n}>{i ? ", " : ""}<a href={`#/sensor/${n}`}>{n}</a></span>)}</p>
      )}

      {msj?.ok && <p className="mensaje ok" role="status">{msj.ok}</p>}
      {msj?.error && <p className="mensaje error" role="alert">{msj.error}</p>}

      {abierta && puede && (
        <div className="atender">
          {a.estado === "nueva" && (
            <button className="boton primario" disabled={ocupado}
                    onClick={() => hacer("reconocer", undefined, "Quedaste como responsable de esta alerta.")}>
              Reconocer y atender
            </button>
          )}
          {deOtro && <p className="mensaje info">La atiende {a.responsable_nombre}. Puedes agregar observaciones.</p>}

          <form className="formulario" onSubmit={async (e) => {
            e.preventDefault();
            if (await hacer("notas", { texto: nota }, "Observación agregada.")) setNota("");
          }}>
            <label className="campo">
              <span>Acciones realizadas y observaciones de campo</span>
              <textarea rows={3} value={nota} onChange={(e) => setNota(e.target.value)}
                        placeholder="Ej.: se tomó muestra en la llave del parque; cloro residual 0,15 mg/L." />
            </label>
            <div className="acciones"><button className="boton" disabled={ocupado || nota.trim().length < 5}>Agregar observación</button></div>
          </form>

          {!deOtro && (
            <form className="formulario cierre" onSubmit={async (e) => {
              e.preventDefault();
              await hacer("cerrar", cierre, "Alerta cerrada. Gracias: este resultado sirve para evaluar el modelo.");
            }}>
              <fieldset>
                <legend>Cerrar la alerta: ¿qué se encontró?</legend>
                {RESULTADOS.map((r) => (
                  <label key={r.valor} className={`opcion${cierre.resultado === r.valor ? " elegida" : ""}`}>
                    <input type="radio" name="resultado" value={r.valor} checked={cierre.resultado === r.valor}
                           onChange={() => setCierre({ ...cierre, resultado: r.valor })} />
                    <span><b>{r.texto}</b><small>{r.ayuda}</small></span>
                  </label>
                ))}
              </fieldset>
              <label className="campo">
                <span>Observaciones (obligatorias)</span>
                <textarea rows={3} value={cierre.observaciones} required
                          onChange={(e) => setCierre({ ...cierre, observaciones: e.target.value })}
                          placeholder="Qué se revisó, qué se encontró y qué se hizo." />
              </label>
              <div className="acciones">
                <button className="boton primario" disabled={ocupado || !cierre.resultado || cierre.observaciones.trim().length < 5}>
                  Cerrar alerta
                </button>
              </div>
            </form>
          )}
        </div>
      )}
      {abierta && !puede && <p className="nota">Solo el operador técnico y el administrador atienden las alertas.</p>}

      <h3 className="subtitulo">Historial</h3>
      <ol className="historial">
        {a.historial.map((h, i) => (
          <li key={i} className={`h-${h.accion}`}>
            <time>{fechaHora(h.fecha)}</time>
            <span className="que"><b>{h.nombre ?? "Sistema"}</b> · {ACCIONES[h.accion] ?? h.accion}</span>
            {h.texto && <span className="texto">{h.texto}</span>}
          </li>
        ))}
      </ol>
    </section>
  );
}

export default function GestionAlertas({ id, sesion, nodos, indicadores }) {
  const [f, setF] = useState({ estado: "pendientes", tipo: "", nodo: "", desde: "", hasta: "" });
  const q = new URLSearchParams(Object.entries(f).filter(([, v]) => v)).toString();
  const lista = useConsulta(`/api/alertas?${q}`, 10000);
  const cambiar = (k) => (e) => setF({ ...f, [k]: e.target.value });
  const filas = lista.datos ?? [];

  return (
    <div className={`gestion${id ? " con-detalle" : ""}`}>
      <section className="panel lista-gestion" aria-label="Alertas">
        <div className="panel-cabeza">
          <div>
            <h2>Alertas</h2>
            <p className="nota">Cada alarma, posible fuga, aviso anticipado o riesgo en 24 h queda aquí hasta que alguien la cierre.</p>
          </div>
        </div>
        <Indicadores datos={indicadores.datos} />
        <Rendimiento puede={sesion.permisos.atender_alertas} />
        <div className="filtros filtros-alertas">
          <label className="campo"><span>Estado</span>
            <select value={f.estado} onChange={cambiar("estado")}>
              <option value="pendientes">Pendientes</option>
              <option value="nueva">Nuevas</option>
              <option value="en_atencion">En atención</option>
              <option value="cerrada">Cerradas</option>
              <option value="">Todas</option>
            </select>
          </label>
          <label className="campo"><span>Tipo</span>
            <select value={f.tipo} onChange={cambiar("tipo")}>
              <option value="">Todos</option>
              <option value="alarma">Alarmas</option>
              <option value="fuga">Posibles fugas</option>
              <option value="aviso">Avisos anticipados</option>
              <option value="riesgo">Riesgo en 24 h</option>
            </select>
          </label>
          <label className="campo"><span>Nodo</span>
            <select value={f.nodo} onChange={cambiar("nodo")}>
              <option value="">Todos</option>
              {nodos.map((n) => <option key={n} value={n}>{n}</option>)}
            </select>
          </label>
          <label className="campo"><span>Desde</span><input type="date" value={f.desde} onChange={cambiar("desde")} /></label>
          <label className="campo"><span>Hasta</span><input type="date" value={f.hasta} onChange={cambiar("hasta")} /></label>
        </div>
        {lista.error && !lista.datos && <p className="mensaje error">{lista.error.message}</p>}
        {lista.datos && !filas.length && (
          <p className="vacio">{f.estado === "pendientes" ? "No hay alertas pendientes." : "Ninguna alerta coincide con los filtros."}</p>
        )}
        <ul className="lista-gestion-alertas">
          {filas.map((a) => <Fila key={a.id} a={a} elegida={String(a.id) === String(id)} />)}
        </ul>
      </section>
      <Detalle id={id} yo={sesion.usuario} puede={sesion.permisos.atender_alertas}
               onCambio={() => { lista.recargar(); indicadores.recargar(); }} />
    </div>
  );
}
