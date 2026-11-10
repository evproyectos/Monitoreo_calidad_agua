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


def test_aviso_anticipado_se_abre_una_vez_y_se_cierra(tmp_path, cfg):
    from monitoreo.motor import HORAS_FIN_AVISO
    alto = {INICIO + pd.Timedelta(hours=k) for k in (6, 7, 8)}
    modelos = ModelosFalsos(p_anticipa=lambda h, k: 0.8 if h in alto else 0.1, eleccion={3: (0.5, 2), 2: (0.6, 1)})
    m = Motor(cfg, modelos, registrar=True)
    novedades = []
    for x in lecturas(10 + HORAS_FIN_AVISO):
        m.recibir(x["fecha"], x["valores"])
        novedades += m.procesar()
    avisos = [n for n in novedades if n["evento"] == "aviso_anticipado"]
    # tipo 3 confirma con 2 h (7:00); tipo 2 con 1 h (6:00)
    assert [(n["tipo"], n["hora"]) for n in avisos] == [("falla_cloro", str(INICIO + pd.Timedelta(hours=6))),
                                                        ("turbidez_fuente", str(INICIO + pd.Timedelta(hours=7)))]
    assert len(m.lista_avisos()) == 2 and not m.avisos_abiertos          # ya se cerraron
    terminados = sorted(n["tipo"] for n in novedades if n["evento"] == "aviso_terminado")
    assert terminados == ["falla_cloro", "turbidez_fuente"]
    r = m.resumen_anticipacion()
    assert {t["tipo"] for t in r["tipos"]} == {"turbidez_fuente", "falla_cloro"}
    assert not any(t["en_aviso"] for t in r["tipos"])
    assert m.estado()["anticipacion"] and m.estado()["avisos_anticipados_activos"] == []
    assert modelos.lluvia_mes is not None and len(m.lluvia_horaria) > 0
    sesion = list((tmp_path / "registros").iterdir())[0]
    reg = pd.read_csv(sesion / "anticipacion.csv")
    assert set(reg["tipo"]) == {"turbidez_fuente", "falla_cloro"} and reg["en_aviso"].sum() == 5


def test_anticipacion_a_48_h_se_muestra_sin_avisos_propios(cfg):
    alto = {INICIO + pd.Timedelta(hours=k) for k in (5, 6, 7)}
    modelos = ModelosFalsos(p_anticipa=lambda h, k: 0.1, p_anticipa_48h=lambda h, k: 0.8 if h in alto else 0.2,
                            eleccion_48h={3: (0.6, 2)})
    m = Motor(cfg, modelos, registrar=False)
    vistos, novedades = {}, []
    for x in lecturas(9):
        m.recibir(x["fecha"], x["valores"])
        novedades += m.procesar()
        r = m.resumen_anticipacion()
        if r["tipos"]:
            vistos[r["hora"]] = r["tipos"][0]["en_aviso_48h"]
    t = m.resumen_anticipacion()["tipos"][0]
    assert t["probabilidad"] == 0.1 and t["umbral_48h"] == 0.6
    # confirma con 2 h seguidas sobre 0,6: en aviso a las 6:00 y 7:00
    assert [h for h, en in vistos.items() if en] == [str(INICIO + pd.Timedelta(hours=k)) for k in (6, 7)]
    assert not [n for n in novedades if n["evento"] == "aviso_anticipado"]      # los avisos son de 24 h


def test_sin_modelo_de_anticipacion_no_hay_avisos(cfg):
    m = Motor(cfg, ModelosFalsos(), registrar=False)
    for x in lecturas(8):
        m.recibir(x["fecha"], x["valores"])
        m.procesar()
    assert m.lista_avisos() == [] and m.resumen_anticipacion() == {"hora": None, "tipos": []}
    assert m.estado()["anticipacion"] is False


def test_alarma_de_fuga_con_tramo(tmp_path, cfg):
    alto = {hora(k) for k in (5, 6, 7)}
    modelos = ModelosFalsos(p_fuga=lambda h: 0.9 if h in alto else 0.1)
    m = Motor(cfg, modelos, registrar=True)
    alimentar(m, 13)
    nov = [n for n in m.procesar() if n["evento"].startswith("fuga")]
    assert [(n["evento"], n["hora"]) for n in nov] == [("fuga_abierta", str(hora(6))), ("fuga_cerrada", str(hora(9)))]
    assert nov[0]["tramo"] == "J280 – J10" and nov[0]["caudal_residuo"] == 3.6
    f = m.lista_fugas()
    assert len(f) == 1 and f[0]["tramo"] == "J280 – J10" and f[0]["horas"] == 2 and f[0]["fin"] == str(hora(7))
    r = m.resumen_fugas()
    assert r["actual"]["en_alarma"] is False and len(r["serie"]) == 8 and sum(x["en_alarma"] for x in r["serie"]) == 2
    assert r["serie"][0]["riesgo"] == {"J280 – J10": 0.08, "J10 – J20": 0.02}          # 0,1 × 0,8 y 0,1 × 0,2
    assert m.estado()["fugas"] and not m.estado()["fuga_activa"]
    sesion = list((tmp_path / "registros").iterdir())[0]
    assert pd.read_csv(sesion / "fugas.csv")["en_alarma"].sum() == 2


def test_sin_modelo_de_fugas_y_sensores_de_mas_se_ignoran(cfg):
    m = Motor(cfg, ModelosFalsos(), registrar=False)
    for x in lecturas(8):
        m.recibir(x["fecha"], {**x["valores"], "CL2_J99": 0.5, "P_J99": 20.0, "TURB_J99": 0.4})
        m.procesar()
    assert m.lista_fugas() == [] and m.resumen_fugas()["actual"] is None
    assert "CL2_J99" in m.bufer and m.ultima_hora_procesada == hora(6)
    assert m.estado()["sensores"] == ModelosFalsos().sensores


def test_resultados_tambien_en_la_base_de_datos(tmp_path):
    from conftest import configuracion
    url = f"sqlite:///{tmp_path / 'monitoreo.db'}"
    alto = {hora(k) for k in (5, 6, 7)}
    modelos = ModelosFalsos(p_evento=lambda h, n: 0.95 if (n == "J10" and h in alto) else 0.1,
                            p_fuga=lambda h: 0.9 if h in alto else 0.1)
    m = Motor(configuracion(tmp_path, base_de_datos=url), modelos, registrar=True)
    alimentar(m, 13)
    m.procesar()
    assert m.base.contar("deteccion") == 12 * len(SENSORES) == m.base.contar("pronosticos")
    assert m.base.contar("alarmas") == 1 and m.base.contar("fugas") == 8
    fila = pd.read_sql("SELECT * FROM fugas ORDER BY fecha", m.base.motor).iloc[2]
    assert fila["sesion"].startswith("sesion_") and pd.Timestamp(fila["fecha"]) == hora(6) and fila["en_alarma"] == 1


def test_deriva_de_los_datos_cada_dia(cfg):
    from calidad_agua import deriva
    from conftest import tabla_lecturas
    ref_h = tabla_lecturas(80).resample("1h").mean()      # las mismas lecturas que llegan en vivo
    ref_h["CL2_J10"] += 0.3                                 # en el "entrenamiento" el cloro era más alto
    modelos = ModelosFalsos()
    modelos.deriva = {"referencia": deriva.referencia(ref_h), "periodo": "prueba"}
    m = Motor(cfg, modelos, registrar=False)
    nov = []
    for x in lecturas(80):
        m.recibir(x["fecha"], x["valores"])
        nov += m.procesar()
    derivas = [n for n in nov if n["evento"] == "deriva"]
    # cada día a las 06:00 desde el tercero (antes hay menos de 48 h de datos)
    assert [n["hora"] for n in derivas] == [str(hora(54)), str(hora(78))]
    assert [c for c, _ in derivas[0]["columnas"]] == ["CL2_J10"]
    estados = {c["columna"]: c["estado"] for c in m.ultima_deriva["columnas"]}
    assert estados["CL2_J10"] == "deriva" and estados["CL2_J280"] == "estable"


def test_en_vivo_el_preprocesamiento_usa_las_lecturas_que_llegan_despues(cfg):
    """La última lectura de una hora (xx:45) se revisa y se rellena con las de la hora siguiente."""
    vistos = []

    class Espia(ModelosFalsos):
        def detectar(self, hd, horas):
            vistos.append(hd.copy())
            return super().detectar(hd, horas)

    lec = lecturas(4)
    k = 2 * 4 + 3                                          # 02:45
    normal_turb = lec[k]["valores"]["TURB_J10"]
    lec[k]["valores"]["TURB_J10"] = normal_turb + 6.0      # pico de turbidez del sensor
    lec[k]["valores"]["CL2_J20"] = None                    # y una lectura de cloro que no llegó
    motor = Motor(cfg, Espia(), registrar=False)
    for x in lec[:k + 3]:                                  # hasta las 03:15: la hora 2 ya está cerrada
        motor.recibir(x["fecha"], x["valores"])
    motor.procesar()
    hd = vistos[-1]
    turb = [lec[2 * 4 + j]["valores"]["TURB_J10"] for j in range(3)]
    assert hd.loc[hora(2), "TURB_J10"] < max(turb) + 1      # el pico no entró al promedio de la hora
    assert hd.loc[hora(2), "lecturas_J20"] == 4             # el cloro faltante se interpoló
    assert motor.estado()["imputacion_ultimo_ciclo"].get("interpolado", 0) >= 1
