import { fechaHora } from "../formato.js";
import { conNombres, haceCuanto, lugaresOrdenados, nombreDe, parametro, PARS, saludo, veredicto } from "../sencillo.js";
import { Icono } from "./Menu.jsx";
import { ordenRed } from "./RedSensores.jsx";

// Inicio (vista sencilla): ¿está bien el agua?, ¿dónde hay un problema? y ¿qué hay que hacer?
// En palabras y con los nombres de los lugares. Los gráficos y las probabilidades están en la vista
// detallada (#/general), a un clic.

const ICONO = { normal: "ok", atencion: "aviso", alarma: "aviso", "sin-dato": "reloj" };

export function EstadoLugar({ e }) {
  return <span className={`estado-lugar tono-${e.tono}`}><Icono nombre={ICONO[e.tono]} tam={15} />{e.palabra}</span>;
}

export function Chips({ parametros }) {
  return (
    <span className="chips">
      {parametros.map((x) => <span key={x.par} className={`chip tono-${x.tono}`}>{x.etiqueta}</span>)}
    </span>
  );
}

// lo que está fuera de la norma casi siempre en un punto (no es una alerta nueva)
function deSiempre(sensores, norma, nombres) {
  return sensores.flatMap((s) => PARS.map((p) => parametro(s, p, norma)).filter((x) => x.habitual).map((x) => ({
    nodo: s.nodo,
    titulo: `${x.par === "TURB" ? "Agua turbia" : `${x.par === "CL2" ? "Cloro" : "pH"} ${x.palabra.replace(" (de siempre)", "")}`} de siempre en ${nombreDe(nombres, s.nodo)}`,
    texto: x.par === "CL2" ? "Pasa casi siempre en ese punto. No es algo nuevo, pero conviene revisar la cloración de ese sector."
      : "Pasa casi siempre en ese punto. No es algo nuevo, pero conviene revisarlo.",
  })));
}

function quienAtiende(a) {
  return a.estado === "en_atencion" ? `La atiende ${a.responsable_nombre}` : "Nadie la atiende todavía";
}

export default function Inicio({ sesion, estado, sensores, norma, nombres, anticipacion, fugas, resumen, pendientes }) {
  const v = veredicto({ resumen, estado, sensores, norma, nombres, anticipacion, fugas });
  const lista = lugaresOrdenados(ordenRed(sensores), norma);
  const conocidos = deSiempre(sensores, norma, nombres);
  const urgentes = (pendientes ?? []).filter((a) => a.nivel === "rojo");
  const urgente = urgentes[0];
  const hora = estado?.ultima_hora_procesada;
  const hace = haceCuanto(hora);
  const primerNombre = sesion.inicio_sesion ? sesion.usuario.nombre.trim().split(/\s+/)[0] : null;
  const total = (pendientes?.length ?? 0) + conocidos.length;
  const bien = lista.filter((x) => x.e.clave === "bien").length;

  return (
    <div className="inicio">
      <div className="saludo-fila">
        <h2>{saludo()}{primerNombre ? `, ${primerNombre}` : ""}</h2>
        {hora && <p>Datos {hace ? `de ${hace} · ` : "de las "}{fechaHora(hora)}</p>}
      </div>

      <section className={`panel veredicto tono-${v.tono}`} aria-labelledby="veredicto-titulo">
        <div className="veredicto-principal">
          <span className="veredicto-icono" aria-hidden="true"><Icono nombre={ICONO[v.tono]} tam={32} /></span>
          <div>
            <h2 id="veredicto-titulo">{v.titulo}</h2>
            <p>{v.texto}</p>
          </div>
        </div>
        {v.tono === "alarma" ? (
          <div className="veredicto-accion">
            {urgente ? (
              <>
                <a className="boton primario grande" href={`#/alertas/${urgente.id}`}>Ver qué hacer</a>
                <span>{quienAtiende(urgente)}</span>
              </>
            ) : v.lugarProblema ? (
              <a className="boton primario grande" href={`#/lugar/${v.lugarProblema}`}>Ver el lugar</a>
            ) : (
              <a className="boton primario grande" href="#/alertas">Ver las alertas</a>
            )}
          </div>
        ) : v.manana && (
          <div className="veredicto-datos">
            <p><Icono nombre="reloj" tam={22} /><span><b>Próximas 24 horas</b>{v.manana}</span></p>
            <p><Icono nombre="gota" tam={22} /><span><b>Fugas</b>{v.fugas}</span></p>
            {urgentes.length > 0 && (
              <p><Icono nombre="alertas" tam={22} /><span><b>Alertas sin cerrar</b>
                <a href="#/alertas">{urgentes.length} urgente{urgentes.length > 1 ? "s" : ""} por atender</a></span></p>
            )}
          </div>
        )}
      </section>

      <div className="inicio-columnas">
        <section className="panel lugares-inicio" aria-labelledby="lugares-titulo">
          <div className="titulo-con-nota">
            <h2 id="lugares-titulo" className="titulo-tarjeta">Los {lista.length} lugares</h2>
            <span className="nota">{lista[0]?.e.clave !== "bien" ? "Primero lo que hay que revisar" : "De la naciente al final de la red"}{bien < lista.length ? ` · ${bien} bien` : ""}</span>
          </div>
          <ul>
            {lista.map(({ s, e }) => (
              <li key={s.nodo}>
                <EstadoLugar e={e} />
                <a className="lugar-nombre" href={`#/lugar/${s.nodo}`}>
                  <b>{nombreDe(nombres, s.nodo)}</b>
                  <span>{nombres?.[s.nodo]?.zona || s.nodo}</span>
                </a>
                <Chips parametros={e.parametros} />
                <Icono nombre="adelante" tam={18} />
              </li>
            ))}
          </ul>
        </section>

        <section className="panel para-atender" aria-labelledby="atender-titulo">
          <div className="titulo-con-nota">
            <h2 id="atender-titulo" className="titulo-tarjeta">Para atender</h2>
            {total > 0 && <span className={`insignia ${urgente ? "" : "suave"}`}>{total}</span>}
          </div>
          {pendientes == null && <p className="vacio">Cargando…</p>}
          {pendientes != null && total === 0 && (
            <p className="nada"><Icono nombre="ok" tam={20} />Nada pendiente.</p>
          )}
          <ul>
            {(pendientes ?? []).map((a) => (
              <li key={a.id}>
                <span className={`chip tono-${a.nivel === "rojo" ? "alarma" : "atencion"} fuerte`}>
                  {a.nivel === "rojo" ? "Urgente" : "Aviso"}
                </span>
                <h3><a href={`#/alertas/${a.id}`}>{conNombres(a.titulo, nombres)}</a></h3>
                <p className="nota">{quienAtiende(a)} · desde {fechaHora(a.inicio)}</p>
              </li>
            ))}
            {conocidos.map((c) => (
              <li key={c.titulo}>
                <span className="chip tono-atencion">Aviso · ya conocido</span>
                <h3><a href={`#/lugar/${c.nodo}`}>{c.titulo}</a></h3>
                <p className="nota">{c.texto}</p>
              </li>
            ))}
          </ul>
          <a className="enlace-mas" href="#/alertas">Ver todas las alertas</a>
        </section>

        <section className="panel glosario" aria-labelledby="glosario-titulo">
          <h2 id="glosario-titulo" className="titulo-tarjeta">Qué se mide</h2>
          <p><b>Cloro:</b> lo que desinfecta el agua. Si baja mucho, el agua puede no estar bien desinfectada.</p>
          <p><b>Claridad:</b> qué tan turbia está el agua (turbidez). Suele empeorar con lluvias fuertes.</p>
          <p><b>pH:</b> qué tan ácida está el agua. Fuera de rango puede dar mal sabor o dañar las tuberías.</p>
        </section>
      </div>

      <p className="panel enlace-detallada">
        ¿Necesitas los gráficos, las probabilidades y los datos completos? <a href="#/general">Abrir la vista detallada</a>
      </p>
    </div>
  );
}
