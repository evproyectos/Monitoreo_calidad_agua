"""
API del servicio de monitoreo (FastAPI) para el dashboard.

Al arrancar carga los modelos y deja corriendo, en segundo plano, el ciclo que consulta la API de
datos, pasa las lecturas al motor y procesa cada hora cerrada. Los endpoints solo leen el estado
del motor.

  GET /health                           si el servicio está en pie, versión y modelos cargados
  GET /api/estado                       hora simulada, conexión, alarma activa, modo de pronóstico
  GET /api/sensores                     estado actual de los 21 sensores (observado, pronóstico, detector)
  GET /api/sensores/{nodo}/serie?horas= serie horaria para graficar (observado, pronóstico, prob. de evento)
  GET /api/red/series?horas=48          series de los 21 sensores a la vez (vista general)
  GET /api/alarmas                      alarmas de red (la más reciente primero)
  GET /api/referencias                  norma, tolerancias de la meta y umbral del detector
  GET /                                 dashboard (React, compilado en frontend/dist)

Uso (desde backend/):  python -m monitoreo.servicio            → http://127.0.0.1:8001
"""

import argparse
import threading
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from calidad_agua import calidad, metas

from monitoreo import __version__
from monitoreo.alertas import Alertas
from monitoreo.cliente_datos import ClienteDatos
from monitoreo.config import Config, RAIZ
from monitoreo.motor import Motor

DIST = RAIZ / "frontend" / "dist"


class Servicio:
    """El motor más el ciclo en segundo plano que lo alimenta desde la API de datos."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.motor = Motor(cfg)
        self.cliente = ClienteDatos(cfg.url_datos)
        self.alertas = Alertas()                         # Telegram si está configurado; si no, consola
        self.candado = threading.Lock()
        self.conectado = False
        self.ultimo_error = None
        self.ultimo_ciclo_s = None
        self._parar = threading.Event()
        self.hilo = threading.Thread(target=self._ciclo, daemon=True)

    def _ciclo(self):
        while not self._parar.is_set():
            t0 = time.time()
            try:
                lecturas = self.cliente.lecturas_desde(self.motor.ultima_lectura)
                self.conectado, self.ultimo_error = True, None
                with self.candado:
                    for l in lecturas:
                        self.motor.recibir(l["fecha"], l["valores"])
                    novedades = self.motor.procesar()
                    self.alertas.revisar(self.motor, novedades)
                self.ultimo_ciclo_s = round(time.time() - t0, 2)
            except Exception as e:                       # la API de datos se cayó o no responde
                self.conectado, self.ultimo_error = False, str(e)[:200]
            self._parar.wait(max(0.2, self.cfg.intervalo_consulta_s - (time.time() - t0)))

    def iniciar(self):
        self.hilo.start()

    def detener(self):
        self._parar.set()


def crear_app(cfg=None):
    cfg = cfg or Config()
    estado = {}

    @asynccontextmanager
    async def ciclo_de_vida(_app):
        print("Cargando modelos...")
        estado["s"] = Servicio(cfg)
        estado["s"].iniciar()
        print(f"Servicio de monitoreo listo · modo {cfg.modo_pronostico} · datos desde {cfg.url_datos}")
        print(f"Alertas: {estado['s'].alertas.canal.nombre}" + ("" if estado["s"].alertas.canal.nombre == "telegram"
              else "  (para Telegram: variables TELEGRAM_TOKEN y TELEGRAM_CHAT_ID)"))
        print("Dashboard: http://127.0.0.1:8001" + ("" if DIST.exists() else
              "  (falta compilar el frontend: cd frontend && npm run build)"))
        yield
        estado["s"].detener()

    app = FastAPI(title="Monitoreo de calidad de agua", version=__version__, lifespan=ciclo_de_vida)
    # en desarrollo el dashboard corre en el servidor de Vite (puerto 5173)
    app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                       allow_methods=["GET"], allow_headers=["*"])

    def servicio():
        if "s" not in estado:
            raise HTTPException(503, "El servicio todavía está cargando los modelos")
        return estado["s"]

    @app.get("/health")
    def salud():
        """
        200 con estado "ok" si todo funciona, o "degradado" si el servicio está en pie pero no
        llegan datos o falla el pronóstico de lluvia (sigue con el último). Mientras carga los
        modelos el puerto todavía no responde. Para Docker y para monitoreo externo.
        """
        if "s" not in estado:
            return JSONResponse(status_code=503, content={
                "estado": "iniciando", "version": __version__, "detalle": "cargando los modelos"})
        s = estado["s"]
        with s.candado:
            e = s.motor.estado()
            m = s.motor.modelos
        problemas = []
        if not s.conectado:
            problemas.append("sin conexión con la API de datos" + (f": {s.ultimo_error}" if s.ultimo_error else ""))
        if e["error_pronostico_lluvia"]:
            problemas.append(f"pronóstico de lluvia: {e['error_pronostico_lluvia']}")
        return {"estado": "degradado" if problemas else "ok", "problemas": problemas,
                "version": __version__,
                "modelos": {**m.version, "modo": m.modo,
                            "por_parametro": m.elegido, "umbral_detector": m.umbral},
                "pronostico_lluvia": e["pronostico_lluvia"],
                "conectado_a_datos": s.conectado,
                "ultima_hora_procesada": e["ultima_hora_procesada"],
                "alertas": s.alertas.canal.nombre}

    @app.get("/api/estado")
    def ver_estado():
        s = servicio()
        with s.candado:
            e = s.motor.estado()
            abierta = s.motor.lista_alarmas()[-1] if s.motor.alarma_abierta else None
            en_alarma = sum(1 for x in s.motor.resumen_sensores() if x["en_alarma"])
        return {**e, "conectado_a_datos": s.conectado, "error": s.ultimo_error,
                "duracion_ultimo_ciclo_s": s.ultimo_ciclo_s, "sensores_en_alarma": en_alarma,
                "alarma_abierta": abierta, "sensores": len(s.motor.sensores), "alertas": s.alertas.estado()}

    @app.get("/api/sensores")
    def ver_sensores():
        s = servicio()
        with s.candado:
            return s.motor.resumen_sensores()

    @app.get("/api/sensores/{nodo}/serie")
    def ver_serie(nodo: str, horas: int = 72):
        s = servicio()
        if nodo not in s.motor.sensores:
            raise HTTPException(404, f"No existe el sensor {nodo}")
        with s.candado:
            return s.motor.serie_sensor(nodo, max(6, min(horas, 168)))

    @app.get("/api/red/series")
    def ver_series_red(horas: int = 48):
        s = servicio()
        with s.candado:
            return s.motor.series_red(max(6, min(horas, 168)))

    @app.get("/api/alarmas")
    def ver_alarmas():
        s = servicio()
        with s.candado:
            return list(reversed(s.motor.lista_alarmas()))

    @app.get("/api/referencias")
    def ver_referencias():
        s = servicio()
        return {"norma": calidad.NORMA, "tolerancia": metas.TOLERANCIA, "meta_pct": metas.META_PCT,
                "umbral_detector": s.motor.modelos.umbral, "confirmar_h": s.motor.modelos.confirmar_h}

    if DIST.exists():
        app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

        @app.get("/")
        def dashboard():
            return FileResponse(DIST / "index.html")

    return app


if __name__ == "__main__":
    import uvicorn
    ap = argparse.ArgumentParser()
    ap.add_argument("--modo", choices=["combinado", "arboles"], default=None)
    ap.add_argument("--puerto", type=int, default=8001)
    args = ap.parse_args()
    cfg = Config()
    if args.modo:
        cfg.modo_pronostico = args.modo
    uvicorn.run(crear_app(cfg), host="127.0.0.1", port=args.puerto, log_level="warning")
