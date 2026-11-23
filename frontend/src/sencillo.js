// La vista sencilla: el estado del agua en palabras, para quien no necesita los gráficos (la Junta,
// los operadores en el campo). Usa los mismos datos y la misma norma que la vista detallada
// (estado.js); aquí solo se dice de otra forma: "Bien", "Revisar", "el cloro está bajo", y en vez
// del código de cada sensor, el nombre del lugar (página Lugares, /api/lugares).
import { enFrase, fueraDeNorma, TIPOS } from "./formato.js";
import { habitual, nivelSensor } from "./estado.js";

export const PARS = ["CL2", "TURB", "PH"];

// tono = los colores del semáforo en estilos.css (.tono-*)
const ESTADO = {
  rojo: { clave: "revisar", palabra: "Revisar", tono: "alarma", orden: 0 },
  amarillo: { clave: "vigilar", palabra: "Vigilar", tono: "atencion", orden: 1 },
  habitual: { clave: "aviso", palabra: "Aviso", tono: "atencion", orden: 2 },
  verde: { clave: "bien", palabra: "Bien", tono: "normal", orden: 3 },
  gris: { clave: "sin_dato", palabra: "Sin dato", tono: "sin-dato", orden: 4 },
};

export const NOMBRE = { CL2: "Cloro", TURB: "Claridad", PH: "pH" };
export const QUE_ES = { CL2: "desinfección", TURB: "turbidez", PH: "acidez" };

// --------------------------------------------------------------------- nombres de los lugares
export function mapaNombres(lugares) {
  return Object.fromEntries((lugares ?? []).map((l) => [l.codigo, l]));
}
export const nombreDe = (nombres, nodo) => nombres?.[nodo]?.nombre ?? nodo;

// "A", "A y B", "A, B y C"
export function enLista(x) {
  return x.length <= 1 ? x.join("") : `${x.slice(0, -1).join(", ")} y ${x.at(-1)}`;
}

// cambia cada código de sensor de un texto (J101) por el nombre del lugar (Escuela)
export function conNombres(texto, nombres) {
  const codigos = Object.keys(nombres ?? {}).filter((c) => nombres[c].nombre && nombres[c].nombre !== c);
  if (!texto || !codigos.length) return texto;
  const patron = new RegExp(`(?<![\\w-])(${codigos.sort((a, b) => b.length - a.length).map((c) => c.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})(?![\\w-])`, "g");
  return texto.replace(patron, (c) => nombres[c].nombre);
}

// --------------------------------------------------------------------- un parámetro, en palabras
// { par, palabra, etiqueta ("Cloro bajo"), tono, habitual }
export function parametro(s, p, norma) {
  const v = s?.[p];
  const n = norma?.[p];
  const r = (palabra, tono, extra = {}) => ({ par: p, palabra, tono, etiqueta: etiqueta(p, palabra), valor: v, ...extra });
  if (v == null || !n) return r("sin dato", "sin-dato");
  const hab = habitual(s, p, norma);
  const futuro = s[`pronostico_${p}`];
  if (fueraDeNorma(p, v, norma)) {
    const bajo = p !== "TURB" && v < n.minimo;
    const palabra = p === "TURB" ? "turbia" : bajo ? "bajo" : "alto";
    return r(hab ? `${palabra} (de siempre)` : palabra, hab ? "atencion" : "alarma", { fuera: true, bajo, habitual: hab });
  }
  if (!hab && fueraDeNorma(p, futuro, norma)) {
    const palabra = p === "TURB" ? "podría enturbiarse" : futuro < n.minimo ? "podría bajar" : "podría subir";
    return r(palabra, "atencion", { pronostico: true, bajo: p !== "TURB" && futuro < n.minimo });
  }
  if (p === "TURB") return r(v > n.recomendado ? "aceptable" : "clara", "normal");
  return r("bien", "normal");
}

function etiqueta(p, palabra) {
  if (p === "TURB") return palabra === "sin dato" ? "Claridad sin dato" : `Agua ${palabra}`;
  return `${NOMBRE[p]} ${palabra}`;
}

// --------------------------------------------------------------------- un lugar
export function estadoLugar(s, norma) {
  return { ...ESTADO[nivelSensor(s, norma)], parametros: PARS.map((p) => parametro(s, p, norma)) };
}

// qué pasa en un lugar con problema, en una frase
export function problemaEnFrase(s, norma) {
  const fuera = PARS.map((p) => parametro(s, p, norma)).filter((x) => x.fuera && !x.habitual);
  const x = fuera[0];
  if (x?.par === "CL2" && x.bajo) return "El cloro está por debajo del mínimo: el agua de ese sector podría no estar bien desinfectada.";
  if (x?.par === "CL2") return "El cloro está por encima del máximo permitido.";
  if (x?.par === "TURB") return "El agua está más turbia de lo permitido.";
  if (x?.par === "PH") return "El pH del agua está fuera de lo normal.";
  const tipo = TIPOS[s.tipo_sugerido];
  return tipo ? `El sistema detectó señales de posible ${enFrase(tipo)}.` : "Las lecturas se apartan de lo normal.";
}

// lo que se espera en un lugar en las próximas 24 h
export function futuroEnFrase(s, norma, nombres) {
  const x = PARS.map((p) => parametro(s, p, norma)).find((y) => y.pronostico);
  if (!x) return null;
  const que = x.par === "TURB" ? "el agua podría enturbiarse" : `${x.par === "CL2" ? "el cloro" : "el pH"} ${x.palabra}`;
  return `${que[0].toUpperCase()}${que.slice(1)} en ${nombreDe(nombres, s.nodo)}`;
}

// --------------------------------------------------------------------- toda la red
/**
 * El veredicto grande del inicio: { tono, titulo, texto, manana, fugas, lugarProblema? }.
 * `resumen` es el de estado.js (para los casos sin conexión o sin datos).
 */
export function veredicto({ resumen, estado, sensores, norma, nombres, anticipacion, fugas }) {
  const fugasTexto = estado?.fuga_activa
    ? (fugas?.actual?.tramo ? `Posible fuga entre ${enLista(fugas.actual.tramo.split(/\s*[–-]\s*/).map((n) => nombreDe(nombres, n)))}`
      : "Posible fuga")
    : "No se detectan";
  if (resumen.nivel === "gris") {
    return { tono: "sin-dato", titulo: resumen.texto, texto: "Lo que se ve es lo último que llegó y puede no estar al día.",
             manana: null, fugas: null };
  }
  const lugares = sensores.map((s) => ({ s, e: estadoLugar(s, norma) }));
  const revisar = lugares.filter((x) => x.e.clave === "revisar");
  const vigilar = lugares.filter((x) => x.e.clave === "vigilar");
  const avisos = lugares.filter((x) => x.e.clave === "aviso");
  const futuros = vigilar.map((x) => futuroEnFrase(x.s, norma, nombres)).filter(Boolean);
  const anticipado = (anticipacion?.tipos ?? []).find((t) => t.en_aviso);
  const manana = futuros.length ? `${futuros[0]}${futuros.length > 1 ? ` y en ${futuros.length - 1} lugar${futuros.length > 2 ? "es" : ""} más` : ""}`
    : anticipado ? `Podría haber ${enFrase(TIPOS[anticipado.tipo] ?? "un evento fuera de lo normal")}`
      : "Se espera que siga bien";

  const bien = lugares.filter((x) => x.e.clave === "bien").length;
  if (revisar.length === 1) {
    const { s } = revisar[0];
    const otros = sensores.length - 1;
    const resto = !otros ? "" : bien === otros ? ` Los otros ${otros} lugares están bien.` : ` ${bien} de los otros ${otros} lugares están bien.`;
    return { tono: "alarma", titulo: `Hay un problema en ${nombreDe(nombres, s.nodo)}`, lugarProblema: s.nodo,
             texto: `${problemaEnFrase(s, norma)}${resto}`, manana, fugas: fugasTexto };
  }
  if (revisar.length > 1) {
    return { tono: "alarma", titulo: `Hay problemas en ${revisar.length} lugares`,
             texto: `Hay que revisar ${enLista(revisar.map((x) => nombreDe(nombres, x.s.nodo)))}.`, manana, fugas: fugasTexto };
  }
  if (estado?.fuga_activa) {
    return { tono: "alarma", titulo: "Puede haber una fuga",
             texto: `${fugasTexto}: la fuente está entregando más agua de lo normal. El agua de los lugares está bien.`,
             manana, fugas: fugasTexto };
  }
  if (futuros.length || anticipado) {
    return { tono: "atencion", titulo: "El agua está bien, pero hay que vigilar",
             texto: `${manana} en las próximas 24 horas.`, manana, fugas: fugasTexto };
  }
  if (avisos.length) {
    const nota = avisos.map((x) => {
      const p = x.e.parametros.find((y) => y.habitual);
      const que = p?.par === "TURB" ? "el agua sigue turbia" : `${p?.par === "PH" ? "el pH" : "el cloro"} sigue ${p?.palabra.replace(" (de siempre)", "")}`;
      return `En ${nombreDe(nombres, x.s.nodo)} ${que}, como de costumbre.`;
    }).join(" ");
    return { tono: "normal", titulo: "El agua está bien",
             texto: `En ${sensores.length - avisos.length} de los ${sensores.length} lugares todo está dentro de la norma. ${nota}`,
             manana, fugas: fugasTexto };
  }
  return { tono: "normal", titulo: "El agua está bien",
           texto: `Los ${sensores.length} lugares tienen el cloro, la claridad y el pH dentro de la norma.`, manana, fugas: fugasTexto };
}

// los lugares para la lista del inicio: primero lo que hay que revisar, luego el orden de la red
export function lugaresOrdenados(ordenados, norma) {
  return ordenados.map((s, i) => ({ s, e: estadoLugar(s, norma), i }))
    .sort((a, b) => a.e.orden - b.e.orden || a.i - b.i);
}

// --------------------------------------------------------------------- tiempo
export function saludo(fecha = new Date()) {
  const h = fecha.getHours();
  return h < 12 ? "Buenos días" : h < 19 ? "Buenas tardes" : "Buenas noches";
}

// "hace 5 minutos", "hace 3 horas"; null si es de hace más de 2 días (con el emisor acelerado los
// datos son de otras fechas y "hace 4 meses" no ayuda)
export function haceCuanto(texto, ahora = new Date()) {
  if (!texto) return null;
  const min = Math.round((ahora - new Date(texto.replace(" ", "T"))) / 60000);
  if (min < 0 || min > 48 * 60) return null;
  if (min < 1) return "hace un momento";
  if (min < 60) return `hace ${min} minuto${min === 1 ? "" : "s"}`;
  const h = Math.floor(min / 60);
  return `hace ${h} hora${h === 1 ? "" : "s"}`;
}

// --------------------------------------------------------------------- alertas
const EVENTO_A_PAR = { falla_cloro: "CL2", turbidez_fuente: "TURB", falla_ph: "PH", CL2: "CL2", TURB: "TURB", PH: "PH" };
export const parDeAlerta = (a) => EVENTO_A_PAR[a.evento] ?? null;

// los lugares de una alerta, en palabras
export function lugarDeAlerta(a, nombres) {
  const nodos = a.nodos ?? [];
  if (a.tipo === "fuga" && nodos.length === 2) return `Entre ${nombreDe(nombres, nodos[0])} y ${nombreDe(nombres, nodos[1])}`;
  if (nodos.length) return enLista(nodos.map((n) => nombreDe(nombres, n)));
  return a.lugar ?? "Toda la red";
}

// qué pasó, en una frase
export function explicacion(a, nombres) {
  const donde = lugarDeAlerta(a, nombres);
  if (a.tipo === "fuga") return `La fuente está entregando más agua de lo normal: puede haber una fuga ${donde.toLowerCase().startsWith("entre") ? enFrase(donde) : `en ${donde}`}.`;
  if (a.tipo === "riesgo") {
    const que = { CL2: "el cloro", TURB: "la claridad del agua", PH: "el pH" }[a.evento] ?? "una lectura";
    return `El pronóstico indica que ${que} podría salir de la norma en ${donde} en las próximas 24 horas.`;
  }
  if (a.tipo === "aviso") {
    const tipo = TIPOS[a.evento];
    return `Es posible que en las próximas 24 horas haya ${tipo ? enFrase(tipo) : "algo fuera de lo normal"}${a.nodos?.length ? `, empezando en ${donde}` : ""}.`;
  }
  return {
    contaminacion: `El sistema detectó señales de posible contaminación del agua en ${donde}.`,
    falla_cloro: `El cloro bajó en ${donde}: puede ser una falla en la cloración.`,
    turbidez_fuente: `El agua viene más turbia desde la fuente y se nota en ${donde}.`,
    falla_ph: `El pH del agua se salió de lo normal en ${donde}.`,
  }[a.evento] ?? `Las lecturas de ${donde} se apartan de lo normal.`;
}

// "qué hacer" de la alerta (texto del servicio, alertas.py), en pasos
export function pasos(accion) {
  return (accion ?? "").split(/;\s*/).map((x) => x.trim()).filter(Boolean)
    .map((x) => `${x[0].toUpperCase()}${x.slice(1)}${/[.!?]$/.test(x) ? "" : "."}`);
}
