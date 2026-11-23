import { lazy, Suspense, useEffect, useState } from "react";
import { useConsulta } from "./api.js";
import Encabezado from "./componentes/Encabezado.jsx";
import Estructura from "./componentes/Estructura.jsx";
import Inicio from "./componentes/Inicio.jsx";
import { ordenRed } from "./componentes/RedSensores.jsx";
import Tarjetas from "./componentes/Tarjetas.jsx";
import Alarmas from "./componentes/Alarmas.jsx";
import AlertasActivas from "./componentes/AlertasActivas.jsx";
import VistaGeneral, { HORAS } from "./componentes/VistaGeneral.jsx";
import { alertasActivas, resumenRed } from "./estado.js";
import { conNombres, mapaNombres } from "./sencillo.js";

// Las vistas que no se abren al entrar se cargan cuando se piden (RNF-001: la primera carga en
// Fast 3G trae solo la vista general; los gráficos llegan después).
const DetalleSensor = lazy(() => import("./componentes/DetalleSensor.jsx"));
const Usuarios = lazy(() => import("./componentes/Usuarios.jsx"));
const Cuenta = lazy(() => import("./componentes/Cuenta.jsx"));
const GestionAlertas = lazy(() => import("./componentes/GestionAlertas.jsx"));
const Lugar = lazy(() => import("./componentes/Lugar.jsx"));
const Lugares = lazy(() => import("./componentes/Lugares.jsx"));
const cargando = <p className="vacio">Cargando…</p>;

// La vista vive en la dirección: así funcionan el botón de atrás del navegador y los enlaces directos
// (los del correo). La vista sencilla: #/inicio (la portada) y #/lugar/J224. La vista detallada:
// #/general, #/sensor/J224 y #/fugas (la general, en el panel de fugas: el enlace de las alertas de
// fuga). Además #/alertas/12, #/usuarios, #/lugares y #/cuenta.
function leerRuta() {
  const [, vista, nodo] = window.location.hash.replace(/^#\/?/, "/").split("/");
  if (vista === "sensor" || vista === "lugar") return { vista, nodo: nodo || null };
  if (["usuarios", "cuenta", "lugares"].includes(vista)) return { vista, nodo: null };
  if (vista === "alertas") return { vista, nodo: null, alerta: nodo || null };
  if (vista === "general" || vista === "fugas") return { vista: "general", nodo: null, fugas: vista === "fugas" };
  return { vista: "inicio", nodo: null };
}

// Todo se vuelve a consultar solo, cada pocos segundos (RF-003.2: sin recargar, en ≤ 5 min).
export default function App({ sesion, onSalir, onActualizar }) {
  const estado = useConsulta("/api/estado", 2000);
  const sensores = useConsulta("/api/sensores", 2000);
  const alarmas = useConsulta("/api/alarmas", 3000);
  const referencias = useConsulta("/api/referencias", 60000);
  const anticipacion = useConsulta("/api/anticipacion", 5000);
  const fugas = useConsulta(`/api/fugas?horas=${HORAS}`, 5000);
  const indicadores = useConsulta("/api/alertas/indicadores", 15000);
  const lugares = useConsulta("/api/lugares", 60000);
  const [ruta, setRuta] = useState(leerRuta);
  // las series de toda la red y las alertas pendientes, solo en las vistas que las muestran
  const red = useConsulta(["general", "sensor"].includes(ruta.vista) ? `/api/red/series?horas=${HORAS}` : null, 5000);
  const pendientes = useConsulta(ruta.vista === "inicio" ? "/api/alertas?estado=pendientes&limite=6" : null, 10000);
  const [ultimoSensor, setUltimoSensor] = useState(null);

  useEffect(() => {
    const cambio = () => setRuta(leerRuta());
    window.addEventListener("hashchange", cambio);
    return () => window.removeEventListener("hashchange", cambio);
  }, []);

  const lista = sensores.datos ?? [];
  const norma = referencias.datos?.norma;
  const nombres = mapaNombres(lugares.datos?.lugares);
  const abrirSensor = (nodo) => { window.location.hash = `#/sensor/${nodo}`; };

  // en la vista por sensor sin sensor elegido: el primero en alarma, el último visto o el primero
  const nodo = ruta.vista === "sensor"
    ? (lista.some((s) => s.nodo === ruta.nodo) ? ruta.nodo
      : (lista.find((s) => s.en_alarma) ?? lista.find((s) => s.nodo === ultimoSensor) ?? lista[0])?.nodo)
    : null;
  useEffect(() => { if (nodo) setUltimoSensor(nodo); }, [nodo]);
  const sensor = lista.find((s) => s.nodo === nodo);
  // al abrir otro sensor, su detalle queda arriba: se vuelve al principio de la página
  useEffect(() => { if (nodo) window.scrollTo({ top: 0, behavior: "smooth" }); }, [nodo]);
  useEffect(() => {
    if (ruta.fugas) document.getElementById("fugas")?.scrollIntoView({ behavior: "smooth" });
  }, [ruta.fugas, lista.length]);

  // sin conexión = la red falló o el servicio respondió con un error suyo (no un 401 o 403)
  const sinServicio = Boolean(estado.error) && !(estado.error.status < 500);
  // desde cuándo no hay conexión (hora de este equipo), para decirlo en el aviso
  const [sinServicioDesde, setSinServicioDesde] = useState(null);
  useEffect(() => { setSinServicioDesde(sinServicio ? (d) => d ?? new Date() : null); }, [sinServicio]);
  const admin = sesion.permisos.gestionar_usuarios && sesion.inicio_sesion;
  const vista = ["usuarios", "lugares"].includes(ruta.vista) && !admin ? "inicio" : ruta.vista;
  const alertas = norma ? alertasActivas({ estado: estado.datos, sensores: lista, norma,
                                           anticipacion: anticipacion.datos, fugas: fugas.datos }) : [];
  const resumen = resumenRed({ sinServicio, estado: estado.datos, sensores: lista, alertas });
  // sin conexión o sin datos nuevos: lo que se ve es lo último que llegó, y no se puede decir "Normal"
  const desactualizado = lista.length > 0 && resumen.nivel === "gris"
    ? (sinServicio ? "Sin conexión" : "Sin datos nuevos") : null;
  const lateral = (
    <aside className="lateral">
      <AlertasActivas alertas={alertas} onAbrir={abrirSensor} sinAtender={indicadores.datos?.nuevas}
                      enAtencion={indicadores.datos?.en_atencion} desactualizado={desactualizado} />
      <Alarmas alarmas={alarmas.datos} confirmarH={referencias.datos?.confirmar_h} onElegir={abrirSensor} />
    </aside>
  );

  const pie = (
    <>
      <span>{new Date().getFullYear()} © ASADA La Lucha · Alertas tempranas de calidad del agua</span>
      <span>
        Datos meteorológicos: <a href="https://open-meteo.com/" target="_blank" rel="noreferrer">Open-Meteo.com</a>,
        licencia <a href="https://creativecommons.org/licenses/by/4.0/deed.es" target="_blank" rel="noreferrer">CC BY 4.0</a>
      </span>
    </>
  );

  return (
    <Estructura vista={vista} sensor={vista === "lugar" ? ruta.nodo : nodo ?? ultimoSensor} sensores={lista} norma={norma}
                desactualizado={desactualizado} sesion={sesion} onSalir={onSalir} nombres={nombres}
                sinAtender={indicadores.datos?.nuevas ?? 0} pie={pie}>
      {/* el estado de la red, en las vistas del agua; en Usuarios y Mi cuenta no aporta (la campana avisa) */}
      {["general", "sensor", "alertas"].includes(vista) && (
        <Encabezado resumen={{ ...resumen, texto: conNombres(resumen.texto, nombres) }} hora={estado.datos?.ultima_hora_procesada} />
      )}
      {sinServicio && (
        <p className="aviso" role="alert">
          <b>No hay conexión con el servicio de monitoreo</b>
          {sinServicioDesde && <> desde las {sinServicioDesde.toLocaleTimeString("es-CR", { hour12: false })}</>}.
          Lo que se ve es lo último que llegó y puede no estar al día. Si sigue así unos minutos, avise al
          encargado del sistema.
        </p>
      )}

      {vista === "inicio" && (lista.length > 0 ? (
        <Inicio sesion={sesion} estado={estado.datos} sensores={lista} norma={norma} nombres={nombres}
                anticipacion={anticipacion.datos} fugas={fugas.datos} resumen={resumen} pendientes={pendientes.datos} />
      ) : !sinServicio && <p className="panel vacio">{resumen.texto}</p>)}

      <Suspense fallback={cargando}>
        {vista === "lugar" && lista.length > 0 && (
          <Lugar s={lista.find((s) => s.nodo === ruta.nodo)} norma={norma} nombres={nombres} />
        )}
        {vista === "lugares" && (
          <div className="cuerpo-admin">
            <Lugares orden={ordenRed(lista).map((s) => s.nodo)} onGuardado={lugares.recargar} />
          </div>
        )}
        {vista === "usuarios" && <div className="cuerpo-admin"><Usuarios yo={sesion.usuario} /></div>}
        {vista === "alertas" && (
          <div className="cuerpo-admin">
            <GestionAlertas id={ruta.alerta} sesion={sesion} nodos={lista.map((s) => s.nodo)} indicadores={indicadores}
                            nombres={nombres} sensores={lista} norma={norma} />
          </div>
        )}
        {vista === "cuenta" && (
          <div className="cuerpo-admin"><Cuenta usuario={sesion.usuario} onListo={onActualizar} /></div>
        )}
      </Suspense>

      {/* Toda la red: tarjetas y debajo los gráficos con las alertas al lado. Un sensor: su detalle
          arriba y las tarjetas debajo, para pasar a otro. En pantallas angostas las alertas activas
          suben justo debajo del estado de la red (estilos.css, .tablero). */}
      {lista.length > 0 && vista === "general" && (
        <div className="tablero">
          <Tarjetas sensores={lista} red={red.datos} norma={norma} fugas={fugas.datos} estado={estado.datos}
                    elegido={null} onAbrir={abrirSensor} desactualizado={desactualizado} />
          <div className="cuerpo">
            <VistaGeneral sensores={lista} referencias={referencias.datos} red={red.datos}
                          anticipacion={anticipacion.datos} fugas={fugas.datos} onAbrir={abrirSensor} />
            {lateral}
          </div>
        </div>
      )}

      {lista.length > 0 && vista === "sensor" && (
        <div className="tablero">
          <div className="cuerpo">
            <Suspense fallback={<section className="panel">{cargando}</section>}>
              <DetalleSensor sensor={sensor} referencias={referencias.datos} />
            </Suspense>
            {lateral}
          </div>
          <section className="otros-puntos" aria-label="Otros puntos de medición">
            <h2 className="titulo-seccion">Otros puntos de medición</h2>
            <Tarjetas sensores={lista} red={red.datos} norma={norma} fugas={fugas.datos} estado={estado.datos}
                      elegido={nodo} onAbrir={abrirSensor} desactualizado={desactualizado} />
          </section>
        </div>
      )}

      {/* crédito que pide la licencia CC BY 4.0 de los datos de Open-Meteo (lluvia y pronóstico) */}
    </Estructura>
  );
}
