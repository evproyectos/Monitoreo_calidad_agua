import { fueraDeNorma } from "../formato.js";

// Estado de cada sensor, del más grave al menos grave.
export function estadoSensor(s, norma) {
  if (s.CL2 == null && s.TURB == null && s.PH == null) return "sin-dato";
  if (s.en_alarma) return "alarma";
  if (["CL2", "TURB", "PH"].some((p) => fueraDeNorma(p, s[p], norma))) return "atencion";
  if (["CL2", "TURB", "PH"].some((p) => fueraDeNorma(p, s[`pronostico_${p}`], norma))) return "riesgo";
  return "normal";
}

export const TEXTO_ESTADO = {
  alarma: "En alarma",
  atencion: "Fuera de norma ahora",
  riesgo: "Fuera de norma en 24 h (pronóstico)",
  normal: "Normal",
  "sin-dato": "Sin dato",
};
export const COLOR_ESTADO = { alarma: "--alarma", atencion: "--atencion", riesgo: "--atencion", normal: "--normal", "sin-dato": "--sin-dato" };

// de la fuente al extremo: el cloro típico baja a medida que el agua recorre la red
export function ordenRed(sensores) {
  return [...sensores].sort((a, b) => b.cloro_tipico - a.cloro_tipico);
}
