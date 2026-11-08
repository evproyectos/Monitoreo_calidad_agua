import { useEffect, useState } from "react";
import { useConsulta } from "./api.js";
import Encabezado from "./componentes/Encabezado.jsx";
import Tarjetas from "./componentes/Tarjetas.jsx";
import DetalleSensor from "./componentes/DetalleSensor.jsx";
import Alarmas from "./componentes/Alarmas.jsx";
import AlertasActivas from "./componentes/AlertasActivas.jsx";
import VistaGeneral, { HORAS } from "./componentes/VistaGeneral.jsx";
import { alertasActivas, resumenRed } from "./estado.js";

// La vista vive en la dirección (#/general, #/fugas o #/sensor/J224): así funcionan el botón
// de atrás del navegador y los enlaces directos a un sensor. #/fugas es la vista general (el
// enlace de las alertas de fuga), que lleva al panel de fugas.
function leerRuta() {
  const [, vista, nodo] = window.location.hash.replace(/^#\/?/, "/").split("/");
  if (vista === "sensor") return { vista: "sensor", nodo: nodo || null };
  return { vista: "general", nodo: null, fugas: vista === "fugas" };
}

// Todo se vuelve a consultar solo, cada pocos segundos (RF-003.2: sin recargar, en ≤ 5 min).
export default function App() {
  const estado = useConsulta("/api/estado", 2000);
  const sensores = useConsulta("/api/sensores", 2000);
  const alarmas = useConsulta("/api/alarmas", 3000);
  const referencias = useConsulta("/api/referencias", 60000);
  const anticipacion = useConsulta("/api/anticipacion", 5000);
  const fugas = useConsulta(`/api/fugas?horas=${HORAS}`, 5000);
  const red = useConsulta(`/api/red/series?horas=${HORAS}`, 5000);
  const [ruta, setRuta] = useState(leerRuta);
  const [ultimoSensor, setUltimoSensor] = useState(null);

  useEffect(() => {
    const cambio = () => setRuta(leerRuta());
    window.addEventListener("hashchange", cambio);
    return () => window.removeEventListener("hashchange", cambio);
  }, []);

  const lista = sensores.datos ?? [];
  const norma = referencias.datos?.norma;
  const abrirSensor = (nodo) => { window.location.hash = `#/sensor/${nodo}`; };

  // en la vista por sensor sin sensor elegido: el primero en alarma, el último visto o el primero
  const nodo = ruta.vista === "sensor"
    ? (lista.some((s) => s.nodo === ruta.nodo) ? ruta.nodo
      : (lista.find((s) => s.en_alarma) ?? lista.find((s) => s.nodo === ultimoSensor) ?? lista[0])?.nodo)
    : null;
  useEffect(() => { if (nodo) setUltimoSensor(nodo); }, [nodo]);
  const sensor = lista.find((s) => s.nodo === nodo);
  useEffect(() => {
    if (ruta.fugas) document.getElementById("fugas")?.scrollIntoView({ behavior: "smooth" });
  }, [ruta.fugas, lista.length]);

  const sinServicio = Boolean(estado.error);
  const alertas = norma ? alertasActivas({ estado: estado.datos, sensores: lista, norma,
                                           anticipacion: anticipacion.datos, fugas: fugas.datos }) : [];
  const resumen = resumenRed({ sinServicio, estado: estado.datos, sensores: lista, alertas });
  const lateral = (
    <aside className="lateral">
      <AlertasActivas alertas={alertas} onAbrir={abrirSensor} />
      <Alarmas alarmas={alarmas.datos} confirmarH={referencias.datos?.confirmar_h} onElegir={abrirSensor} />
    </aside>
  );

  return (
    <div className="app">
      <Encabezado resumen={resumen} hora={estado.datos?.ultima_hora_procesada} vista={ruta.vista}
                  sensor={nodo ?? ultimoSensor} />
      {sinServicio && (
        <p className="aviso">
          Revisa que el servicio esté corriendo: en la carpeta backend, <code>python -m monitoreo.servicio</code>.
          Se muestra la última información recibida.
        </p>
      )}

      {lista.length > 0 && (
        <Tarjetas sensores={lista} red={red.datos} norma={norma} fugas={fugas.datos} estado={estado.datos}
                  elegido={ruta.vista === "sensor" ? nodo : null} onAbrir={abrirSensor} />
      )}

      {lista.length > 0 && ruta.vista === "general" && (
        <div className="cuerpo">
          <VistaGeneral sensores={lista} referencias={referencias.datos} red={red.datos}
                        anticipacion={anticipacion.datos} fugas={fugas.datos} onAbrir={abrirSensor} />
          {lateral}
        </div>
      )}

      {lista.length > 0 && ruta.vista === "sensor" && (
        <div className="cuerpo">
          <DetalleSensor sensor={sensor} referencias={referencias.datos} />
          {lateral}
        </div>
      )}
    </div>
  );
}
