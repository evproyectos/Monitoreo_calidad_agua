"""
Cliente de la API de datos de los sensores (la de Simulador_sensor/tiempo_real/servicio.py).
Cada consulta se reintenta 3 veces con espera exponencial si la API no responde o da un error 5xx
(reintentos.py, RNF-002); si igual falla, el servicio vuelve a probar en el siguiente ciclo.
"""

import time

import requests

from monitoreo.reintentos import reintentar


def _reintentable(e):
    """La API no respondió o tuvo un error suyo; un 4xx (pedido mal hecho) no se arregla reintentando."""
    if isinstance(e, requests.HTTPError) and e.response is not None:
        return e.response.status_code >= 500
    return isinstance(e, requests.RequestException)


class ClienteDatos:
    def __init__(self, url, tiempo_espera=30, espera_s=0.5, dormir=time.sleep):
        self.url = url.rstrip("/")
        self.s = requests.Session()
        self.tiempo_espera = tiempo_espera
        self.espera_s, self.dormir = espera_s, dormir

    def _get(self, params):
        def pedir():
            r = self.s.get(f"{self.url}/lecturas", params=params, timeout=self.tiempo_espera)
            r.raise_for_status()
            return r.json()
        return reintentar(pedir, espera_s=self.espera_s, reintentable=_reintentable,
                          nombre="la consulta a la API de datos", dormir=self.dormir)

    def disponible(self):
        try:
            self.s.get(f"{self.url}/estado", timeout=5).raise_for_status()
            return True
        except requests.RequestException:
            return False

    def lecturas_desde(self, desde=None):
        """
        Lecturas con fecha >= `desde` (todas si es None), en orden. La API devuelve hasta 5 000
        por consulta; si llegan 5 000 se sigue pidiendo hasta ponerse al día.
        """
        todas = []
        while True:
            params = {"desde": desde.isoformat()} if desde is not None else {}
            lote = self._get(params)
            todas += lote
            if len(lote) < 5000:
                return todas
            desde = __import__("pandas").Timestamp(lote[-1]["fecha"])
