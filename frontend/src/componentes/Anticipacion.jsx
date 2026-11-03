import { useConsulta } from "../api.js";
import { fechaHora, TIPOS } from "../formato.js";

// Probabilidad de que empiece cada tipo de evento en las próximas 24 h (modelo del notebook 09).
// Cada barra muestra la probabilidad y una marca en el umbral de aviso de ese tipo.
const NOMBRES = { ...TIPOS, anomalia: "Operación fuera de lo normal" };

function pct(x) {
  return x == null ? "—" : `${Math.round(100 * x)} %`;
}

export default function Anticipacion() {
  const { datos } = useConsulta("/api/anticipacion", 5000);
  if (!datos?.disponible) return null;
  const activos = datos.tipos.filter((t) => t.en_aviso);
  const recientes = datos.avisos.filter((a) => a.fin != null).slice(0, 3);

  return (
    <section className="panel anticipacion" aria-label="Anticipación de eventos">
      <div className="grafico-cabeza">
        <h2>¿Viene un evento?</h2>
        <span className="nota">
          Probabilidad de que empiece en las próximas 24 h{datos.hora ? ` · ${fechaHora(datos.hora)}` : ""}
        </span>
      </div>
      <p className={`anticipacion-estado${activos.length ? " en-aviso" : ""}`}>
        {activos.length
          ? `Aviso: posible ${activos.map((t) => (NOMBRES[t.tipo] ?? t.tipo).toLowerCase()).join(" y ")}`
          : "Sin avisos: ningún tipo de evento supera su umbral."}
      </p>
      <ul className="probabilidades">
        {datos.tipos.map((t) => (
          <li key={t.tipo} className={t.en_aviso ? "en-aviso" : ""}>
            <span className="nombre">{NOMBRES[t.tipo] ?? t.tipo}</span>
            <span className="barra" role="img"
                  aria-label={`${pct(t.probabilidad)}, umbral ${pct(t.umbral)}`}>
              <i style={{ width: `${Math.min(100, 100 * (t.probabilidad ?? 0))}%` }} />
              <b style={{ left: `${100 * t.umbral}%` }} title={`umbral ${pct(t.umbral)}`} />
            </span>
            <span className="valor">{pct(t.probabilidad)}</span>
          </li>
        ))}
      </ul>
      {recientes.length > 0 && (
        <p className="nota">
          Avisos recientes: {recientes.map((a) => `${(NOMBRES[a.tipo] ?? a.tipo).toLowerCase()} (${fechaHora(a.inicio)})`).join(" · ")}
        </p>
      )}
    </section>
  );
}
