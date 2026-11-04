"""
Piezas comunes de las pruebas del servicio: lecturas sintéticas de una red pequeña y unos
modelos "de mentira" que dan pronósticos y probabilidades fijadas por la prueba. Así se prueban
el motor, las alarmas, las alertas y la API sin los modelos entrenados ni los datos reales.
"""

import os

import numpy as np
import pandas as pd
import pytest

os.environ["MONITOREO_SIN_ENV"] = "1"            # las pruebas no leen el .env de la máquina

from calidad_agua.red_neuronal import SALIDAS  # noqa: E402  (después de MONITOREO_SIN_ENV)
from monitoreo.config import Config  # noqa: E402  (después de MONITOREO_SIN_ENV)

SENSORES = ["J280", "J10", "J20"]                 # en el orden de la red (J280 es la fuente)
PARAMETROS = ["CL2", "TEMP", "TURB", "PH", "P"]
INICIO = pd.Timestamp("2026-05-01 00:00")


def tabla_lecturas(horas, inicio=INICIO, semilla=0):
    """Lecturas de 15 min con la forma que mandan los sensores (sin etiquetas)."""
    rng = np.random.default_rng(semilla)
    idx = pd.date_range(inicio, periods=horas * 4, freq="15min")
    ciclo = np.sin(2 * np.pi * (idx.hour.values + idx.minute.values / 60) / 24)
    t = pd.DataFrame(index=idx)
    for k, n in enumerate(SENSORES):
        t[f"CL2_{n}"] = 0.8 - 0.1 * k + 0.05 * ciclo + rng.normal(0, 0.01, len(idx))
        t[f"TEMP_{n}"] = 25 + ciclo + rng.normal(0, 0.1, len(idx))
        t[f"TURB_{n}"] = 0.5 + rng.normal(0, 0.02, len(idx))
        t[f"PH_{n}"] = 7.2 + rng.normal(0, 0.01, len(idx))
        t[f"P_{n}"] = 30 - 4 * k + rng.normal(0, 0.2, len(idx))
    t["Q_R1"] = 12 + ciclo
    t["lluvia_mm_h"] = 0.0
    return t


def lecturas(horas, inicio=INICIO, semilla=0):
    """Las mismas lecturas como las entrega la API de datos: [{"fecha", "valores"}, ...]."""
    t = tabla_lecturas(horas, inicio, semilla)
    return [{"fecha": f.isoformat(), "valores": {c: float(v) for c, v in fila.items()}}
            for f, fila in t.iterrows()]


class PronosticoFijo:
    descripcion = "pronóstico de prueba"
    error = None


class ModelosFalsos:
    """
    Misma interfaz que monitoreo.modelos.Modelos.
      p_evento(hora, nodo) -> probabilidad de evento (por defecto 0,05)
      pronostico_24h[nodo][parametro] -> valor pronosticado (por defecto, el valor actual)
    """

    def __init__(self, p_evento=None, pronostico_24h=None, p_anticipa=None, eleccion=None, tipo_evento=1):
        self.sensores = sorted(SENSORES)
        self.orden_sensores = list(SENSORES)
        self.umbral, self.confirmar_h, self.modo = 0.9, 2, "combinado"
        self.elegido = {"CL2": "arboles", "TURB": "combinado", "PH": "combinado"}
        self.tipicos = {(p, n): v for n in SENSORES for p, v in
                        [("CL2", 0.7), ("TURB", 0.5), ("PH", 7.2), ("TEMP", 25.0)]}
        self.pronostico = PronosticoFijo()
        self.version = {"pronostico": {"archivo": "pronostico.joblib", "sha256": "aaaaaaaaaaaa", "fecha": "2026-10-26"},
                        "detector": {"archivo": "detector.joblib", "sha256": "bbbbbbbbbbbb", "fecha": "2026-10-26"}}
        self.p_evento = p_evento or (lambda hora, nodo: 0.05)
        self.tipo_evento = tipo_evento                  # tipo que sugiere el detector (1 = contaminación)
        # anticipación: p_anticipa(hora, tipo) -> probabilidad; sin ella, el servicio no anticipa
        self.p_anticipa = p_anticipa
        self.anticipacion = None if p_anticipa is None else {
            "eleccion": eleccion or {3: (0.5, 1)},
            "retrasos_propagacion": pd.DataFrame({"mediana": [0.0, 2.0, 9.0]}, index=SENSORES)}
        self.pronostico_24h = pronostico_24h or {}
        self.llamadas = 0

    def pronosticar(self, h, horas):
        self.llamadas += 1
        filas = []
        for hora in horas:
            for n in SENSORES:
                fila = {"fecha": hora, "nodo": n, "fecha_pronosticada": hora + pd.Timedelta(hours=24)}
                for p in SALIDAS:
                    actual = float(h.loc[hora, f"{p}_{n}"])
                    fila[f"base_{p}"] = actual
                    fila[p] = self.pronostico_24h.get(n, {}).get(p, actual)
                filas.append(fila)
        return pd.DataFrame(filas)

    def anticipar(self, ha, horas, lluvia_mes=None):
        self.lluvia_mes = lluvia_mes
        tipos = list(self.anticipacion["eleccion"])
        return pd.DataFrame({k: [self.p_anticipa(h, k) for h in horas] for k in tipos}, index=pd.DatetimeIndex(horas))

    def detectar(self, hd, horas):
        filas = [{"fecha": hora, "nodo": n, "p_evento": self.p_evento(hora, n), "tipo": self.tipo_evento}
                 for hora in horas for n in SENSORES]
        return pd.DataFrame(filas)


def configuracion(tmp_path, **cambios):
    """Configuración con poca historia (4 h) para que las pruebas usen pocas lecturas."""
    valores = dict(url_datos="http://datos.prueba", carpeta_modelos=tmp_path, modo_pronostico="combinado",
                   carpeta_registros=tmp_path / "registros", historia_h=4, intervalo_consulta_s=0.02)
    valores.update(cambios)
    return Config(**valores)


@pytest.fixture
def cfg(tmp_path):
    return configuracion(tmp_path)
