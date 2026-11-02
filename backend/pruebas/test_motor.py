"""Motor en vivo (motor.py): horas cerradas, calentamiento, alarmas de red y consultas."""

import pandas as pd

from conftest import INICIO, SENSORES, ModelosFalsos, lecturas
from monitoreo.motor import Motor


def hora(k):
    return INICIO + pd.Timedelta(hours=k)


def alimentar(motor, horas, desde=0):
    for lec in lecturas(horas)[desde * 4:]:
        motor.recibir(lec["fecha"], lec["valores"])


def test_una_hora_se_cierra_cuando_llega_la_siguiente(cfg):
    motor = Motor(cfg, ModelosFalsos(), registrar=False)
    assert len(motor.horas_pendientes()) == 0
    alimentar(motor, 3)                                  # 00:00 a 02:45
    assert list(motor.horas_pendientes()) == [hora(0), hora(1)]
    motor.procesar()
    assert motor.ultima_hora_procesada == hora(1)
    assert len(motor.horas_pendientes()) == 0 and motor.procesar() == []


def test_lecturas_repetidas_o_desordenadas_se_ignoran(cfg):
    motor = Motor(cfg, ModelosFalsos(), registrar=False)
    lec = lecturas(1)
    for x in lec + lec[:2]:
        motor.recibir(x["fecha"], x["valores"])
    assert motor.lecturas_recibidas == 4


def test_no_hay_alarmas_mientras_se_completa_la_historia(cfg):
    modelos = ModelosFalsos(p_evento=lambda h, n: 0.99)    # todo "en evento"
    motor = Motor(cfg, modelos, registrar=False)
    alimentar(motor, 5)
    motor.procesar()                                       # horas 0 a 3: historia incompleta (4 h)
    assert motor.alarma_abierta is None
    assert motor.tabla_pronosticos()["calentando"].all()
    alimentar(motor, 8, desde=5)
    nov = motor.procesar()                                 # horas 4 a 6
    assert [n["evento"] for n in nov] == ["alarma_abierta"]
    assert nov[0]["hora"] == str(hora(5))                  # 2 h seguidas sobre el umbral: 4 y 5


def test_alarma_de_red_se_abre_y_se_cierra(tmp_path, cfg):
    alto = {hora(k) for k in (5, 6, 7)}
    modelos = ModelosFalsos(p_evento=lambda h, n: 0.95 if (n == "J10" and h in alto) else 0.1)
    motor = Motor(cfg, modelos, registrar=True)
    alimentar(motor, 13)
    nov = motor.procesar()                                 # horas 0 a 11
    assert [(n["evento"], n["hora"]) for n in nov] == [("alarma_abierta", str(hora(6))),
                                                       ("alarma_cerrada", str(hora(9)))]
    a = motor.lista_alarmas()[0]
    assert a == {"id": 1, "inicio": str(hora(6)), "fin": str(hora(7)), "horas": 2, "sensores": "J10",
                 "tipo_sugerido": "contaminacion"}
    assert motor.matriz_alarmas()["J10"].sum() == 2
    # todo queda registrado en CSV
    sesion = list((tmp_path / "registros").iterdir())[0]
    assert {f.name for f in sesion.iterdir()} == {"pronosticos.csv", "deteccion.csv", "alarmas.csv"}
    assert len(pd.read_csv(sesion / "alarmas.csv")) == 1


def test_alarma_abierta_aparece_en_la_lista_sin_fin(cfg):
    motor = Motor(cfg, ModelosFalsos(p_evento=lambda h, n: 0.95 if h >= hora(5) else 0.1), registrar=False)
    alimentar(motor, 9)
    motor.procesar()
    abierta = motor.lista_alarmas()[-1]
    assert abierta["fin"] is None and abierta["sensores"] == ", ".join(sorted(SENSORES))
    assert motor.estado()["alarma_activa"] is True


def test_consultas_para_el_dashboard(cfg):
    modelos = ModelosFalsos(pronostico_24h={"J20": {"CL2": 0.25}})
    motor = Motor(cfg, modelos, registrar=False)
    assert motor.resumen_sensores() == [] and motor.serie_sensor("J10")["puntos"] == []
    assert motor.series_red()["sensores"] == {}
    alimentar(motor, 10)
    motor.procesar()                                       # horas 0 a 8
    resumen = {s["nodo"]: s for s in motor.resumen_sensores()}
    assert set(resumen) == set(SENSORES) and resumen["J20"]["pronostico_CL2"] == 0.25
    assert resumen["J10"]["hora"] == str(hora(8)) and resumen["J10"]["en_alarma"] is False
    serie = motor.serie_sensor("J20", horas=6)
    assert serie["ahora"] == str(hora(8)) and len(serie["puntos"]) == 6 + 24
    futuro = serie["puntos"][-1]
    assert futuro["CL2"] is None and futuro["pronostico_CL2"] == 0.25 and futuro["p_evento"] is None
    red = motor.series_red(horas=6)
    assert len(red["fechas"]) == 30 and len(red["sensores"]["J10"]["CL2"]) == 30
    e = motor.estado()
    assert e["ultima_hora_procesada"] == str(hora(8)) and e["lecturas_recibidas"] == 40
    assert e["pronostico_lluvia"] == "pronóstico de prueba" and e["confirmar_h"] == 2
