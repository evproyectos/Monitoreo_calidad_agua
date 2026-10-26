"""
Carga de los modelos entrenados en el proyecto Modelo_calidad_agua (notebooks 07 y 08) y
cálculo de pronósticos y probabilidades de evento a partir de tablas horarias.

Las variables se arman con las MISMAS funciones del paquete calidad_agua que se usaron al
entrenar; aquí solo se aplican los modelos. Los árboles del pronóstico usan además la lluvia
pronosticada para las próximas 24 h (monitoreo.pronostico_lluvia).
"""

import os
import numpy as np
import pandas as pd
import joblib

from calidad_agua import variables, detector, red_neuronal as rn, modelo as arboles_
from calidad_agua.red_neuronal import SALIDAS

from monitoreo import pronostico_lluvia

PISO_LOG = 0.05


class Modelos:
    def __init__(self, carpeta, modo="combinado", pronostico=None):
        carpeta = os.fspath(carpeta)
        ruta_p = os.path.join(carpeta, "pronostico_24h_final.joblib")
        ruta_d = os.path.join(carpeta, "detector_eventos.joblib")
        for r in (ruta_p, ruta_d):
            if not os.path.exists(r):
                raise FileNotFoundError(
                    f"No se encontró {r}. Corre los notebooks 07 y 08 del proyecto Modelo_calidad_agua.")
        p = joblib.load(ruta_p)
        d = joblib.load(ruta_d)
        self.modo = modo
        self.arboles = p["arboles"]
        self.columnas = p["columnas"]
        self.tipicos = p["tipicos"]
        self.normalizacion = p["normalizacion"]
        if "anio_sin" in self.columnas or "pronostico_lluvia" not in p:
            raise RuntimeError(
                f"Los modelos de {carpeta} son de una versión anterior (sin pronóstico de lluvia). "
                "Vuelve a correr los notebooks 07 y 08 del proyecto Modelo_calidad_agua.")
        self.opciones_lstm = p.get("lstm_opciones", {"epoca": False, "pronostico": False})
        # fuente del pronóstico de lluvia (por defecto, según FUENTE_PRONOSTICO)
        self.pronostico = pronostico or pronostico_lluvia.desde_entorno()
        # modelo por parámetro elegido en validación; sin TensorFlow todo se hace con árboles
        self.elegido = dict(p["elegido"]) if modo == "combinado" else {k: "arboles" for k in SALIDAS}
        self.redes = []
        if any(v in ("lstm", "combinado") for v in self.elegido.values()):
            import keras                                   # solo se importa TensorFlow si hace falta
            import tensorflow as tf
            tf.get_logger().setLevel("ERROR")              # avisos de "retracing" sin importancia
            self.redes = [keras.models.load_model(os.path.join(carpeta, f), compile=False)
                          for f in p["redes"]]
        self.detector = d["modelo"]
        self.columnas_detector = d["columnas"]
        self.tipicos_detector = d["tipicos"]
        self.umbral = d["umbral"]
        self.confirmar_h = d["confirmar_h"]
        self.sensores = list(d["sensores"])

    # ------------------------------------------------------------------ pronóstico
    def pronosticar(self, h, horas):
        """
        Pronóstico a 24 h para cada sensor en cada hora de `horas` (deben estar en `h`, la tabla
        horaria de variables.horario). Devuelve una fila por (hora, sensor) con el pronóstico de
        CL2, TURB y PH para hora + 24 h y el valor actual (línea base).
        """
        lluvia_pron = self.pronostico.ventanas(h.index)
        tabla, _ = variables.tabla(h, tipicos=self.tipicos, pronostico=lluvia_pron)
        tabla = tabla[tabla["fecha"].isin(horas)].reset_index(drop=True)
        out = tabla[["fecha", "nodo"]].copy()
        for p in SALIDAS:
            out[f"base_{p}"] = tabla[p].values
            out[f"arboles_{p}"] = arboles_.pronosticar(self.arboles[p], tabla, p, self.columnas)

        if self.redes:
            datos = rn.preparar(h, self.tipicos, normalizacion=self.normalizacion,
                                epoca=self.opciones_lstm.get("epoca", False),
                                pronostico=lluvia_pron if self.opciones_lstm.get("pronostico") else None)
            pos = {f: i for i, f in enumerate(datos["fechas"])}
            sens = {n: i for i, n in enumerate(datos["sensores"])}
            idx = np.array([[sens[n], pos[f]] for f, n in zip(out["fecha"], out["nodo"])])
            completa = idx[:, 1] >= rn.VENTANA_H - 1                 # hace falta la ventana de 48 h
            lstm = np.full((len(out), len(SALIDAS)), np.nan)
            if completa.any():
                lstm[completa] = np.mean([rn.pronosticar(r, datos, idx[completa]) for r in self.redes], axis=0)
            for k, p in enumerate(SALIDAS):
                out[f"lstm_{p}"] = lstm[:, k]

        for p in SALIDAS:
            cual = self.elegido[p]
            if cual == "arboles":
                out[p] = out[f"arboles_{p}"]
            elif cual == "lstm":
                out[p] = out[f"lstm_{p}"]
            elif p == "TURB":                        # combinación en escala logarítmica (notebook 08)
                out[p] = np.exp((np.log(np.clip(out[f"arboles_{p}"], PISO_LOG, None)) +
                                 np.log(np.clip(out[f"lstm_{p}"], PISO_LOG, None))) / 2)
            else:
                out[p] = (out[f"arboles_{p}"] + out[f"lstm_{p}"]) / 2
        out["fecha_pronosticada"] = out["fecha"] + pd.Timedelta(hours=rn.HORIZONTE_H)
        return out

    # ------------------------------------------------------------------ detector
    def detectar(self, hd, horas):
        """Probabilidad de evento y tipo más probable por (hora, sensor). `hd` = detector.horario."""
        tabla, _ = detector.tabla(hd, tip=self.tipicos_detector)
        tabla = tabla[tabla["fecha"].isin(horas)].reset_index(drop=True)
        p_evento, tipo = detector.probabilidades(self.detector, tabla, self.columnas_detector)
        return pd.DataFrame({"fecha": tabla["fecha"], "nodo": tabla["nodo"],
                             "p_evento": p_evento, "tipo": tipo})
