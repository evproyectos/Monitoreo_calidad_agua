"""
Pronóstico de lluvia para los modelos (los árboles lo usan como variable, notebook 06).

Los modelos necesitan, en cada hora t, la lluvia pronosticada para las horas t+1 … t+24 por
tramos (calidad_agua.clima.ventanas), con el promedio de los cuatro modelos meteorológicos con
que se entrenaron (ECMWF IFS, GFS, ICON y GEM). Hay dos fuentes:

  archivo     (por defecto) los pronósticos pasados guardados en el proyecto de modelos
              (clima/pronostico_lluvia_modelos.csv): lo que decían los modelos meteorológicos
              24 h antes de cada hora. Es lo que corresponde cuando los datos de los sensores son
              de fechas pasadas, como los que manda el emisor: el servicio ve exactamente el
              pronóstico que habría existido en ese momento.
  open-meteo  el pronóstico vigente de la Forecast API de Open-Meteo, para operar con datos en
              tiempo real. Se consulta al arrancar y luego cada hora, con 3 reintentos y espera
              exponencial (reintentos.py, RNF-002); si igual falla, se sigue con el último
              pronóstico y se vuelve a probar en 10 minutos. Con OPEN_METEO_API_KEY (plan pagado)
              usa el dominio customer-api.open-meteo.com con esa clave; sin ella, la API gratuita
              (uso no comercial). Datos de Open-Meteo.com, licencia CC BY 4.0.

Se elige con la variable de entorno FUENTE_PRONOSTICO.
"""

import json
import os
import threading
import time
import urllib.parse
import urllib.request

import pandas as pd

from calidad_agua import clima
from monitoreo.reintentos import reintentar

LATITUD, LONGITUD = 10.3606, -84.5135            # estación 69-701 ITCR, San Carlos (IMN)
URL_OPEN_METEO = ("https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
                  "&hourly=precipitation&models={modelos}&timezone=America%2FCosta_Rica"
                  "&past_days=2&forecast_days=3")


def con_clave(url, clave=None):
    """Con la clave del plan pagado de Open-Meteo (OPEN_METEO_API_KEY): el dominio customer-… de
    la misma API y &apikey=. Sin clave, la URL queda igual (API gratuita)."""
    clave = (os.environ.get("OPEN_METEO_API_KEY", "") if clave is None else clave).strip()
    if not clave:
        return url
    partes = urllib.parse.urlsplit(url)
    consulta = partes.query + ("&" if partes.query else "") + urllib.parse.urlencode({"apikey": clave})
    return urllib.parse.urlunsplit(partes._replace(netloc="customer-" + partes.netloc, query=consulta))


class PronosticoArchivo:
    descripcion = "pronósticos pasados de Open-Meteo (archivo)"

    def __init__(self, ruta=None, modelos=clima.MODELOS):
        self.serie = clima.cargar_pronostico(ruta, modelos)

    def ventanas(self, horas):
        return clima.ventanas(self.serie, horas)


class PronosticoOpenMeteo:
    descripcion = "pronóstico vigente de Open-Meteo"
    REINTENTAR_S = 600                                 # si la consulta falló del todo, otra en 10 min

    def __init__(self, modelos=clima.MODELOS, cada_s=3600, dormir=time.sleep):
        self.modelos, self.cada_s, self.dormir = list(modelos), cada_s, dormir
        self.serie, self.consultado = None, 0.0
        self.error = None
        self._candado = threading.Lock()              # el motor y las solicitudes a pedido lo comparten

    def _actualizar(self):
        if self.serie is not None and time.time() - self.consultado < self.cada_s:
            return
        url = con_clave(URL_OPEN_METEO.format(lat=LATITUD, lon=LONGITUD, modelos=",".join(self.modelos)))

        def consultar():
            with urllib.request.urlopen(url, timeout=10) as r:
                return json.load(r)["hourly"]
        try:
            datos = reintentar(consultar, nombre="la consulta a Open-Meteo", dormir=self.dormir)
            t = pd.DataFrame({m: datos.get(f"precipitation_{m}") for m in self.modelos},
                             index=pd.to_datetime(datos["time"])).astype(float)
            nueva = t.clip(lower=0).mean(axis=1).astype("float32")
            # se conservan los pronósticos de horas ya pasadas que la consulta nueva no trae
            self.serie = nueva if self.serie is None else nueva.combine_first(self.serie)
            self.consultado, self.error = time.time(), None
        except Exception as e:                          # sin red: se sigue con el último pronóstico
            self.error = str(e)
            self.consultado = time.time() - self.cada_s + self.REINTENTAR_S
            if self.serie is None:
                self.serie = pd.Series(dtype="float32")

    def ventanas(self, horas):
        with self._candado:
            self._actualizar()
            serie = self.serie
        return clima.ventanas(serie, horas)


def desde_entorno():
    fuente = os.environ.get("FUENTE_PRONOSTICO", "archivo")
    if fuente == "archivo":
        return PronosticoArchivo(os.environ.get("PRONOSTICO_LLUVIA") or None)
    if fuente == "open-meteo":
        return PronosticoOpenMeteo()
    raise ValueError("FUENTE_PRONOSTICO debe ser 'archivo' u 'open-meteo'")
