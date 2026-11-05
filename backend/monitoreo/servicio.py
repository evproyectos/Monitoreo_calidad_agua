"""
API del servicio de monitoreo (FastAPI) para el dashboard.

Al arrancar carga los modelos y deja corriendo, en segundo plano, el ciclo que consulta la API de
datos, pasa las lecturas al motor y procesa cada hora cerrada. Los endpoints solo leen el estado
del motor.

  GET /health                           si el servicio está en pie, versión y modelos cargados
  POST /predict/contaminacion           predicción a pedido con lecturas que manda el cliente (422 si faltan
                                        datos); pide la clave de API en el encabezado X-API-Key (401 sin ella)
  POST /predict/fugas                   lo mismo para fugas: probabilidad, alarma, tramo y caudal de más
  GET /api/estado                       hora simulada, conexión, alarma activa, modo de pronóstico
  GET /api/sensores                     estado actual de los sensores (observado, pronóstico, detector)
  GET /api/sensores/{nodo}/serie?horas= serie horaria para graficar (observado, pronóstico, prob. de evento)
  GET /api/red/series?horas=48          series de todos los sensores a la vez (vista general)
  GET /api/alarmas                      alarmas de red (la más reciente primero)
  GET /api/anticipacion                 probabilidad de que empiece cada tipo de evento en 24 h y avisos
  GET /api/fugas?horas=168              probabilidad de fuga por hora, tramo y alarmas de fuga
  GET /api/deriva                       deriva de los datos: la última semana contra el entrenamiento
  GET /api/referencias                  norma, tolerancias de la meta y umbral del detector
  GET /                                 dashboard (React, compilado en frontend/dist)

Uso (desde backend/):  python -m monitoreo.servicio            → http://127.0.0.1:8001
Con CERTIFICADO_TLS y CLAVE_TLS en el .env atiende solo por HTTPS (https://127.0.0.1:8001).
"""

import argparse
import asyncio
import os
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
from monitoreo.modelos import Modelos, firma
from monitoreo.motor import Motor
from monitoreo.trabajadores import Trabajadores

REVISAR_MODELOS_S = 600         # cada cuánto se revisa si hay modelos nuevos en la carpeta

DIST = RAIZ / "frontend" / "dist"


def silenciar_cortes(loop):
    """
    En Windows, asyncio imprime un error largo (ConnectionResetError, WinError 10054) cada vez que un
    cliente corta la conexión de golpe, por ejemplo un navegador que todavía no confía en el
    certificado de prueba. No es una falla del servicio: esos casos se ignoran y lo demás se
    reporta como siempre.
    """
    anterior = loop.get_exception_handler()

    def manejador(lp, contexto):
        if isinstance(contexto.get("exception"), ConnectionResetError):
            return
        if anterior is not None:
            anterior(lp, contexto)
        else:
            lp.default_exception_handler(contexto)

    loop.set_exception_handler(manejador)


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
        self.recargas, self.error_recarga, self._ultima_revision = [], None, time.time()
        self.trabajadores, self.error_trabajadores = None, None

    def revisar_modelos(self):
        """
        Si cambiaron los archivos de la carpeta de modelos (un reentrenamiento,
        Modelo_calidad_agua/herramientas/reentrenar.py), carga los nuevos y el motor sigue con
        ellos sin reiniciar el servicio (RF-004.2). Si los nuevos no cargan, o son de otros sensores,
        se sigue con los actuales y queda el error en /health.
        """
        if firma(self.cfg.carpeta_modelos) == self.motor.modelos.firma:
            return False
        try:
            nuevos = Modelos(self.cfg.carpeta_modelos, self.cfg.modo_pronostico)
        except Exception as e:                           # un archivo a medio copiar, una versión vieja...
            self.error_recarga = str(e)[:200]
            return False
        if nuevos.sensores != self.motor.sensores:
            self.error_recarga = f"los modelos nuevos son de otros sensores ({nuevos.sensores}): reinicie el servicio"
            return False
        with self.candado:
            self.motor.modelos = nuevos
        self.recargas.append({"hora": time.strftime("%Y-%m-%d %H:%M:%S"),
                              "modelos": {k: v["sha256"] for k, v in nuevos.version.items()}})
        self.error_recarga = None
        print(f"Modelos nuevos cargados: {self.recargas[-1]['modelos']}")
        return True

    def _ciclo(self):
        while not self._parar.is_set():
            t0 = time.time()
            if t0 - self._ultima_revision >= REVISAR_MODELOS_S:
                self._ultima_revision = t0
                self.revisar_modelos()
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
        if self.cfg.trabajadores_prediccion > 0:
            try:
                self.trabajadores = Trabajadores(self.cfg.carpeta_modelos, self.cfg.modo_pronostico,
                                                 self.cfg.trabajadores_prediccion)
            except Exception as e:                       # sin procesos aparte: /predict en este proceso
                self.error_trabajadores = str(e)[:200]
        self.hilo.start()

    def detener(self):
        self._parar.set()
        if self.trabajadores:
            self.trabajadores.cerrar()

    def predecir(self, tipo, solicitud):
        """
        POST /predict: en un proceso trabajador si los hay (monitoreo/trabajadores.py), con los
        mismos modelos que usa el motor; si no, o si el trabajador falla, en este proceso.
        """
        m, cfg = self.motor.modelos, self.cfg
        if self.trabajadores:
            try:
                return self.trabajadores.atender(tipo, solicitud, getattr(m, "firma", None), cfg.historia_h,
                                                 cfg.umbral_amarillo)
            except prediccion.ErrorEntrada:
                raise
            except Exception as e:                       # un trabajador se cayó o no cargó los modelos
                self.error_trabajadores = f"{type(e).__name__}: {str(e)[:200]}"
        if tipo == "contaminacion":
            return prediccion.predecir(solicitud, m, cfg.historia_h, cfg.umbral_amarillo)
        return prediccion.predecir_fugas(solicitud, m, cfg.historia_h)


def crear_app(cfg=None):
    cfg = cfg or Config()
    estado = {}

    @asynccontextmanager
    async def ciclo_de_vida(_app):
        silenciar_cortes(asyncio.get_running_loop())
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
        if s.error_recarga:
            problemas.append(f"modelos nuevos sin cargar: {s.error_recarga}")
        if s.error_trabajadores:
            problemas.append(f"/predict en el proceso del servicio: {s.error_trabajadores}")
        return {"estado": "degradado" if problemas else "ok", "problemas": problemas,
                "version": __version__,
                "modelos": {**m.version, "modo": m.modo,
                            "por_parametro": m.elegido, "umbral_detector": m.umbral},
                "pronostico_lluvia": e["pronostico_lluvia"],
                "conectado_a_datos": s.conectado,
                "ultima_hora_procesada": e["ultima_hora_procesada"],
                "alertas": s.alertas.canal.nombre,
                "procesos_prediccion": s.trabajadores.cuantos if s.trabajadores else 0,
                "recargas_de_modelos": s.recargas[-5:]}

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
            r = s.predecir("contaminacion", solicitud)
        except prediccion.ErrorEntrada as e:
            raise HTTPException(422, {"error": e.error, "detalles": e.detalles})
        prediccion.guardar(s.motor.carpeta_sesion, r)
        return r

    @app.post("/predict/fugas", dependencies=[con_clave],
              responses={401: {"description": "Clave de API ausente o inválida"},
                         422: {"description": "Faltan datos o no tienen el formato esperado"},
                         503: {"description": "El servicio no tiene claves de API configuradas"}})
    def predecir_fugas(solicitud: prediccion.SolicitudContaminacion):
        """
        Probabilidad de fuga en la última hora cerrada, alarma confirmada, tramo más probable (entre
        qué dos sensores) y caudal de más que entrega la fuente. Recibe las mismas lecturas que
        /predict/contaminacion. Responde 422 con el detalle si faltan datos.
        """
        s = servicio()
        try:
            return s.predecir("fugas", solicitud)
        except prediccion.ErrorEntrada as e:
            raise HTTPException(422, {"error": e.error, "detalles": e.detalles})

    @app.get("/api/fugas")
    def ver_fugas(horas: int = 168):
        s = servicio()
        with s.candado:
            if getattr(s.motor.modelos, "fugas", None) is None:
                return {"disponible": False, "hora": None, "actual": None, "serie": [], "fugas": [], "tramos": []}
            return {"disponible": True, **s.motor.resumen_fugas(max(6, min(horas, 336)))}

    @app.get("/api/deriva")
    def ver_deriva():
        """Deriva de los datos: cada lectura de la última semana contra el entrenamiento (PSI)."""
        s = servicio()
        with s.candado:
            if getattr(s.motor.modelos, "deriva", None) is None:
                return {"disponible": False}
            return {"disponible": True, **(s.motor.ultima_deriva or {"hora": None, "columnas": []}),
                    "criterio": "PSI < 0,10 estable · 0,10 a 0,25 vigilar · > 0,25 deriva"}

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

    @app.get("/api/anticipacion")
    def ver_anticipacion():
        s = servicio()
        with s.candado:
            if getattr(s.motor.modelos, "anticipacion", None) is None:
                return {"disponible": False, "hora": None, "tipos": [], "avisos": []}
            return {"disponible": True, **s.motor.resumen_anticipacion(),
                    "avisos": list(reversed(s.motor.lista_avisos()))}

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
    ap.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"),
                    help="dirección donde atender (0.0.0.0 dentro de Docker)")
    args = ap.parse_args()
    cfg = Config()
    if args.modo:
        cfg.modo_pronostico = args.modo
    seguridad.servidor(crear_app(cfg), args.host, args.puerto, cfg.certificado_tls, cfg.clave_tls,
                       log_level="warning").run()
