// Etiquetas, unidades, norma y formato de números/fechas (en español de Costa Rica).

export const PARAMETROS = {
  CL2: { nombre: "Cloro libre", unidad: "mg/L", decimales: 2 },
  TURB: { nombre: "Turbidez", unidad: "UNT", decimales: 2 },
  PH: { nombre: "pH", unidad: "", decimales: 2 },
};

// "Falla de pH" → "falla de pH" (solo la primera letra, para usarlo dentro de una frase)
export function enFrase(texto) {
  return texto ? texto[0].toLowerCase() + texto.slice(1) : texto;
}

export const TIPOS = {
  contaminacion: "Contaminación",
  falla_cloro: "Falla de cloración",
  turbidez_fuente: "Turbidez en la fuente",
  falla_ph: "Falla de pH",
  fuga: "Fuga",
};

// Decreto 38924-S (los valores exactos llegan del backend en /api/referencias)
export function fueraDeNorma(par, valor, norma) {
  if (valor == null || !norma) return false;
  const n = norma[par];
  if (par === "TURB") return valor > n.maximo;
  return valor < n.minimo || valor > n.maximo;
}

// Tolerancia de la meta (igual que calidad_agua/metas.py)
export function tolerancia(par, valor, tol) {
  if (valor == null || !tol) return null;
  const t = tol[par];
  return t.relativa ? Math.max(t.minima, t.relativa * Math.abs(valor)) : t.absoluta;
}

const nf = {};
export function numero(x, dec = 2) {
  if (x == null || Number.isNaN(x)) return "—";
  nf[dec] ??= new Intl.NumberFormat("es-CR", { minimumFractionDigits: dec, maximumFractionDigits: dec });
  return nf[dec].format(x);
}

// las fechas llegan como "2026-09-02 11:00:00" (hora de Costa Rica) y se muestran como
// "02/09/2026 11:00:00" (DD/MM/YYYY HH:mm:ss)
const dos = (n) => String(n).padStart(2, "0");
export function partes(texto) {
  const [d, h = "00:00:00"] = texto.split(" ");
  const [a, m, dia] = d.split("-").map(Number);
  return { a, m, dia, hora: (h + ":00").slice(0, 8) };
}
export function fechaDia(texto) {
  const p = partes(texto);
  return `${dos(p.dia)}/${dos(p.m)}/${p.a}`;
}
export function hora(texto) {
  return texto ? partes(texto).hora : "—";
}
export function fechaHora(texto) {
  if (!texto) return "—";
  return `${fechaDia(texto)} ${hora(texto)}`;
}
// marcas del eje de tiempo: la fecha a medianoche, la hora (HH:mm) en las demás
export function etiquetaEje(texto) {
  const p = partes(texto);
  return p.hora === "00:00:00" ? fechaDia(texto) : p.hora.slice(0, 5);
}
export function horasEntre(a, b) {
  return Math.round((new Date(b.replace(" ", "T")) - new Date(a.replace(" ", "T"))) / 3600000);
}
