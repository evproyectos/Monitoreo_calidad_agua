"""
Prueba de carga de la API de predicción (RNF-001): 10 usuarios a la vez durante 5 minutos piden
POST /predict/contaminacion y POST /predict/fugas con las últimas lecturas reales.

Con el servicio y la API de datos corriendo (y CLAVES_API configurada), desde backend/:

    pip install locust
    set CLAVE_API=<una de las claves de CLAVES_API>          (PowerShell: $env:CLAVE_API="...")
    set CORREO_CARGA=<correo de un usuario del dashboard>    (para GET /api/estado, que pide sesión)
    set CONTRASENA_CARGA=<su contraseña>
    locust -f carga/locustfile.py --host https://127.0.0.1:8001 --headless -u 10 -r 2 -t 5m ^
           --csv ../docs/rendimiento/carga

Con el servicio en HTTP (sin CERTIFICADO_TLS) el --host es http://127.0.0.1:8001. Con HTTPS no se
verifica el certificado, porque es autofirmado.

El reporte queda en docs/rendimiento/carga_stats.csv: la columna 95% es el percentil 95 de la
latencia en ms (meta: ≤ 500 ms). URL_DATOS cambia la API de datos (por defecto la local).
"""

import os

import requests
import urllib3
from locust import HttpUser, between, events, task

URL_DATOS = os.environ.get("URL_DATOS", "http://127.0.0.1:8000")
CLAVE = os.environ.get("CLAVE_API", "")
# el dashboard pide inicio de sesión: con estas dos variables cada usuario simulado entra una vez
CORREO = os.environ.get("CORREO_CARGA", "")
CONTRASENA = os.environ.get("CONTRASENA_CARGA", "")
LECTURAS = {}


@events.test_start.add_listener
def cargar_lecturas(environment, **_):
    """Una sola vez: los últimos 8 días de lecturas (lo que pide /predict/fugas)."""
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

    def on_start(self):
        if self.host.startswith("https"):           # certificado autofirmado del servicio
            self.client.verify = False
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        self.con_sesion = bool(CORREO) and self.client.post(
            "/api/sesion", json={"correo": CORREO, "contrasena": CONTRASENA}, name="POST /api/sesion").ok

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
        if self.con_sesion:                          # sin sesión el dashboard responde 401
            self.client.get("/api/estado", name="GET /api/estado")
