"""API del servicio (servicio.py) de punta a punta, con el ciclo real y una API de datos falsa."""

import time

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from conftest import INICIO, SENSORES, ModelosFalsos, configuracion, lecturas
from monitoreo import servicio as srv
from monitoreo.motor import Motor

ULTIMA_HORA = str(INICIO + pd.Timedelta(hours=5))
CLAVE = "clave-de-prueba"


class DatosFalsos:
    """Hace de API de datos: entrega 7 horas de lecturas; con caida=True no responde."""

    def __init__(self, url):
        self.todas, self.caida = lecturas(7), False

    def lecturas_desde(self, desde=None):
        if self.caida:
            raise ConnectionError("la API de datos no responde")
        return [x for x in self.todas if desde is None or pd.Timestamp(x["fecha"]) > desde]


def esperar(cond, segundos=5):
    fin = time.time() + segundos
    while time.time() < fin and not cond():
        time.sleep(0.02)
    return cond()


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    monkeypatch.delenv("TELEGRAM_TOKEN", raising=False)
    monkeypatch.setenv("CLAVES_API", f"otra-clave, {CLAVE}")
    modelos = ModelosFalsos(p_evento=lambda h, n: 0.95 if n == "J10" and h >= INICIO + pd.Timedelta(hours=4) else 0.1,
                            p_fuga=lambda h: 0.8 if h >= INICIO + pd.Timedelta(hours=4) else 0.1)
    datos = []
    monkeypatch.setattr(srv, "Motor", lambda cfg: Motor(cfg, modelos, registrar=False))
    monkeypatch.setattr(srv, "ClienteDatos", lambda url: datos.append(DatosFalsos(url)) or datos[-1])
    with TestClient(srv.crear_app(configuracion(tmp_path)), headers={"X-API-Key": CLAVE}) as c:
        # el ciclo en segundo plano consulta los datos y procesa las horas cerradas
        assert esperar(lambda: c.get("/api/estado").json()["ultima_hora_procesada"] == ULTIMA_HORA)
        c.modelos, c.datos = modelos, datos[0]
        yield c


def test_health_ok_con_version_y_modelos(cliente):
    r = cliente.get("/health")
    assert r.status_code == 200
    d = r.json()
    assert d["estado"] == "ok" and d["problemas"] == [] and d["version"] == srv.__version__
    assert d["modelos"]["detector"]["sha256"] == "bbbbbbbbbbbb" and d["modelos"]["umbral_detector"] == 0.9
    assert d["conectado_a_datos"] is True and d["alertas"] == "consola"
    assert d["ultima_hora_procesada"] == ULTIMA_HORA


def test_health_degradado_si_falla_el_pronostico_de_lluvia(cliente):
    cliente.modelos.pronostico.error = "sin red"
    d = cliente.get("/health").json()
    assert d["estado"] == "degradado" and d["problemas"] == ["pronóstico de lluvia: sin red"]


def test_health_degradado_si_se_cae_la_api_de_datos(cliente):
    cliente.datos.caida = True
    assert esperar(lambda: cliente.get("/health").json()["estado"] == "degradado")
    assert "la API de datos no responde" in cliente.get("/health").json()["problemas"][0]
    assert cliente.get("/api/estado").json()["conectado_a_datos"] is False
    cliente.datos.caida = False
    assert esperar(lambda: cliente.get("/health").json()["estado"] == "ok")


def test_endpoints_del_dashboard(cliente):
    e = cliente.get("/api/estado").json()
    assert e["sensores"] == len(SENSORES) and e["sensores_en_alarma"] == 1 and e["alarma_abierta"]["id"] == 1
    sensores = cliente.get("/api/sensores").json()
    assert {s["nodo"] for s in sensores} == set(SENSORES)
    serie = cliente.get("/api/sensores/J10/serie", params={"horas": 6}).json()
    assert serie["ahora"] == ULTIMA_HORA and len(serie["puntos"]) == 30
    assert cliente.get("/api/sensores/J999/serie").status_code == 404
    red = cliente.get("/api/red/series", params={"horas": 6}).json()
    assert set(red["sensores"]) == set(SENSORES)
    alarmas = cliente.get("/api/alarmas").json()
    assert alarmas[0]["sensores"] == "J10" and alarmas[0]["fin"] is None
    ref = cliente.get("/api/referencias").json()
    assert ref["norma"]["CL2"]["minimo"] == 0.3 and ref["confirmar_h"] == 2
    assert cliente.get("/api/anticipacion").json() == {"disponible": False, "hora": None, "tipos": [], "avisos": []}


def test_predict_contaminacion(cliente):
    r = cliente.post("/predict/contaminacion", json={"lecturas": lecturas(7)})
    assert r.status_code == 200
    d = r.json()
    assert d["hora_evaluada"] == ULTIMA_HORA and d["nivel_red"] == "rojo" and d["sensores_en_riesgo"] == ["J10"]


def test_predict_contaminacion_responde_422_en_espanol(cliente):
    lec = lecturas(7)
    del lec[0]["valores"]["CL2_J20"]
    r = cliente.post("/predict/contaminacion", json={"lecturas": lec})
    assert r.status_code == 422
    assert r.json()["detail"]["error"].startswith("Faltan columnas")

    r = cliente.post("/predict/contaminacion", json={})
    assert r.status_code == 422
    assert r.json()["detail"] == {"error": "La solicitud no tiene el formato esperado.",
                                  "detalles": ["lecturas: falta este campo"]}

    lec = lecturas(7)
    lec[0]["valores"]["PH_J10"] = "siete"
    r = cliente.post("/predict/contaminacion", json={"lecturas": lec})
    assert r.json()["detail"]["detalles"] == ["lecturas.0.valores.PH_J10: debe ser un número o null"]

    r = cliente.post("/predict/contaminacion", content="no es json", headers={"Content-Type": "application/json"})
    assert r.status_code == 422 and "JSON" in r.json()["detail"]["detalles"][0]


def test_predict_contaminacion_pide_la_clave_de_api(cliente, tmp_path):
    r = cliente.post("/predict/contaminacion", json={"lecturas": lecturas(7)}, headers={"X-API-Key": ""})
    assert r.status_code == 401
    r = cliente.post("/predict/contaminacion", json={"lecturas": lecturas(7)}, headers={"X-API-Key": "otra"})
    assert r.status_code == 401
    assert cliente.get("/health").status_code == 200                # el resto no pide clave
    registro = (tmp_path / "registros" / "accesos_rechazados.log").read_text(encoding="utf-8")
    assert registro.count("POST /predict/contaminacion") == 2
    doc = cliente.get("/openapi.json").json()
    assert "X-API-Key" in str(doc["components"]["securitySchemes"])  # Swagger ofrece "Authorize"


def test_cortes_de_conexion_no_llenan_la_consola_de_errores():
    import asyncio
    loop = asyncio.new_event_loop()
    try:
        vistos = []
        loop.set_exception_handler(lambda lp, ctx: vistos.append(ctx["message"]))
        srv.silenciar_cortes(loop)
        loop.call_exception_handler({"message": "corte", "exception": ConnectionResetError(10054, "WinError")})
        loop.call_exception_handler({"message": "otro error", "exception": ValueError("x")})
        assert vistos == ["otro error"]
    finally:
        loop.close()


def test_fugas_en_el_dashboard_y_a_pedido(cliente):
    f = cliente.get("/api/fugas").json()
    assert f["disponible"] and f["hora"] == ULTIMA_HORA and f["actual"]["en_alarma"] is True
    assert f["actual"]["tramo"] == "J280 – J10" and f["fugas"][0]["fin"] is None
    assert f["tramos"] == ["J10 – J20", "J280 – J10"] and f["modelo"] == "Random Forest"
    r = cliente.post("/predict/fugas", json={"lecturas": lecturas(7)})
    assert r.status_code == 422 and "historia" in str(r.json())          # hacen falta 8 días
    r = cliente.post("/predict/fugas", json={"lecturas": lecturas(200, inicio=INICIO - pd.Timedelta(hours=193))})
    assert r.status_code == 200
    d = r.json()
    assert d["hora_evaluada"] == ULTIMA_HORA and d["nivel"] == "rojo" and d["alarma_confirmada"] is True
    assert d["tramo"] == "J280 – J10" and d["caudal_extra_Ls"] == 3.2 and d["horas_sobre_umbral"] == 2
    assert cliente.post("/predict/fugas", json={"lecturas": lecturas(2)}).status_code == 422
    assert cliente.post("/predict/fugas", json={"lecturas": lecturas(7)}, headers={"X-API-Key": "x"}).status_code == 401


def test_modelos_nuevos_se_cargan_sin_reiniciar(tmp_path, monkeypatch):
    modelos = ModelosFalsos()
    modelos.firma = ("a",)
    monkeypatch.setattr(srv, "Motor", lambda cfg: Motor(cfg, modelos, registrar=False))
    s = srv.Servicio(configuracion(tmp_path))
    monkeypatch.setattr(srv, "firma", lambda carpeta: ("a",))
    assert s.revisar_modelos() is False                     # nada cambió
    monkeypatch.setattr(srv, "firma", lambda carpeta: ("b",))
    nuevos = ModelosFalsos()
    monkeypatch.setattr(srv, "Modelos", lambda carpeta, modo: nuevos)
    assert s.revisar_modelos() is True and s.motor.modelos is nuevos and s.error_recarga is None
    assert s.recargas[-1]["modelos"]["detector"] == "bbbbbbbbbbbb"
    otros = ModelosFalsos()
    otros.sensores = ["J280"]
    nuevos.firma = ("b",)
    monkeypatch.setattr(srv, "firma", lambda carpeta: ("c",))
    monkeypatch.setattr(srv, "Modelos", lambda carpeta, modo: otros)
    assert s.revisar_modelos() is False and "otros sensores" in s.error_recarga and s.motor.modelos is nuevos

    def roto(carpeta, modo):
        raise RuntimeError("archivo a medio copiar")
    monkeypatch.setattr(srv, "Modelos", roto)
    assert s.revisar_modelos() is False and "medio copiar" in s.error_recarga


def test_deriva_sin_referencia(cliente):
    assert cliente.get("/api/deriva").json() == {"disponible": False}
