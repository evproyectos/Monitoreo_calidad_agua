"""Cliente de la API de datos de los sensores (la de Simulador_sensor/tiempo_real/servicio.py)."""

import requests


class ClienteDatos:
    def __init__(self, url, tiempo_espera=30):
        self.url = url.rstrip("/")
        self.s = requests.Session()
        self.tiempo_espera = tiempo_espera

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
            r = self.s.get(f"{self.url}/lecturas", params=params, timeout=self.tiempo_espera)
            r.raise_for_status()
            lote = r.json()
            todas += lote
            if len(lote) < 5000:
                return todas
            desde = __import__("pandas").Timestamp(lote[-1]["fecha"])
