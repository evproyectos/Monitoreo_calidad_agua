"""Fuentes de la lluvia observada (fuentes_lluvia.py, RNF-009)."""

import io
import json
import urllib.parse

import pandas as pd
import pytest

from monitoreo import fuentes_lluvia as fl
from monitoreo import servicio as srv

AHORA = pd.Timestamp("2026-11-12 14:05").tz_localize("America/Costa_Rica").timestamp()


class OpenMeteoFalso:
    """Responde como Open-Meteo: lluvia horaria = la hora del día / 10 (y 'llueve más' en GFS)."""

    def __init__(self, falla=0):
        self.urls, self.falla = [], falla

    def __call__(self, url, timeout):
        self.urls.append(url)
        if self.falla:
            self.falla -= 1
            raise OSError("sin red")
        q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        horas = pd.date_range(q["start_date"][0], pd.Timestamp(q["end_date"][0]) + pd.Timedelta(hours=23), freq="h")
        modelos = q["models"][0].split(",")
        hourly = {"time": [f"{h:%Y-%m-%dT%H:%M}" for h in horas]}
        for m in modelos:
            clave = "precipitation" if len(modelos) == 1 else f"precipitation_{m}"
            hourly[clave] = [h.hour / 10 + (1 if m == "gfs_seamless" else 0) for h in horas]
        return io.BytesIO(json.dumps({"hourly": hourly}).encode())


def fuente(modelos="ecmwf_ifs025", **kw):
    abrir = OpenMeteoFalso(**kw)
    return fl.LluviaOpenMeteo(modelos, abrir=abrir, dormir=lambda s: None, reloj=lambda: AHORA), abrir


def test_open_meteo_un_modelo_y_promedio():
    f, _ = fuente()
    s = f.lluvia("2026-11-12 08:10", "2026-11-12 10:50")
    assert list(s.index.hour) == [8, 9, 10] and list(s) == pytest.approx([0.8, 0.9, 1.0])
    f2, _ = fuente("ecmwf_ifs025,gfs_seamless")
    assert f2.lluvia("2026-11-12 08:00", "2026-11-12 08:00").iloc[0] == pytest.approx(1.3)   # (0,8 + 1,8) / 2


def test_reciente_o_historica_y_sin_pedir_dos_veces():
    f, om = fuente()
    f.lluvia("2026-11-12 00:00", "2026-11-12 12:00")
    f.lluvia("2026-11-12 03:00", "2026-11-12 11:45")          # ya las tiene: no consulta
    assert len(om.urls) == 1 and om.urls[0].startswith(fl.LluviaOpenMeteo.URL_RECIENTE)
    f.lluvia("2026-05-03 10:00", "2026-05-03 12:00")           # fechas del simulador: más de 90 días
    assert om.urls[1].startswith(fl.LluviaOpenMeteo.URL_HISTORICA)


def test_no_guarda_horas_que_todavia_no_pasan():
    f, om = fuente()
    s = f.lluvia("2026-11-12 13:00", "2026-11-12 15:00")       # son las 14:05
    assert s.loc["2026-11-12 14:00"] == pytest.approx(1.4) and pd.isna(s.loc["2026-11-12 15:00"])
    s = f.lluvia("2026-11-12 13:00", "2026-11-12 15:00")       # la de las 15 no se vuelve a pedir enseguida
    assert len(om.urls) == 1


def test_sin_red_reintenta_y_luego_espera_10_minutos():
    f, om = fuente(falla=4)
    s = f.lluvia("2026-11-12 08:00", "2026-11-12 09:00")
    assert s.isna().all() and "sin red" in f.error and len(om.urls) == 4   # 4 intentos (reintentos.py)
    f.lluvia("2026-11-12 08:00", "2026-11-12 09:00")
    assert len(om.urls) == 4                                   # no insiste en cada ciclo
    f.reloj = lambda: AHORA + 601
    assert list(f.lluvia("2026-11-12 08:00", "2026-11-12 09:00")) == pytest.approx([0.8, 0.9])
    assert f.error is None


class Datos:
    def __init__(self, lecturas):
        self.lecturas, self.otro = lecturas, "x"

    def lecturas_desde(self, desde=None):
        return self.lecturas


def test_con_lluvia_pone_la_de_la_hora_que_termino():
    lecturas = [{"fecha": f"2026-11-12 {h}", "valores": {"CL2_J10": 0.7, "lluvia_mm_h": 9.0}}
                for h in ("09:45", "10:00", "10:15", "10:45")]
    f, _ = fuente()
    c = fl.ConLluvia(Datos(lecturas), f)
    r = c.lecturas_desde()
    assert [x["valores"]["lluvia_mm_h"] for x in r] == pytest.approx([0.9, 1.0, 1.0, 1.0])
    assert r[0]["valores"]["CL2_J10"] == 0.7 and lecturas[0]["valores"]["lluvia_mm_h"] == 9.0   # no cambia el original
    assert c.otro == "x"                                       # lo demás pasa al cliente
    assert fl.ConLluvia(Datos(lecturas), fl.LluviaDeLecturas()).lecturas_desde() is lecturas


def test_sin_lluvia_queda_vacia():
    f, _ = fuente(falla=99)
    r = fl.ConLluvia(Datos([{"fecha": "2026-11-12 10:00", "valores": {}}]), f).lecturas_desde()
    assert r[0]["valores"]["lluvia_mm_h"] is None              # el motor la toma como faltante


def test_desde_entorno(monkeypatch):
    monkeypatch.delenv("FUENTE_LLUVIA", raising=False)
    assert isinstance(fl.desde_entorno(), fl.LluviaDeLecturas)
    monkeypatch.setenv("FUENTE_LLUVIA", "open-meteo")
    monkeypatch.setenv("LLUVIA_MODELOS", "best_match")
    f = fl.desde_entorno()
    assert isinstance(f, fl.LluviaOpenMeteo) and f.modelos == ["best_match"]
    monkeypatch.setenv("FUENTE_LLUVIA", "imn")
    with pytest.raises(ValueError, match="lecturas, open-meteo"):
        fl.desde_entorno()


def test_una_fuente_nueva_es_solo_una_clase(monkeypatch, tmp_path):
    """RNF-009: otra fuente se agrega con un adaptador; el servicio y el motor no cambian."""
    from conftest import ModelosFalsos, configuracion, lecturas
    from monitoreo.motor import Motor

    class Pluviometro(fl.FuenteLluvia):
        nombre, descripcion = "pluviometro", "pluviómetro de la ASADA (prueba)"

        def lluvia(self, desde, hasta):
            horas = pd.date_range(pd.Timestamp(desde).floor("h"), pd.Timestamp(hasta).floor("h"), freq="h")
            return pd.Series(3.0, index=horas)

    monkeypatch.setitem(fl.FUENTES, "pluviometro", Pluviometro)
    monkeypatch.setenv("FUENTE_LLUVIA", "pluviometro")
    datos = lecturas(10)
    for x in datos:
        x["valores"].pop("lluvia_mm_h", None)                  # los sensores no miden lluvia
    monkeypatch.setattr(srv, "Motor", lambda cfg: Motor(cfg, ModelosFalsos(), registrar=False))
    monkeypatch.setattr(srv, "ClienteDatos", lambda url: Datos(datos))
    s = srv.Servicio(configuracion(tmp_path))
    s.paso()
    assert s.fuente_lluvia.nombre == "pluviometro"
    assert (s.motor.bufer["lluvia_mm_h"] == 3.0).all()
