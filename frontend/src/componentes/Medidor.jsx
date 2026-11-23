import { numero, PARAMETROS } from "../formato.js";

// Una lectura sobre una barra con la zona normal en verde: dónde está el valor respecto a la norma,
// sin tener que saber de memoria los límites. La zona "aceptable" de la turbidez (entre lo
// recomendado y el máximo) va en amarillo claro.
const ESCALA = {
  CL2: (n) => [0, Math.max(1.2, n.maximo * 1.2)],
  TURB: (n) => [0, n.maximo * 1.2],
  PH: () => [5, 10],
};

export function textoNorma(par, n) {
  if (!n) return "";
  if (par === "TURB") return `Ideal: menos de ${numero(n.recomendado, 0)} · máximo ${numero(n.maximo, 0)}`;
  return `Lo normal: de ${numero(n.minimo, 1)} a ${numero(n.maximo, 1)}`;
}

export default function Medidor({ par, valor, norma, tono = "normal" }) {
  const n = norma?.[par];
  if (!n) return null;
  const [a, b] = ESCALA[par](n);
  const pos = (x) => `${Math.min(100, Math.max(0, (100 * (x - a)) / (b - a)))}%`;
  const ancho = (x, y) => `calc(${pos(y)} - ${pos(x)})`;
  const u = PARAMETROS[par].unidad;
  const v = valor == null ? "sin dato" : `${numero(valor, PARAMETROS[par].decimales)}${u ? ` ${u}` : ""}`;
  return (
    <div className={`medidor tono-${tono}`} role="img" aria-label={`${PARAMETROS[par].nombre}: ${v}. ${textoNorma(par, n)}`}>
      <div className="medidor-barra" aria-hidden="true">
        {par === "TURB" ? (
          <>
            <span className="zona bien" style={{ left: 0, width: pos(n.recomendado) }} />
            <span className="zona aceptable" style={{ left: pos(n.recomendado), width: ancho(n.recomendado, n.maximo) }} />
          </>
        ) : (
          <span className="zona bien" style={{ left: pos(n.minimo), width: ancho(n.minimo, n.maximo) }} />
        )}
        {valor != null && <span className="marca-valor" style={{ left: pos(valor) }} />}
      </div>
      <div className="medidor-texto" aria-hidden="true">
        <span><b>{v}</b></span>
        <span>{textoNorma(par, n)}</span>
      </div>
    </div>
  );
}
