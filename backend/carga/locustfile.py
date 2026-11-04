"""
Prueba de carga de la API de predicción (RNF-001): 10 usuarios a la vez durante 5 minutos piden
POST /predict/contaminacion y POST /predict/fugas con las últimas lecturas reales.

Con el servicio y la API de datos corriendo (y CLAVES_API configurada), desde backend/:

    pip install locust
    set CLAVE_API=<una de las claves de CLAVES_API>          (PowerShell: $env:CLAVE_API="...")
    locust -f carga/locustfile.py --host http://127.0.0.1:8001 --headless -u 10 -r 2 -t 5m ^
           --csv ../docs/rendimiento/carga

El reporte queda en docs/rendimiento/carga_stats.csv: la columna 95% es el percentil 95 de la
latencia en ms (meta: ≤ 500 ms). URL_DATOS cambia la API de datos (por defecto la local).
"""

import os

import requests
from locust import HttpUser, between, events, task

URL_DATOS = os.environ.get("URL_DATOS", "http://127.0.0.1:8000")
CLAVE = os.environ.get("CLAVE_API", "")
LECTURAS = {}


@events.test_start.add_listener
def cargar_lecturas(environment, **_):
    """Una sola vez: las últimas 8 días de lecturas (lo que pide /predict/fugas)."""
    todas, desde = [], None
    while True:
        r = requests.get(f"{URL_DATOS}/lecturas", params={"desde": desde} if desde else {}, timeout=60)
        r.raise_for_status()
        lote = r.json()
        todas += lote
        if len(lote) < 5000:
            break
        desde = lote[-1]["fecha"]
    LECTURAS["fugas"] = todas[-(4 * 200):]          # 200 h
    LECTURAS["contaminacion"] = todas[-(4 * 100):]  # 100 h


class Cliente(HttpUser):
    wait_time = between(0.5, 1.5)

    @task(3)
    def contaminacion(self):
        self.client.post("/predict/contaminacion", json={"lecturas": LECTURAS["contaminacion"]},
                         headers={"X-API-Key": CLAVE}, name="POST /predict/contaminacion")

    @task(1)
    def fugas(self):
        self.client.post("/predict/fugas", json={"lecturas": LECTURAS["fugas"]},
                         headers={"X-API-Key": CLAVE}, name="POST /predict/fugas")

    @task(2)
    def estado(self):
        self.client.get("/api/estado", name="GET /api/estado")
