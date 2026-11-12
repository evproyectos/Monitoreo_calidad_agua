"""
F1 de las alarmas en producción (RF-004.2 y RNF-003): cada día, el F1 de los últimos 7 días, con lo
que el personal verificó en campo, registrado en MLflow; si baja del 75 %, se avisa.

De dónde sale cada caso (alarmas de la red y posibles fugas, las alertas rojas de los modelos de
detección; los avisos anticipados y el riesgo en 24 h no cuentan):
  verdadero positivo  alerta cerrada como "confirmada" (gestion.py)
  falso positivo      alerta cerrada como "descartada"
  falso negativo      evento que ocurrió sin alerta: lo registra el personal (resultado del
                      laboratorio, registro de la ASADA o reporte de un abonado) en no_detectados
Las alertas inconclusas, las que se resolvieron solas y las que siguen abiertas no cuentan (se
muestran como "sin verificar"). Los días se cuentan por la hora de los datos, la misma de las alertas.

F1 = 2·VP / (2·VP + FP + FN). Con menos de RENDIMIENTO_MIN_CASOS casos verificados en la ventana el
estado es "sin datos" y no se avisa: un F1 con uno o dos casos no dice nada.

Registro diario: al pasar el procesamiento por la medianoche de los datos se calcula el F1 de los 7
días anteriores, se guarda en la tabla rendimiento_diario y se registra en MLflow (experimento
monitoreo_produccion, una corrida por día) si está MLFLOW_URL (en Docker, el servicio mlflow). Sin
MLflow se guarda igual en la base y se ve en el dashboard.

Variables de entorno (opcionales):
  MLFLOW_URL               servidor de MLflow (p. ej. http://mlflow:5000)
  RENDIMIENTO_DIAS         ventana en días (7)
  RENDIMIENTO_F1_MINIMO    por debajo se avisa (0,75)
  RENDIMIENTO_MIN_CASOS    casos verificados mínimos para evaluar (3)
"""

import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timedelta

import pandas as pd
from sqlalchemy import Column, DateTime, Float, Integer, MetaData, String, Table, insert, select

from monitoreo import gestion as gestion_

TIPOS_DETECCION = ("alarma", "fuga")            # alertas rojas de los modelos de detección
TIPOS_EVENTO = {"contaminacion": "Contaminación", "falla_cloro": "Falla de cloración",
                "turbidez_fuente": "Turbidez en la fuente", "falla_ph": "Falla de pH", "fuga": "Fuga"}
FUENTES = {"laboratorio": "Resultado de laboratorio", "registro_asada": "Registro de la ASADA",
           "reporte": "Reporte de un abonado", "otra": "Otra"}
EXPERIMENTO = "monitoreo_produccion"

meta = MetaData()
no_detectados = Table(
    "no_detectados", meta,
    Column("id", Integer, primary_key=True),
    Column("fecha", DateTime, nullable=False),              # cuándo ocurrió (hora de los datos)
    Column("tipo", String(20), nullable=False),
    Column("lugar", String(300)),
    Column("fuente", String(20), nullable=False),
    Column("observaciones", String(1000), nullable=False),
    Column("registrado", DateTime, nullable=False),
    Column("correo", String(254)),
    Column("nombre", String(120)),
)
diario = Table(
    "rendimiento_diario", meta,
    Column("fecha", DateTime, primary_key=True),            # el día evaluado (fin de la ventana)
    Column("desde", DateTime, nullable=False),
    Column("confirmadas", Integer, nullable=False),
    Column("descartadas", Integer, nullable=False),
    Column("no_detectados", Integer, nullable=False),
    Column("sin_verificar", Integer, nullable=False),
    Column("precision", Float),
    Column("sensibilidad", Float),
    Column("f1", Float),
    Column("estado", String(12), nullable=False),
    Column("mlflow_run", String(64)),
    Column("calculado", DateTime, nullable=False),
)


def _f(t):
    return None if t is None else pd.Timestamp(t).isoformat(timespec="minutes")


def metricas(confirmadas, descartadas, no_detectados_, minimo_casos, f1_minimo):
    casos = confirmadas + descartadas + no_detectados_
    precision = confirmadas / (confirmadas + descartadas) if confirmadas + descartadas else None
    sensibilidad = confirmadas / (confirmadas + no_detectados_) if confirmadas + no_detectados_ else None
    f1 = 2 * confirmadas / (2 * confirmadas + descartadas + no_detectados_) if casos else None
    estado = "sin_datos" if casos < minimo_casos else ("bajo" if f1 < f1_minimo else "bien")
    return {"precision": precision, "sensibilidad": sensibilidad, "f1": f1, "casos": casos, "estado": estado}


class Mlflow:
    """Lo mínimo de la API REST de MLflow para registrar una corrida por día (sin instalar mlflow)."""

    def __init__(self, url, experimento=EXPERIMENTO, timeout=5):
        self.url, self.experimento, self.timeout = url.rstrip("/"), experimento, timeout
        self._id = None

    def _pedir(self, ruta, cuerpo=None):
        datos = None if cuerpo is None else json.dumps(cuerpo).encode()
        req = urllib.request.Request(f"{self.url}/api/2.0/mlflow/{ruta}", data=datos,
                                     headers={"Content-Type": "application/json"}, method="POST" if datos else "GET")
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return json.loads(r.read() or b"{}")

    def experimento_id(self):
        if self._id is None:
            try:
                q = urllib.request.quote(self.experimento)
                self._id = self._pedir(f"experiments/get-by-name?experiment_name={q}")["experiment"]["experiment_id"]
            except urllib.error.HTTPError as e:
                if e.code != 404:
                    raise
                self._id = self._pedir("experiments/create", {"name": self.experimento})["experiment_id"]
        return self._id

    def registrar(self, r, params):
        """Una corrida con las métricas del día; devuelve su id."""
        ahora = int(datetime.now().timestamp() * 1000)
        dia = pd.Timestamp(r["hasta"])
        etiquetas = [{"key": "fecha_datos", "value": f"{dia:%Y-%m-%d}"}, {"key": "estado", "value": r["estado"]},
                     {"key": "origen", "value": "servicio de monitoreo"}]
        run = self._pedir("runs/create", {
            "experiment_id": self.experimento_id(), "run_name": f"F1 {params['ventana_dias']} días · {dia:%d/%m/%Y}",
            "start_time": ahora, "tags": etiquetas})["run"]["info"]["run_id"]
        paso, marca = int(dia.timestamp() // 86400), int(dia.timestamp() * 1000)
        valores = {k: r[k] for k in ("f1", "precision", "sensibilidad") if r[k] is not None}
        valores.update({k: r[k] for k in ("confirmadas", "descartadas", "no_detectados", "sin_verificar")})
        self._pedir("runs/log-batch", {
            "run_id": run, "metrics": [{"key": f"{k}_{params['ventana_dias']}d", "value": float(v),
                                        "timestamp": marca, "step": paso} for k, v in valores.items()],
            "params": [{"key": k, "value": str(v)} for k, v in params.items()]})
        self._pedir("runs/update", {"run_id": run, "status": "FINISHED", "end_time": ahora})
        return run


class Rendimiento:
    def __init__(self, gestion, mlflow_url=None, dias=None, f1_minimo=None, minimo_casos=None):
        self.gestion = gestion
        self.motor = gestion.motor
        meta.create_all(self.motor)
        self.dias = int(dias or os.environ.get("RENDIMIENTO_DIAS", 7))
        self.f1_minimo = float(f1_minimo or os.environ.get("RENDIMIENTO_F1_MINIMO", 0.75))
        self.minimo_casos = int(minimo_casos or os.environ.get("RENDIMIENTO_MIN_CASOS", 3))
        url = mlflow_url if mlflow_url is not None else os.environ.get("MLFLOW_URL")
        self.mlflow = Mlflow(url) if url else None
        self.ultimo_error_mlflow = None

    @property
    def params(self):
        return {"ventana_dias": self.dias, "f1_minimo": self.f1_minimo, "minimo_casos": self.minimo_casos}

    # ------------------------------------------------------------------ cálculo
    def calcular(self, hasta):
        hasta = pd.Timestamp(hasta).to_pydatetime()
        desde = hasta - timedelta(days=self.dias)
        a = gestion_.alertas
        with self.motor.connect() as c:
            filas = c.execute(select(a.c.estado, a.c.resultado).where(
                a.c.tipo.in_(TIPOS_DETECCION), a.c.inicio >= desde, a.c.inicio < hasta)).all()
            fn = c.execute(select(no_detectados.c.id).where(
                no_detectados.c.fecha >= desde, no_detectados.c.fecha < hasta)).all()
        conf = sum(1 for f in filas if f.resultado == "confirmada")
        desc = sum(1 for f in filas if f.resultado == "descartada")
        sin = sum(1 for f in filas if f.estado != "cerrada" or f.resultado in ("inconclusa", "automatica"))
        return {"desde": _f(desde), "hasta": _f(hasta), "confirmadas": conf, "descartadas": desc,
                "no_detectados": len(fn), "sin_verificar": sin,
                **metricas(conf, desc, len(fn), self.minimo_casos, self.f1_minimo)}

    def diario(self, anterior, ahora, hora=0):
        """
        Los días cuya medianoche (de los datos) cruzó el procesamiento entre `anterior` y `ahora`: los
        calcula, los guarda y los registra en MLflow (una vez por día). Devuelve el último calculado.
        """
        if anterior is None or ahora is None:
            return None
        horas = pd.date_range(pd.Timestamp(anterior), pd.Timestamp(ahora), freq="1h")[1:]
        ultimo = None
        for dia in sorted({h.normalize() for h in horas if h.hour == hora}):
            with self.motor.connect() as c:
                if c.execute(select(diario.c.fecha).where(diario.c.fecha == dia.to_pydatetime())).first():
                    continue                            # ya registrado (al reiniciar el servicio)
            r = self.calcular(dia)
            r["mlflow_run"] = self._registrar_mlflow(r)
            with self.motor.begin() as c:
                c.execute(insert(diario).values(
                    fecha=dia.to_pydatetime(), desde=pd.Timestamp(r["desde"]).to_pydatetime(),
                    calculado=datetime.now(), **{k: r[k] for k in (
                        "confirmadas", "descartadas", "no_detectados", "sin_verificar", "precision",
                        "sensibilidad", "f1", "estado", "mlflow_run")}))
            ultimo = r
        return ultimo

    def _registrar_mlflow(self, r):
        if self.mlflow is None:
            return None
        try:
            run = self.mlflow.registrar(r, self.params)
            self.ultimo_error_mlflow = None
            return run
        except Exception as e:                           # sin MLflow se guarda igual en la base
            self.ultimo_error_mlflow = f"{type(e).__name__}: {e}"
            print(f"No se pudo registrar el F1 del día en MLflow: {self.ultimo_error_mlflow}", flush=True)
            return None

    def historial(self, limite=30):
        with self.motor.connect() as c:
            filas = c.execute(select(diario).order_by(diario.c.fecha.desc()).limit(limite)).all()
        return [{"fecha": _f(f.fecha), "desde": _f(f.desde), "confirmadas": f.confirmadas,
                 "descartadas": f.descartadas, "no_detectados": f.no_detectados, "sin_verificar": f.sin_verificar,
                 "precision": f.precision, "sensibilidad": f.sensibilidad, "f1": f.f1, "estado": f.estado,
                 "mlflow_run": f.mlflow_run} for f in filas][::-1]

    def resumen(self, ahora):
        return {"actual": self.calcular(ahora), "historial": self.historial(), **self.params,
                "mlflow": {"configurado": self.mlflow is not None, "experimento": EXPERIMENTO,
                           "ultimo_error": self.ultimo_error_mlflow}}

    # ------------------------------------------------------------------ eventos no detectados
    def registrar_no_detectado(self, usuario, fecha, tipo, lugar, fuente, observaciones):
        observaciones = (observaciones or "").strip()
        if tipo not in TIPOS_EVENTO:
            raise gestion_.ErrorGestion(f"Tipo de evento: {', '.join(TIPOS_EVENTO)}.")
        if fuente not in FUENTES:
            raise gestion_.ErrorGestion(f"De dónde se supo: {', '.join(FUENTES)}.")
        if len(observaciones) < gestion_.MINIMO_OBSERVACION:
            raise gestion_.ErrorGestion("Las observaciones son obligatorias: cómo se supo y qué se encontró.")
        try:
            fecha = pd.Timestamp(fecha).to_pydatetime().replace(tzinfo=None)
        except (ValueError, TypeError):
            raise gestion_.ErrorGestion("La fecha va como AAAA-MM-DD HH:MM.")
        with self.motor.begin() as c:
            uid = c.execute(insert(no_detectados).values(
                fecha=fecha, tipo=tipo, lugar=(lugar or "").strip()[:300] or None, fuente=fuente,
                observaciones=observaciones[:1000], registrado=datetime.now(), correo=usuario.get("correo"),
                nombre=usuario.get("nombre"))).inserted_primary_key[0]
        return {"id": uid, "fecha": _f(fecha), "tipo": tipo}

    def lista_no_detectados(self, limite=50):
        with self.motor.connect() as c:
            filas = c.execute(select(no_detectados).order_by(no_detectados.c.fecha.desc()).limit(limite)).all()
        return [{"id": f.id, "fecha": _f(f.fecha), "tipo": f.tipo, "tipo_nombre": TIPOS_EVENTO.get(f.tipo),
                 "lugar": f.lugar, "fuente": f.fuente, "fuente_nombre": FUENTES.get(f.fuente),
                 "observaciones": f.observaciones, "nombre": f.nombre, "registrado": _f(f.registrado)} for f in filas]
