// Etiquetas, unidades, norma y formato de números/fechas (en español de Costa Rica).

export const PARAMETROS = {
  CL2: { nombre: "Cloro libre", unidad: "mg/L", decimales: 2 },
  TURB: { nombre: "Turbidez", unidad: "UNT", decimales: 2 },
  PH: { nombre: "pH", unidad: "", decimales: 2 },
};

export const TIPOS = {
  contaminacion: "Contaminación",
  falla_cloro: "Falla de cloración",
  turbidez_fuente: "Turbidez en la fuente",
  falla_ph: "Falla de pH",
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

const MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];
// las fechas llegan como "2026-09-02 11:00:00" (hora local de la red)
export function partes(texto) {
  const [d, h] = texto.split(" ");
  const [a, m, dia] = d.split("-").map(Number);
  return { a, m, dia, hora: h.slice(0, 5) };
}
export function fechaCorta(texto) {
  if (!texto) return "—";
  const p = partes(texto);
  return `${p.dia} ${MESES[p.m - 1]}, ${p.hora}`;
}
export function etiquetaEje(texto) {
  const p = partes(texto);
  return p.hora === "00:00" ? `${p.dia} ${MESES[p.m - 1]}` : p.hora.slice(0, 2) + " h";
}
export function horasEntre(a, b) {
  return Math.round((new Date(b.replace(" ", "T")) - new Date(a.replace(" ", "T"))) / 3600000);
}
