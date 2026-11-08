// Semáforo del dashboard (RF-003.2 a): verde = normal, amarillo = alerta predictiva,
// rojo = alerta crítica, gris = sin dato. Y la lista de alertas activas ordenada por severidad y
// antelación (RF-003.2 c).
import { enFrase, fueraDeNorma, PARAMETROS, TIPOS } from "./formato.js";

export const NIVELES = {
  rojo: { texto: "Alerta crítica", orden: 0 },
  amarillo: { texto: "Alerta predictiva", orden: 1 },
  verde: { texto: "Normal", orden: 2 },
  gris: { texto: "Sin dato", orden: 3 },
};

const PARS = ["CL2", "TURB", "PH"];

export function nivelSensor(s, norma) {
  if (!s || (s.CL2 == null && s.TURB == null && s.PH == null)) return "gris";
  if (s.en_alarma || PARS.some((p) => fueraDeNorma(p, s[p], norma))) return "rojo";
  if (PARS.some((p) => fueraDeNorma(p, s[`pronostico_${p}`], norma))) return "amarillo";
  return "verde";
}

function problema(par, v, n) {
  if (par === "TURB") return "Turbidez alta";
  const bajo = v < n.minimo;
  return par === "CL2" ? (bajo ? "Cloro bajo" : "Cloro alto") : (bajo ? "pH bajo" : "pH alto");
}

function lista(x) {
  return x.length <= 1 ? x.join("") : `${x.slice(0, -1).join(", ")} y ${x.at(-1)}`;
}

/**
 * Alertas activas a partir del estado del servicio, los sensores, la anticipación y las fugas.
 * Cada una: { nivel, titulo, detalle, antelacion_h, sensor? }. antelacion_h = 0 para lo que ya
 * está pasando; 24 o 48 para lo que el modelo anticipa.
 */
export function alertasActivas({ estado, sensores, norma, anticipacion, fugas }) {
  const out = [];
  if (estado?.alarma_activa && estado.alarma_abierta) {
    const a = estado.alarma_abierta;
    const nodos = a.sensores.split(", ");
    out.push({ nivel: "rojo", antelacion_h: 0, sensor: nodos[0],
               titulo: `${TIPOS[a.tipo_sugerido] ? `Posible ${enFrase(TIPOS[a.tipo_sugerido])}` : "Evento sin clasificar"} en ${lista(nodos)}`,
               detalle: `Alarma del detector, en curso desde hace ${a.horas} h.` });
  }
  if (estado?.fuga_activa) {
    const f = fugas?.actual;
    out.push({ nivel: "rojo", antelacion_h: 0, titulo: "Posible fuga",
               detalle: f?.tramo ? `Entre ${f.tramo.replace(" – ", " y ")}. La fuente entrega ${f.caudal_extra_Ls ?? "—"} L/s de más.`
                 : "El caudal de la fuente no se comporta como de costumbre." });
  }
  sensores.forEach((s) => PARS.forEach((p) => {
    if (fueraDeNorma(p, s[p], norma)) {
      out.push({ nivel: "rojo", antelacion_h: 0, sensor: s.nodo, titulo: `${problema(p, s[p], norma[p])} en ${s.nodo}`,
                 detalle: `${PARAMETROS[p].nombre} fuera de la norma de agua potable.` });
    }
  }));
  (anticipacion?.tipos ?? []).forEach((t) => {
    const nombre = TIPOS[t.tipo] ?? t.tipo;
    if (t.en_aviso) {
      out.push({ nivel: "amarillo", antelacion_h: 24, titulo: `Posible ${enFrase(nombre)}`,
                 detalle: `En las próximas 24 h. Probabilidad ${Math.round(100 * t.probabilidad)} %.` });
    } else if (t.en_aviso_48h) {
      out.push({ nivel: "amarillo", antelacion_h: 48, titulo: `Posible ${enFrase(nombre)}`,
                 detalle: `En las próximas 48 h. Probabilidad ${Math.round(100 * t.probabilidad_48h)} %.` });
    }
  });
  sensores.forEach((s) => PARS.forEach((p) => {
    if (!fueraDeNorma(p, s[p], norma) && fueraDeNorma(p, s[`pronostico_${p}`], norma)) {
      out.push({ nivel: "amarillo", antelacion_h: 24, sensor: s.nodo,
                 titulo: `${problema(p, s[`pronostico_${p}`], norma[p])} en ${s.nodo}`,
                 detalle: `El pronóstico sale de norma en las próximas 24 h.` });
    }
  }));
  return out.sort((a, b) => NIVELES[a.nivel].orden - NIVELES[b.nivel].orden || a.antelacion_h - b.antelacion_h);
}

// Una frase con el estado de toda la red, para el encabezado.
export function resumenRed({ sinServicio, estado, sensores, alertas }) {
  if (sinServicio) return { nivel: "gris", texto: "Sin conexión con el servicio de monitoreo" };
  if (!estado) return { nivel: "gris", texto: "Conectando con el servicio…" };
  if (!estado.conectado_a_datos) return { nivel: "gris", texto: "No están llegando datos de los sensores" };
  if (!sensores.length) return { nivel: "gris", texto: "Esperando las primeras lecturas" };
  const peor = alertas[0];
  if (!peor) return { nivel: "verde", texto: `Agua dentro de norma en los ${sensores.length} puntos de medición` };
  const mas = alertas.length > 1 ? ` y ${alertas.length - 1} alerta${alertas.length > 2 ? "s" : ""} más` : "";
  return { nivel: peor.nivel, texto: `${peor.titulo}${mas}` };
}
