"""
API del servicio de monitoreo (FastAPI) para el dashboard.

Al arrancar carga los modelos y deja corriendo, en segundo plano, el ciclo que consulta la API de
datos, pasa las lecturas al motor y procesa cada hora cerrada. Los endpoints solo leen el estado
del motor.

  GET /health                           si el servicio está en pie, versión y modelos cargados
  POST /predict/contaminacion           predicción a pedido con lecturas que manda el cliente (422 si faltan
                                        datos); pide la clave de API en el encabezado X-API-Key (401 sin ella)
  GET /api/estado                       hora simulada, conexión, alarma activa, modo de pronóstico
  GET /api/sensores                     estado actual de los 21 sensores (observado, pronóstico, detector)
  GET /api/sensores/{nodo}/serie?horas= serie horaria para graficar (observado, pronóstico, prob. de evento)
  GET /api/red/series?horas=48          series de los 21 sensores a la vez (vista general)
  GET /api/alarmas                      alarmas de red (la más reciente primero)
  GET /api/referencias                  norma, tolerancias de la meta y umbral del detector
  GET /                                 dashboard (React, compilado en frontend/dist)

Uso (desde backend/):  python -m monitoreo.servicio            → http://127.0.0.1:8001
Con CERTIFICADO_TLS y CLAVE_TLS en el .env atiende solo por HTTPS (https://127.0.0.1:8001).
"""

import argparse
import threading
import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from calidad_agua import calidad, metas

from monitoreo import __version__, prediccion, seguridad
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
                    for lec in lecturas:
                        self.motor.recibir(lec["fecha"], lec["valores"])
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
        claves = len(seguridad.claves_configuradas())
        print(f"Clave de API para /predict: {claves} configurada{'s' if claves != 1 else ''}" if claves else
              "Sin CLAVES_API: /predict/contaminacion responde 503 hasta que se configure una clave")
        print(f"Dashboard: {cfg.esquema}://127.0.0.1:8001" + ("" if DIST.exists() else
              "  (falta compilar el frontend: cd frontend && npm run build)"))
        yield
        estado["s"].detener()

    app = FastAPI(title="Monitoreo de calidad de agua", version=__version__, lifespan=ciclo_de_vida)
    # en desarrollo el dashboard corre en el servidor de Vite (puerto 5173)
    app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                       allow_methods=["GET"], allow_headers=["*"])

    # errores de validación en español y con la ubicación del campo (RF-003.1, RNF-010)
    MENSAJES = {"missing": "falta este campo", "float_parsing": "debe ser un número o null",
                "float_type": "debe ser un número o null", "datetime_from_date_parsing": "no es una fecha válida",
                "datetime_parsing": "no es una fecha válida", "datetime_type": "no es una fecha válida",
                "list_type": "debe ser una lista", "dict_type": "debe ser un objeto",
                "too_short": "no puede estar vacío", "json_invalid": "el cuerpo no es JSON válido",
                "model_attributes_type": "debe ser un objeto JSON", "string_type": "debe ser texto"}

    @app.exception_handler(RequestValidationError)
    async def error_validacion(_req: Request, exc: RequestValidationError):
        detalles = []
        for e in exc.errors()[:20]:
            donde = ".".join(str(x) for x in e.get("loc", ()) if x != "body") or "cuerpo"
            detalles.append(f"{donde}: {MENSAJES.get(e.get('type'), e.get('msg'))}")
        return JSONResponse(status_code=422, content={"detail": {
            "error": "La solicitud no tiene el formato esperado.", "detalles": detalles}})

    con_clave = Depends(seguridad.exigir_clave(seguridad.RegistroAccesos(cfg.carpeta_registros)))

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

    @app.post("/predict/contaminacion", dependencies=[con_clave],
              responses={401: {"description": "Clave de API ausente o inválida"},
                         422: {"description": "Faltan datos o no tienen el formato esperado"},
                         503: {"description": "El servicio no tiene claves de API configuradas"}})
    def predecir_contaminacion(solicitud: prediccion.SolicitudContaminacion):
        """
        Probabilidad de evento de contaminación por sensor para la última hora cerrada, pronóstico a
        24 h de cloro, turbidez y pH, y nivel de riesgo (verde, amarillo, rojo). Recibe las lecturas
        de 15 min de toda la red de al menos las últimas 98 h, en el formato que los sensores le
        mandan a la API de datos. Responde 422 con el detalle si faltan columnas, lecturas o datos.
        """
        s = servicio()
        try:
            r = prediccion.predecir(solicitud, s.motor.modelos, cfg.historia_h, cfg.umbral_amarillo, s.candado)
        except prediccion.ErrorEntrada as e:
            raise HTTPException(422, {"error": e.error, "detalles": e.detalles})
        prediccion.guardar(s.motor.carpeta_sesion, r)
        return r

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
    ap = argparse.ArgumentParser()
    ap.add_argument("--modo", choices=["combinado", "arboles"], default=None)
    ap.add_argument("--puerto", type=int, default=8001)
    args = ap.parse_args()
    cfg = Config()
    if args.modo:
        cfg.modo_pronostico = args.modo
    seguridad.servidor(crear_app(cfg), "127.0.0.1", args.puerto, cfg.certificado_tls, cfg.clave_tls,
                       log_level="warning").run()
