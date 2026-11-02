"""
Carga y uso de los modelos (modelos.py) con modelos de árboles pequeños entrenados aquí mismo
con las funciones de calidad_agua (sin LSTM, para no depender de los archivos entrenados).
"""

import joblib
import numpy as np
import pandas as pd
import pytest

from calidad_agua import calidad, clima, detector, modelo, variables
from conftest import SENSORES, tabla_lecturas
from monitoreo import modelos as mod_modelos
from monitoreo.modelos import Modelos


class PronosticoConstante:
    descripcion = "lluvia constante"
    error = None

    def ventanas(self, horas):
        s = pd.Series(0.2, index=pd.date_range(horas.min(), horas.max() + pd.Timedelta(hours=30), freq="1h"))
        return clima.ventanas(s, horas)


@pytest.fixture(scope="module")
def carpeta(tmp_path_factory):
    """Modelos guardados con la misma estructura que los notebooks 07 y 08."""
    carpeta = tmp_path_factory.mktemp("modelos")
    t = tabla_lecturas(24 * 6)
    for n in SENSORES:
        t[f"evento_{n}"] = 0
    t.loc[t.index[300:340], "evento_J10"] = 1
    t.loc[t.index[300:340], "CL2_J10"] -= 0.4
    t["particion"] = "entrenamiento"
    w = calidad.lecturas_operativas(t)

    h = variables.horario(w)
    pron = PronosticoConstante().ventanas(h.index)
    tabla, tipicos = variables.tabla(h, pronostico=pron)
    cols = variables.columnas_entrada(tabla)
    filas = tabla["particion"] == "entrenamiento"
    arboles = {p: modelo.entrenar(tabla, p, cols, filas) for p in ["CL2", "TURB", "PH"]}
    joblib.dump({"arboles": arboles, "columnas": cols, "tipicos": tipicos, "normalizacion": None,
                 "elegido": {"CL2": "arboles", "TURB": "combinado", "PH": "combinado"},
                 "pronostico_lluvia": {"modelos": clima.MODELOS, "columnas": clima.COLUMNAS}, "redes": []},
                carpeta / "pronostico_24h_final.joblib")

    hd = detector.horario(w)
    td, tip = detector.tabla(hd)
    cd = detector.columnas_entrada(td)
    joblib.dump({"modelo": detector.entrenar(td, cd, td["particion"] == "entrenamiento"), "columnas": cd,
                 "tipicos": tip, "umbral": 0.9, "confirmar_h": 2, "sensores": sorted(SENSORES)},
                carpeta / "detector_eventos.joblib")
    return carpeta


def test_huella_identifica_el_archivo(tmp_path):
    f = tmp_path / "m.joblib"
    f.write_bytes(b"modelo")
    h = mod_modelos.huella(f)
    assert h["archivo"] == "m.joblib" and len(h["sha256"]) == 12 and h["fecha"][:2] == "20"
    f.write_bytes(b"otro modelo")
    assert mod_modelos.huella(f)["sha256"] != h["sha256"]


def test_sin_modelos_dice_que_notebooks_correr(tmp_path):
    with pytest.raises(FileNotFoundError, match="notebooks 07 y 08"):
        Modelos(tmp_path, pronostico=PronosticoConstante())


def test_modelos_de_una_version_anterior(tmp_path, carpeta):
    viejo = joblib.load(carpeta / "pronostico_24h_final.joblib")
    del viejo["pronostico_lluvia"]
    joblib.dump(viejo, tmp_path / "pronostico_24h_final.joblib")
    (tmp_path / "detector_eventos.joblib").write_bytes((carpeta / "detector_eventos.joblib").read_bytes())
    with pytest.raises(RuntimeError, match="versión anterior"):
        Modelos(tmp_path, pronostico=PronosticoConstante())


def test_carga_orden_y_version(carpeta):
    m = Modelos(carpeta, modo="arboles", pronostico=PronosticoConstante())
    assert m.orden_sensores == SENSORES and m.sensores == sorted(SENSORES)
    assert m.elegido == {"CL2": "arboles", "TURB": "arboles", "PH": "arboles"} and m.redes == []
    assert set(m.version) == {"pronostico", "detector"} and m.umbral == 0.9


def test_pronostico_y_deteccion_de_una_hora(carpeta):
    m = Modelos(carpeta, modo="arboles", pronostico=PronosticoConstante())
    w = calidad.lecturas_operativas(tabla_lecturas(30))
    hora = pd.Timestamp("2026-05-02 04:00")
    pron = m.pronosticar(variables.horario(w), pd.DatetimeIndex([hora]))
    assert len(pron) == len(SENSORES) and (pron["fecha_pronosticada"] == hora + pd.Timedelta(hours=24)).all()
    assert pron[["CL2", "TURB", "PH"]].notna().all().all()
    np.testing.assert_allclose(pron["CL2"], pron["arboles_CL2"])
    det = m.detectar(detector.horario(w), pd.DatetimeIndex([hora]))
    assert set(det["nodo"]) == set(SENSORES) and det["p_evento"].between(0, 1).all()
