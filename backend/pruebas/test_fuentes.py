"""Fuentes externas: pronóstico de lluvia (archivo y Open-Meteo), API de datos y configuración."""

import io
import json

import numpy as np
import pandas as pd
import pytest
import requests

from calidad_agua import clima
from monitoreo import pronostico_lluvia as pl
from monitoreo.cliente_datos import ClienteDatos
from monitoreo.config import Config


def archivo_pronostico(ruta, horas=72, mm=1.0):
    idx = pd.date_range("2026-05-01", periods=horas, freq="1h")
    cab = "time," + ",".join(f"precipitation_previous_day1_{m} (mm)" for m in clima.MODELOS)
    filas = [f"{f:%Y-%m-%dT%H:%M}," + ",".join([str(mm)] * len(clima.MODELOS)) for f in idx]
    ruta.write_text("latitude,longitude\n10.36,-84.51\n\n" + cab + "\n" + "\n".join(filas), encoding="utf-8")
    return ruta


def test_pronostico_desde_archivo(tmp_path):
    p = pl.PronosticoArchivo(archivo_pronostico(tmp_path / "p.csv"))
    v = p.ventanas(pd.date_range("2026-05-01", periods=3, freq="1h"))
    assert v.iloc[0].tolist() == [6.0, 6.0, 12.0]


class RespuestaOpenMeteo(io.BytesIO):
    def __init__(self, mm, horas=48):
        idx = pd.date_range("2026-05-01", periods=horas, freq="1h")
        datos = {"time": [f"{f:%Y-%m-%dT%H:%M}" for f in idx]}
        for k, m in enumerate(clima.MODELOS):
            datos[f"precipitation_{m}"] = [mm + k] * horas          # 1, 2, 3, 4 → promedio 2,5
        super().__init__(json.dumps({"hourly": datos}).encode())


def test_open_meteo_promedia_los_modelos_y_consulta_cada_hora(monkeypatch):
    consultas = []
    monkeypatch.setattr(pl.urllib.request, "urlopen",
                        lambda url, timeout: consultas.append(url) or RespuestaOpenMeteo(1.0))
    p = pl.PronosticoOpenMeteo()
    horas = pd.date_range("2026-05-01", periods=2, freq="1h")
    v = p.ventanas(horas)
    assert v.iloc[0]["lluvia_pron_0_6h"] == pytest.approx(6 * 2.5)
    assert "models=" + ",".join(clima.MODELOS) in consultas[0] and "America%2FCosta_Rica" in consultas[0]
    p.ventanas(horas)
    assert len(consultas) == 1                                       # no vuelve a consultar antes de una hora
    p.consultado -= 3600
    p.ventanas(horas)
    assert len(consultas) == 2 and p.error is None


def test_open_meteo_sin_red_sigue_con_el_ultimo_pronostico(monkeypatch):
    def sin_red(url, timeout):
        raise OSError("sin conexión")
    monkeypatch.setattr(pl.urllib.request, "urlopen", sin_red)
    p = pl.PronosticoOpenMeteo()
    v = p.ventanas(pd.date_range("2026-05-01", periods=2, freq="1h"))
    assert np.isnan(v.values).all() and "sin conexión" in p.error
    monkeypatch.setattr(pl.urllib.request, "urlopen", lambda url, timeout: RespuestaOpenMeteo(0.0))
    p.consultado = 0
    p.serie = None
    p.ventanas(pd.date_range("2026-05-01", periods=2, freq="1h"))
    assert p.error is None
    monkeypatch.setattr(pl.urllib.request, "urlopen", sin_red)
    p.consultado = 0
    v = p.ventanas(pd.date_range("2026-05-01", periods=2, freq="1h"))
    assert v.iloc[0]["lluvia_pron_0_6h"] == pytest.approx(6 * 1.5) and p.error   # conserva el anterior


def test_fuente_segun_variable_de_entorno(tmp_path, monkeypatch):
    monkeypatch.setenv("PRONOSTICO_LLUVIA", str(archivo_pronostico(tmp_path / "p.csv")))
    monkeypatch.setenv("FUENTE_PRONOSTICO", "archivo")
    assert isinstance(pl.desde_entorno(), pl.PronosticoArchivo)
    monkeypatch.setenv("FUENTE_PRONOSTICO", "open-meteo")
    assert isinstance(pl.desde_entorno(), pl.PronosticoOpenMeteo)
    monkeypatch.setenv("FUENTE_PRONOSTICO", "otra")
    with pytest.raises(ValueError, match="FUENTE_PRONOSTICO"):
        pl.desde_entorno()


class RespuestaJSON:
    def __init__(self, datos, codigo=200):
        self.datos, self.codigo = datos, codigo

    def json(self):
        return self.datos

    def raise_for_status(self):
        if self.codigo >= 400:
            raise requests.HTTPError(str(self.codigo))


def test_cliente_pide_de_a_5000_hasta_ponerse_al_dia(monkeypatch):
    c = ClienteDatos("http://datos.prueba/")
    pedidos = []
    lote = [{"fecha": "2026-05-01T00:00:00", "valores": {}}] * 4999 + [{"fecha": "2026-05-02T10:00:00", "valores": {}}]

    def get(url, params=None, timeout=None):
        pedidos.append((url, params))
        return RespuestaJSON(lote if len(pedidos) == 1 else lote[:3])
    monkeypatch.setattr(c.s, "get", get)
    todas = c.lecturas_desde(pd.Timestamp("2026-05-01"))
    assert len(todas) == 5003
    assert pedidos[0] == ("http://datos.prueba/lecturas", {"desde": "2026-05-01T00:00:00"})
    assert pedidos[1][1] == {"desde": "2026-05-02T10:00:00"}
    pedidos.clear()
    c.lecturas_desde(None)
    assert pedidos[0][1] == {}


def test_cliente_disponible(monkeypatch):
    c = ClienteDatos("http://datos.prueba")
    monkeypatch.setattr(c.s, "get", lambda url, timeout: RespuestaJSON({}))
    assert c.disponible()
    monkeypatch.setattr(c.s, "get", lambda url, timeout: RespuestaJSON({}, 500))
    assert not c.disponible()


def test_configuracion_desde_variables_de_entorno(monkeypatch, tmp_path):
    monkeypatch.setenv("URL_DATOS", "http://otra:9000")
    monkeypatch.setenv("MODO_PRONOSTICO", "arboles")
    monkeypatch.setenv("CARPETA_REGISTROS", str(tmp_path))
    monkeypatch.setenv("UMBRAL_AMARILLO", "0.4")
    c = Config()
    assert (c.url_datos, c.modo_pronostico, c.carpeta_registros, c.umbral_amarillo) == \
        ("http://otra:9000", "arboles", tmp_path, 0.4)
    monkeypatch.setenv("MODO_PRONOSTICO", "lstm")
    with pytest.raises(ValueError, match="MODO_PRONOSTICO"):
        Config()
