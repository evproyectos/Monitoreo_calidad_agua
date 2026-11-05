"""Predicción a pedido (prediccion.py): validación de la entrada (422) y armado de la respuesta."""

import json

import pandas as pd
import pytest

from conftest import INICIO, SENSORES, ModelosFalsos, lecturas
from monitoreo import prediccion
from monitoreo.prediccion import ErrorEntrada, SolicitudContaminacion

HISTORIA_H = 4


def solicitud(horas=7, **extra):
    return SolicitudContaminacion.model_validate({"lecturas": lecturas(horas), **extra})


def error_de(sol):
    with pytest.raises(ErrorEntrada) as e:
        prediccion.validar(sol, SENSORES, HISTORIA_H)
    return e.value


def test_columnas_esperadas_en_el_orden_de_la_red():
    cols = prediccion.columnas_esperadas(SENSORES)
    assert cols[:5] == ["CL2_J280", "TEMP_J280", "TURB_J280", "PH_J280", "P_J280"]
    assert cols[-2:] == ["Q_R1", "lluvia_mm_h"] and len(cols) == 5 * len(SENSORES) + 2


def test_solicitud_valida_evalua_la_ultima_hora_cerrada():
    ventana, hora = prediccion.validar(solicitud(7), SENSORES, HISTORIA_H)
    assert hora == INICIO + pd.Timedelta(hours=5)                  # la última lectura es de las 06:45
    assert ventana.index[0] == hora - pd.Timedelta(hours=HISTORIA_H) + pd.Timedelta(minutes=15)
    assert ventana.index[-1] == hora + pd.Timedelta(minutes=45)
    assert list(ventana.columns) == prediccion.columnas_esperadas(SENSORES)


def test_columnas_en_otro_orden_se_reordenan():
    lec = lecturas(7)
    for x in lec:
        x["valores"] = dict(reversed(list(x["valores"].items())))
    ventana, _ = prediccion.validar(SolicitudContaminacion.model_validate({"lecturas": lec}), SENSORES, HISTORIA_H)
    assert list(ventana.columns) == prediccion.columnas_esperadas(SENSORES)


def test_fechas_con_zona_horaria_se_pasan_a_hora_de_costa_rica():
    lec = lecturas(7)
    for x in lec:
        x["fecha"] = (pd.Timestamp(x["fecha"]) + pd.Timedelta(hours=6)).isoformat() + "+00:00"
    _, hora = prediccion.validar(SolicitudContaminacion.model_validate({"lecturas": lec}), SENSORES, HISTORIA_H)
    assert hora == INICIO + pd.Timedelta(hours=5)


def test_falta_una_columna():
    lec = lecturas(7)
    del lec[3]["valores"]["PH_J10"]
    e = error_de(SolicitudContaminacion.model_validate({"lecturas": lec}))
    assert "Faltan columnas" in e.error and "PH_J10" in e.detalles[0]


def test_historia_insuficiente():
    e = error_de(solicitud(4))
    assert "no alcanza la historia" in e.error and "faltan" in e.detalles[0]


def test_sensor_sin_ningun_dato_en_las_ultimas_24_h():
    lec = lecturas(7)
    for x in lec:
        x["valores"]["TURB_J20"] = None
    e = error_de(SolicitudContaminacion.model_validate({"lecturas": lec}))
    assert "TURB_J20 solo trae null" in e.detalles


def test_nulls_sueltos_se_aceptan():
    lec = lecturas(7)
    lec[10]["valores"]["CL2_J10"] = None
    prediccion.validar(SolicitudContaminacion.model_validate({"lecturas": lec}), SENSORES, HISTORIA_H)


def test_fechas_desordenadas_repetidas_o_fuera_de_los_15_min():
    lec = lecturas(7)
    lec[5], lec[6] = lec[6], lec[5]
    assert "orden" in error_de(SolicitudContaminacion.model_validate({"lecturas": lec})).error
    lec = lecturas(7)
    lec[8]["fecha"] = lec[7]["fecha"]
    assert "repetidas" in error_de(SolicitudContaminacion.model_validate({"lecturas": lec})).error
    lec = lecturas(7)
    lec[2]["fecha"] = (pd.Timestamp(lec[2]["fecha"]) + pd.Timedelta(minutes=7)).isoformat()
    assert "cada 15 min" in error_de(SolicitudContaminacion.model_validate({"lecturas": lec})).error


def test_hora_a_evaluar_sin_lecturas():
    lec = [x for x in lecturas(7) if not x["fecha"].startswith("2026-05-01T05")]
    e = error_de(SolicitudContaminacion.model_validate({"lecturas": lec}))
    assert "no hay lecturas en la hora" in e.error


def test_sensor_desconocido():
    e = error_de(solicitud(7, sensores=["J999"]))
    assert "J999 no es un sensor de la red" in e.detalles


@pytest.mark.parametrize("p, ahora, futuro, esperado", [
    (0.95, [], [], "rojo"),
    (0.6, [], [], "amarillo"),
    (0.1, ["CL2: mínimo 0,3"], [], "amarillo"),
    (0.1, [], ["PH: máximo 8,5"], "amarillo"),
    (0.1, [], [], "verde"),
    (float("nan"), [], [], "verde"),
])
def test_nivel_de_riesgo(p, ahora, futuro, esperado):
    assert prediccion.nivel_riesgo(p, 0.9, 0.5, ahora, futuro) == esperado


def test_respuesta_completa(tmp_path):
    hora = INICIO + pd.Timedelta(hours=5)
    modelos = ModelosFalsos(p_evento=lambda h, n: 0.95 if n == "J10" else 0.1,
                            pronostico_24h={"J20": {"CL2": 0.2}})
    r = prediccion.predecir(solicitud(7), modelos, HISTORIA_H, 0.5)
    assert r["hora_evaluada"] == str(hora) and r["fecha_pronosticada"] == str(hora + pd.Timedelta(hours=24))
    assert r["nivel_red"] == "rojo" and r["sensores_en_riesgo"] == ["J10", "J20"]
    s = {x["sensor"]: x for x in r["sensores"]}
    assert [x["sensor"] for x in r["sensores"]] == SENSORES
    assert s["J10"]["alarma_confirmada"] and s["J10"]["horas_sobre_umbral"] == 2
    assert s["J10"]["confianza"] == 0.95 and s["J10"]["tipo_sugerido"] == "contaminacion"
    assert s["J20"]["nivel"] == "amarillo" and s["J20"]["fuera_de_norma_24h"] == ["CL2: mínimo 0,3"]
    assert s["J280"]["nivel"] == "verde" and s["J280"]["pronostico_24h"]["CL2"] == s["J280"]["actual"]["CL2"]
    assert r["version_modelos"]["detector"]["sha256"] == "bbbbbbbbbbbb" and r["duracion_ms"] >= 0
    # solo los sensores pedidos
    uno = prediccion.predecir(solicitud(7, sensores=["J20"]), modelos, HISTORIA_H, 0.5)
    assert [x["sensor"] for x in uno["sensores"]] == ["J20"] and uno["nivel_red"] == "amarillo"
    # cada predicción queda anotada
    prediccion.guardar(tmp_path, r)
    prediccion.guardar(None, r)                            # sin carpeta de registros no hace nada
    linea = json.loads((tmp_path / "predicciones_api.jsonl").read_text(encoding="utf-8"))
    assert linea["nivel_red"] == "rojo" and linea["probabilidades"]["J10"] == 0.95
