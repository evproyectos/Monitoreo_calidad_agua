"""
Predicción a pedido (POST /predict/contaminacion, RF-003.1).

Un sistema externo manda las últimas lecturas de 15 min de toda la red (el mismo formato que los
sensores le envían a la API de datos) y recibe, para la última hora cerrada:
  - la probabilidad de evento de cada sensor (detector), con el tipo sugerido;
  - el pronóstico de cloro, turbidez y pH a 24 h;
  - un nivel de riesgo (verde, amarillo, rojo) por sensor y para la red.

El cálculo es el mismo del motor en vivo (mismas funciones, misma ventana de historia y misma
regla de "hora cerrada"), así que para la misma hora da los mismos números que el dashboard.

Hace falta la red completa porque el detector compara cada sensor con el resto (cuántos se
desvían a la vez, desvío respecto a la mediana de la red).
"""

import json
import os
import time
from datetime import datetime
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

from calidad_agua import calidad, carga, detector, variables
from calidad_agua.red_neuronal import HORIZONTE_H, SALIDAS

from monitoreo.alertas import fuera_de_norma

PARAMETROS_SENSOR = ["CL2", "TEMP", "TURB", "PH", "P"]
COMUNES = ["Q_R1", "lluvia_mm_h"]
HORAS_DATOS_RECIENTES = 24          # cada medición debe tener al menos un dato en estas horas
# el detector mira a lo sumo 24 h hacia atrás (lluvia de 24 h, medias de 12 h): con 48 h de
# lecturas da lo mismo que con toda la historia y tarda la mitad
HORAS_DETECTOR = 48


class Lectura(BaseModel):
    fecha: datetime = Field(description="Hora de la lectura (cada 15 min), hora de Costa Rica")
    valores: Dict[str, Optional[float]] = Field(
        description="Columna -> valor, p. ej. \"CL2_J144\": 0.45. Todas las columnas deben venir; "
                    "null indica que ese sensor no reportó en esa lectura.")


class SolicitudContaminacion(BaseModel):
    lecturas: List[Lectura] = Field(
        min_length=1,
        description="Lecturas de 15 min de toda la red, en orden, que cubran al menos las últimas "
                    "98 h (la historia que usan las variables más la hora en curso).")
    sensores: Optional[List[str]] = Field(
        default=None, description="Sensores a incluir en la respuesta (todos si se omite).")


class ErrorEntrada(Exception):
    """Datos de entrada que no sirven para predecir: se responde 422 con el detalle."""

    def __init__(self, error, detalles=None):
        super().__init__(error)
        self.error, self.detalles = error, detalles or []


def columnas_esperadas(sensores):
    return [f"{p}_{n}" for n in sensores for p in PARAMETROS_SENSOR] + COMUNES


def _hora_local(f):
    f = pd.Timestamp(f)
    return f.tz_convert("America/Costa_Rica").tz_localize(None) if f.tzinfo else f


def validar(solicitud, sensores, historia_h):
    # `sensores` en el orden del entrenamiento (las variables dependen del orden de las columnas)
    """Revisa la solicitud y arma la tabla de lecturas. Lanza ErrorEntrada si algo falta."""
    esperadas = columnas_esperadas(sensores)

    if solicitud.sensores:
        desconocidos = sorted(set(solicitud.sensores) - set(sensores))
        if desconocidos:
            raise ErrorEntrada("Sensores desconocidos en 'sensores'.",
                               [f"{n} no es un sensor de la red" for n in desconocidos])

    fechas = [_hora_local(lec.fecha) for lec in solicitud.lecturas]
    mal_alineadas = [str(f) for f in fechas if f.minute % 15 or f.second or f.microsecond]
    if mal_alineadas:
        raise ErrorEntrada("Las lecturas deben ser cada 15 min (minuto 00, 15, 30 o 45).",
                           [f"fecha no válida: {f}" for f in mal_alineadas[:5]])
    desordenadas = [str(b) for a, b in zip(fechas, fechas[1:]) if b <= a]
    if desordenadas:
        raise ErrorEntrada("Las lecturas deben venir en orden y sin fechas repetidas.",
                           [f"fecha repetida o fuera de orden: {f}" for f in desordenadas[:5]])

    faltan = []
    for f, lec in zip(fechas, solicitud.lecturas):
        ausentes = [c for c in esperadas if c not in lec.valores]
        if ausentes:
            muestra = ", ".join(ausentes[:6]) + (f" y {len(ausentes) - 6} más" if len(ausentes) > 6 else "")
            faltan.append(f"lectura {f}: faltan {muestra}")
    if faltan:
        raise ErrorEntrada("Faltan columnas en las lecturas. Cada lectura debe traer todas las "
                           f"columnas de la red ({len(esperadas)}); use null si un sensor no reportó.",
                           faltan[:5] + ([f"... y {len(faltan) - 5} lecturas más"] if len(faltan) > 5 else []))

    t = pd.DataFrame([lec.valores for lec in solicitud.lecturas], index=pd.DatetimeIndex(fechas, name="fecha"))
    t = t[esperadas].astype("float64")

    # misma regla que el motor: la hora se cierra cuando llega una lectura de la hora siguiente
    hora = t.index[-1].floor("h") - pd.Timedelta(hours=1)
    desde = hora - pd.Timedelta(hours=historia_h) + pd.Timedelta(minutes=15)
    if t.index[0] > desde:
        falta_h = (t.index[0] - desde) / pd.Timedelta(hours=1)
        raise ErrorEntrada(
            "Sin datos suficientes: no alcanza la historia que necesitan las variables.",
            [f"para evaluar la hora {hora} hacen falta lecturas desde {desde}; "
             f"la primera llegó a las {t.index[0]} (faltan {falta_h:.2f} h)",
             f"envíe al menos las últimas {historia_h + 2} h de lecturas"])

    ventana = t.loc[desde:hora + pd.Timedelta(minutes=45)]
    if ventana.loc[hora:].empty:
        raise ErrorEntrada("Sin datos suficientes: no hay lecturas en la hora a evaluar.",
                           [f"no llegó ninguna lectura entre {hora} y {hora + pd.Timedelta(minutes=45)}"])
    recientes = ventana.loc[hora - pd.Timedelta(hours=HORAS_DATOS_RECIENTES - 1):]
    vacias = [c for c in esperadas if recientes[c].isna().all()]
    if vacias:
        raise ErrorEntrada(f"Sin datos suficientes: mediciones sin ningún valor en las últimas "
                           f"{HORAS_DATOS_RECIENTES} h.", [f"{c} solo trae null" for c in vacias[:20]])
    return ventana, hora


def nivel_riesgo(p, umbral, umbral_amarillo, fuera_ahora, fuera_24h):
    if p == p and p >= umbral:
        return "rojo"
    if (p == p and p >= umbral_amarillo) or fuera_ahora or fuera_24h:
        return "amarillo"
    return "verde"


def predecir(solicitud, modelos, historia_h, umbral_amarillo, candado):
    t0 = time.perf_counter()
    ventana, hora = validar(solicitud, modelos.orden_sensores, historia_h)
    w15 = calidad.lecturas_operativas(ventana)
    confirmar = modelos.confirmar_h
    horas_det = pd.date_range(hora - pd.Timedelta(hours=confirmar - 1), hora, freq="1h")
    with candado:                                   # los modelos los comparte el motor en vivo
        pron = modelos.pronosticar(variables.horario(w15), pd.DatetimeIndex([hora]))
        hd = detector.horario(w15.loc[hora - pd.Timedelta(hours=HORAS_DETECTOR - 1):])
        det = modelos.detectar(hd, horas_det)

    pron = pron.set_index("nodo")
    det_ahora = det[det["fecha"] == hora].set_index("nodo")
    sobre = (det.pivot(index="fecha", columns="nodo", values="p_evento") >= modelos.umbral)
    pedidos = solicitud.sensores or modelos.sensores
    orden = {"verde": 0, "amarillo": 1, "rojo": 2}
    sensores = []
    for n in modelos.orden_sensores:
        if n not in pedidos:
            continue
        p = float(det_ahora["p_evento"].get(n, np.nan))
        actual = {par: _num(pron[f"base_{par}"].get(n)) for par in SALIDAS}
        futuro = {par: _num(pron[par].get(n)) for par in SALIDAS}
        fuera_ahora = [f"{par}: {fuera_de_norma(par, v)}" for par, v in actual.items() if fuera_de_norma(par, v)]
        fuera_24h = [f"{par}: {fuera_de_norma(par, v)}" for par, v in futuro.items() if fuera_de_norma(par, v)]
        horas_sobre = int(sobre[n].iloc[::-1].astype(int).cumprod().sum()) if n in sobre else 0
        sensores.append({
            "sensor": n,
            "nivel": nivel_riesgo(p, modelos.umbral, umbral_amarillo, fuera_ahora, fuera_24h),
            "probabilidad_evento": _num(p),
            "confianza": _num(max(p, 1 - p)) if p == p else None,
            "tipo_sugerido": carga.TIPOS_EVENTO.get(int(det_ahora["tipo"].get(n, 0)), "?"),
            "horas_sobre_umbral": horas_sobre,
            "alarma_confirmada": horas_sobre >= confirmar,
            "actual": actual,
            "pronostico_24h": futuro,
            "fuera_de_norma_ahora": fuera_ahora,
            "fuera_de_norma_24h": fuera_24h,
        })
    nivel_red = max((s["nivel"] for s in sensores), key=orden.get, default="verde")
    return {
        "hora_evaluada": str(hora),
        "fecha_pronosticada": str(hora + pd.Timedelta(hours=HORIZONTE_H)),
        "nivel_red": nivel_red,
        "sensores_en_riesgo": [s["sensor"] for s in sensores if s["nivel"] != "verde"],
        "criterios": {
            "rojo": f"probabilidad de evento ≥ {modelos.umbral}",
            "amarillo": f"probabilidad ≥ {umbral_amarillo}, o fuera de norma ahora o en {HORIZONTE_H} h",
            "alarma_confirmada": f"{confirmar} horas seguidas sobre el umbral (como en el dashboard)",
            "confianza": "certeza del detector en su respuesta: max(p, 1 - p)",
        },
        "version_modelos": modelos.version,
        "sensores": sensores,
        "duracion_ms": round((time.perf_counter() - t0) * 1000, 1),
    }


def guardar(carpeta, resultado):
    """Deja constancia de cada predicción pedida (una línea JSON por solicitud)."""
    if not carpeta:
        return
    resumen = {"solicitada": datetime.now().isoformat(timespec="seconds"),
               **{k: resultado[k] for k in ("hora_evaluada", "nivel_red", "sensores_en_riesgo", "duracion_ms")},
               "modelos": {k: v["sha256"] for k, v in resultado["version_modelos"].items()},
               "probabilidades": {s["sensor"]: s["probabilidad_evento"] for s in resultado["sensores"]}}
    with open(os.path.join(carpeta, "predicciones_api.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(resumen, ensure_ascii=False) + "\n")


def _num(x, dec=4):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return None if x != x else round(x, dec)
