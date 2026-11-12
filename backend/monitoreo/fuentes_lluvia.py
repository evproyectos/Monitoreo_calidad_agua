"""
Fuente de la lluvia observada (RNF-009): adaptadores de la capa de ingesta.

Los tres modelos usan la lluvia que cayó (columna `lluvia_mm_h` de las lecturas): el detector la de
las últimas horas, las fugas la de 24 h y la anticipación la de 30 días. Los sensores de la red no
la miden; en el dataset viene de la estación 69-701 del IMN (ITCR, San Carlos), que el simulador
mete en las lecturas. En operación sale de la fuente que se elija con FUENTE_LLUVIA:

  lecturas    (por defecto) la lluvia viene en las mismas lecturas, como la manda el simulador o la
              mandaría un pluviómetro de la ASADA. No se consulta nada.
  open-meteo  se consulta Open-Meteo para la hora de cada lectura: la Forecast API para los últimos
              90 días (lo que pasa en operación) y la Historical Forecast API para fechas más viejas
              (las del simulador). Las dos dan el mismo producto: las primeras horas de cada
              pronóstico, en el punto de la estación. Modelos meteorológicos: LLUVIA_MODELOS (el
              promedio, si son varios); la comparación con el IMN y el efecto en los modelos están en
              Modelo_calidad_agua/docs/modelos/fuente-lluvia.md.

Convención (la misma de lluvia_mm_h y de Open-Meteo): el valor horario de las 14:00 es la lluvia
de 13:00 a 14:00, y va en las lecturas de las 14:00 a las 14:45.

Agregar otra fuente (otra API, una estación propia) es escribir una clase con el método
`lluvia(desde, hasta)`, que devuelve la lluvia horaria en mm con esa convención, y registrarla en
FUENTES. No se toca nada más: ni el servicio, ni el motor, ni los modelos.
"""

import json
import os
import time
import urllib.parse
import urllib.request

import numpy as np
import pandas as pd

from monitoreo.pronostico_lluvia import LATITUD, LONGITUD
from monitoreo.reintentos import reintentar

COLUMNA = "lluvia_mm_h"
MODELOS_OPEN_METEO = "ecmwf_ifs025"             # el que mejor coincide con la estación del IMN


class FuenteLluvia:
    """Interfaz de un adaptador: la lluvia horaria (mm) de las horas desde..hasta."""

    nombre = descripcion = ""
    error = None

    def lluvia(self, desde, hasta):
        raise NotImplementedError

    def estado(self):
        return {"fuente": self.nombre, "descripcion": self.descripcion, "error": self.error}


class LluviaDeLecturas(FuenteLluvia):
    nombre, descripcion = "lecturas", "la lluvia viene en las lecturas (simulador o pluviómetro)"


class LluviaOpenMeteo(FuenteLluvia):
    nombre = "open-meteo"
    URL_RECIENTE = "https://api.open-meteo.com/v1/forecast"
    URL_HISTORICA = "https://historical-forecast-api.open-meteo.com/v1/forecast"
    DIAS_RECIENTES = 90
    REINTENTAR_S = 600                   # una hora que no se pudo conseguir se vuelve a pedir en 10 min

    def __init__(self, modelos=MODELOS_OPEN_METEO, latitud=LATITUD, longitud=LONGITUD,
                 abrir=urllib.request.urlopen, dormir=time.sleep, reloj=time.time):
        self.modelos = [m.strip() for m in modelos.split(",") if m.strip()] if isinstance(modelos, str) \
            else list(modelos)
        self.latitud, self.longitud = latitud, longitud
        self.abrir, self.dormir, self.reloj = abrir, dormir, reloj
        self.descripcion = f"Open-Meteo ({', '.join(self.modelos)})"
        self.serie = pd.Series(dtype="float32")
        self._pedidas = {}               # hora -> cuándo se pidió sin conseguirla
        self.consultas = 0

    def _url(self, inicio, fin):
        hoy = pd.Timestamp(self.reloj(), unit="s").normalize()
        base = self.URL_RECIENTE if inicio >= hoy - pd.Timedelta(days=self.DIAS_RECIENTES) else self.URL_HISTORICA
        params = {"latitude": self.latitud, "longitude": self.longitud, "hourly": "precipitation",
                  "models": ",".join(self.modelos), "timezone": "America/Costa_Rica",
                  "start_date": f"{inicio:%Y-%m-%d}", "end_date": f"{fin:%Y-%m-%d}"}
        return f"{base}?{urllib.parse.urlencode(params)}"

    def _consultar(self, inicio, fin):
        url = self._url(inicio, fin)

        def pedir():
            with self.abrir(url, timeout=20) as r:
                return json.load(r)["hourly"]
        datos = reintentar(pedir, nombre="la consulta de lluvia a Open-Meteo", dormir=self.dormir)
        self.consultas += 1
        columnas = {m: datos.get(f"precipitation_{m}", datos.get("precipitation") if len(self.modelos) == 1 else None)
                    for m in self.modelos}
        t = pd.DataFrame({m: v for m, v in columnas.items() if v is not None},
                         index=pd.to_datetime(datos["time"]), dtype="float64")
        return t.clip(lower=0).mean(axis=1).astype("float32")

    def lluvia(self, desde, hasta):
        horas = pd.date_range(pd.Timestamp(desde).floor("h"), pd.Timestamp(hasta).floor("h"), freq="h")
        ahora = self.reloj()
        conocidas = self.serie.dropna().index
        faltan = [h for h in horas.difference(conocidas) if ahora - self._pedidas.get(h, -np.inf) >= self.REINTENTAR_S]
        if faltan:
            try:
                nueva = self._consultar(min(faltan).normalize(), max(faltan).normalize())
                # solo horas ya cerradas: las que vienen después son pronóstico, no lluvia que cayó
                limite = pd.Timestamp(ahora, unit="s").tz_localize("UTC").tz_convert("America/Costa_Rica")
                nueva = nueva[nueva.index <= limite.tz_localize(None).floor("h")]
                self.serie = nueva.combine_first(self.serie).sort_index()
                self.error = None
            except Exception as e:
                self.error = f"{type(e).__name__}: {str(e)[:150]}"
            conseguidas = set(self.serie.dropna().index)
            for h in faltan:
                if h not in conseguidas:
                    self._pedidas[h] = ahora
            for h in [h for h, t in self._pedidas.items() if ahora - t > 86400]:
                del self._pedidas[h]
        return self.serie.reindex(horas)


FUENTES = {"lecturas": LluviaDeLecturas, "open-meteo": LluviaOpenMeteo}


def desde_entorno():
    nombre = (os.environ.get("FUENTE_LLUVIA") or "lecturas").strip()
    if nombre not in FUENTES:
        raise ValueError(f"FUENTE_LLUVIA debe ser una de: {', '.join(FUENTES)}")
    if nombre == "open-meteo":
        return LluviaOpenMeteo(os.environ.get("LLUVIA_MODELOS") or MODELOS_OPEN_METEO)
    return FUENTES[nombre]()


class ConLluvia:
    """
    El cliente de la API de datos, con la lluvia de la fuente elegida en cada lectura. Para el
    servicio es igual que el cliente (mismo `lecturas_desde`); con la fuente `lecturas` no cambia nada.
    """

    def __init__(self, cliente, fuente):
        self.cliente, self.fuente = cliente, fuente

    def lecturas_desde(self, desde=None):
        lecturas = self.cliente.lecturas_desde(desde)
        if not lecturas or isinstance(self.fuente, LluviaDeLecturas):
            return lecturas
        fechas = pd.DatetimeIndex(pd.to_datetime([x["fecha"] for x in lecturas]))
        valores = self.fuente.lluvia(fechas.min(), fechas.max()).reindex(fechas.floor("h")).to_numpy()
        return [{**x, "valores": {**x["valores"], COLUMNA: None if np.isnan(v) else float(v)}}
                for x, v in zip(lecturas, valores)]

    def __getattr__(self, nombre):
        return getattr(self.cliente, nombre)
