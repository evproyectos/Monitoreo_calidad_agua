import { enFrase, fechaHora, TIPOS } from "../formato.js";

// Probabilidad de que empiece cada tipo de evento en las próximas 24 h y 48 h (RF-003.2 d),
// con el umbral de aviso de cada horizonte marcado sobre su barra.
const NOMBRES = { ...TIPOS, anomalia: "Operación fuera de lo normal" };

function pct(x) {
  return x == null ? "—" : `${Math.round(100 * x)} %`;
}

function Barra({ p, umbral, aviso, horizonte }) {
  if (p == null) return <span className="barra vacia" aria-label={`Sin modelo a ${horizonte} h`} />;
  return (
    <span className={`barra h${horizonte}${aviso ? " en-aviso" : ""}`} role="img"
          aria-label={`${horizonte} h: ${pct(p)}, umbral ${pct(umbral)}`}>
      <i style={{ width: `${Math.min(100, 100 * p)}%` }} />
      <b style={{ left: `${100 * umbral}%` }} />
      <em>{pct(p)}</em>
    </span>
  );
}

export default function Anticipacion({ datos }) {
  if (!datos?.disponible) return null;
  const con48 = datos.tipos.some((t) => t.probabilidad_48h != null);
  const activos = datos.tipos.filter((t) => t.en_aviso || t.en_aviso_48h);
  const recientes = datos.avisos.filter((a) => a.fin != null).slice(0, 3);

  return (
    <section className="panel anticipacion" aria-label="Probabilidad de eventos">
      <div className="panel-cabeza">
        <h2>Probabilidad de eventos</h2>
        <span className="claves-h">
          <span><i className="h24" /> 24 h</span>
          {con48 && <span><i className="h48" /> 48 h</span>}
          <span><i className="umbral" /> Umbral</span>
        </span>
      </div>
      <p className={`estado-linea${activos.length ? " en-aviso" : ""}`}>
        {activos.length
          ? `Aviso: posible ${activos.map((t) => enFrase(NOMBRES[t.tipo] ?? t.tipo)).join(" y ")}`
          : "Ningún tipo de evento llega a su umbral."}
      </p>
      <ul className="probabilidades">
        {datos.tipos.map((t) => (
          <li key={t.tipo} className={t.en_aviso || t.en_aviso_48h ? "en-aviso" : ""}>
            <span className="nombre">{NOMBRES[t.tipo] ?? t.tipo}</span>
            <span className="barras">
              <Barra p={t.probabilidad} umbral={t.umbral} aviso={t.en_aviso} horizonte={24} />
              {con48 && <Barra p={t.probabilidad_48h} umbral={t.umbral_48h} aviso={t.en_aviso_48h} horizonte={48} />}
            </span>
          </li>
        ))}
      </ul>
      {recientes.length > 0 && (
        <p className="nota">
          Avisos recientes: {recientes.map((a) => `${enFrase(NOMBRES[a.tipo] ?? a.tipo)} el ${fechaHora(a.inicio)}`).join("; ")}.
        </p>
      )}
    </section>
  );
}
