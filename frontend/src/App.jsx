import { useEffect, useState } from "react";
import { useConsulta } from "./api.js";
import Encabezado from "./componentes/Encabezado.jsx";
import RedSensores from "./componentes/RedSensores.jsx";
import DetalleSensor from "./componentes/DetalleSensor.jsx";
import Alarmas from "./componentes/Alarmas.jsx";
import VistaGeneral from "./componentes/VistaGeneral.jsx";

// La vista vive en la dirección (#/general o #/sensor/J224): así funcionan el botón
// de atrás del navegador y los enlaces directos a un sensor.
function leerRuta() {
  const [, vista, nodo] = window.location.hash.replace(/^#\/?/, "/").split("/");
  return vista === "sensor" ? { vista: "sensor", nodo: nodo || null } : { vista: "general", nodo: null };
}

export default function App() {
  const estado = useConsulta("/api/estado", 2000);
  const sensores = useConsulta("/api/sensores", 2000);
  const alarmas = useConsulta("/api/alarmas", 3000);
  const referencias = useConsulta("/api/referencias", 60000);
  const [ruta, setRuta] = useState(leerRuta);
  const [ultimoSensor, setUltimoSensor] = useState(null);

  useEffect(() => {
    const cambio = () => setRuta(leerRuta());
    window.addEventListener("hashchange", cambio);
    return () => window.removeEventListener("hashchange", cambio);
  }, []);

  const lista = sensores.datos ?? [];
  const abrirSensor = (nodo) => { window.location.hash = `#/sensor/${nodo}`; };

  // en la vista por sensor sin sensor elegido: el primero en alarma, el último visto o J224
  const nodo = ruta.vista === "sensor"
    ? (lista.some((s) => s.nodo === ruta.nodo) ? ruta.nodo
      : (lista.find((s) => s.en_alarma) ?? lista.find((s) => s.nodo === ultimoSensor) ?? lista.find((s) => s.nodo === "J224") ?? lista[0])?.nodo)
    : null;
  useEffect(() => { if (nodo) setUltimoSensor(nodo); }, [nodo]);
  const sensor = lista.find((s) => s.nodo === nodo);
  const sinServicio = Boolean(estado.error) && !estado.datos;

  return (
    <div className="app">
      <Encabezado estado={estado.datos} sinServicio={Boolean(estado.error)} vista={ruta.vista} sensor={nodo ?? ultimoSensor} />

      {estado.error && (
        <div className="aviso grave">
          No hay conexión con el servicio de monitoreo. Revisa que esté corriendo: en la carpeta backend,
          <code> python -m monitoreo.servicio</code>.
        </div>
      )}
      {estado.datos && !estado.datos.conectado_a_datos && (
        <div className="aviso">
          El servicio no recibe datos de los sensores. Revisa que la API de datos esté corriendo
          ({estado.datos.error ?? "sin respuesta"}).
        </div>
      )}
      {!sinServicio && !lista.length && (
        <div className="panel" style={{ marginTop: 16 }}>
          <p className="vacio">Esperando las primeras lecturas. Los pronósticos aparecen cuando se completa la primera hora.</p>
        </div>
      )}

      {lista.length > 0 && ruta.vista === "general" && (
        <div className="cuerpo">
          <VistaGeneral sensores={lista} referencias={referencias.datos} onAbrir={abrirSensor} />
          <Alarmas alarmas={alarmas.datos} onElegir={abrirSensor} />
        </div>
      )}

      {lista.length > 0 && ruta.vista === "sensor" && (
        <>
          <RedSensores sensores={lista} norma={referencias.datos?.norma} elegido={nodo} onElegir={abrirSensor} />
          <div className="cuerpo">
            <DetalleSensor sensor={sensor} referencias={referencias.datos} />
            <Alarmas alarmas={alarmas.datos} onElegir={abrirSensor} />
          </div>
        </>
      )}
    </div>
  );
}
