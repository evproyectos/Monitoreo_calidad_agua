import { fechaHora, TIPOS } from "../formato.js";

export default function Encabezado({ estado, sinServicio, vista, sensor }) {
  let clase = "sin-dato";
  let texto = "Esperando lecturas";
  if (sinServicio) texto = "Sin conexión con el servicio";
  else if (estado && !estado.conectado_a_datos) texto = "Sin datos de los sensores";
  else if (estado?.alarma_activa) {
    clase = "alarma";
    const tipo = TIPOS[estado.alarma_abierta?.tipo_sugerido];
    texto = `Alarma activa${tipo ? `: ${tipo.toLowerCase()}` : ""}`;
  } else if (estado?.ultima_hora_procesada) {
    clase = "normal";
    texto = "Operación normal";
  }

  return (
    <header className="encabezado">
      <div>
        <h1>Monitoreo de calidad de agua</h1>
        <div className="sub">
          Red de distribución con {estado?.sensores ?? 21} sensores de cloro, turbidez, pH y presión
        </div>
      </div>
      <nav className="vistas" aria-label="Vistas">
        <a href="#/general" aria-current={vista === "general" ? "page" : undefined}>Vista general</a>
        <a href={`#/sensor/${sensor ?? ""}`} aria-current={vista === "sensor" ? "page" : undefined}>
          Por sensor{sensor ? `: ${sensor}` : ""}
        </a>
      </nav>
      <div className="estado">
        <span className="reloj">
          Datos hasta <strong>{fechaHora(estado?.ultima_hora_procesada)}</strong>
        </span>
        <span className={`pastilla ${clase}`} role="status">
          <span aria-hidden="true">{clase === "alarma" ? "▲" : "●"}</span>
          {texto}
        </span>
      </div>
    </header>
  );
}
