"""F1 de las alarmas en producción (rendimiento.py, RF-004.2 y RNF-003)."""

import io
import json
import urllib.error

import pytest
from fastapi.testclient import TestClient

from conftest import ModelosFalsos, configuracion, lecturas
from monitoreo import alertas
from monitoreo import gestion as ge
from monitoreo import rendimiento as re_
from monitoreo import servicio as srv
from monitoreo import usuarios as us
from monitoreo.motor import Motor

ANA = {"correo": "ana@asada.cr", "nombre": "Ana Mora"}


@pytest.fixture
def g(tmp_path):
    gestion = ge.GestionAlertas(f"sqlite:///{tmp_path}/g.db")
    yield gestion
    gestion.motor.dispose()


@pytest.fixture
def r(g, monkeypatch):
    monkeypatch.delenv("MLFLOW_URL", raising=False)
    return re_.Rendimiento(g)


def alerta(g, inicio, resultado=None, tipo="alarma", grupo=None):
    nivel = "rojo" if tipo in ("alarma", "fuga") else "amarillo"
    uid, _ = g.abrir(grupo=grupo or f"{tipo}:{inicio}", inicio=inicio, tipo=tipo, nivel=nivel, titulo="Evento",
                     evento="contaminacion")
    if resultado:
        g.cerrar(uid, ANA, resultado, "Se revisó en campo.")
    return uid


def test_metricas():
    vacio = {"precision": None, "sensibilidad": None, "f1": None, "casos": 0, "estado": "sin_datos"}
    assert re_.metricas(0, 0, 0, 3, 0.75) == vacio
    m = re_.metricas(3, 1, 2, 3, 0.75)
    assert m["precision"] == 0.75 and m["sensibilidad"] == 0.6 and m["f1"] == pytest.approx(6 / 9)
    assert m["estado"] == "bajo"
    assert re_.metricas(8, 1, 1, 3, 0.75)["estado"] == "bien"
    assert re_.metricas(1, 0, 0, 3, 0.75)["estado"] == "sin_datos"         # un caso no basta para avisar
    assert re_.metricas(0, 2, 2, 3, 0.75)["f1"] == 0.0                      # nada acertado: F1 0, no un error


def test_calcular_con_lo_verificado_en_campo(g, r):
    alerta(g, "2026-05-02 06:00", "confirmada")
    alerta(g, "2026-05-03 06:00", "confirmada", tipo="fuga")
    alerta(g, "2026-05-04 06:00", "descartada")
    alerta(g, "2026-05-05 06:00", "inconclusa")                         # no cuenta
    alerta(g, "2026-05-06 06:00")                                       # sigue abierta: sin verificar
    alerta(g, "2026-05-06 08:00", "descartada", tipo="aviso")           # los avisos no cuentan
    alerta(g, "2026-04-20 06:00", "descartada")                         # fuera de la ventana
    r.registrar_no_detectado(ANA, "2026-05-07 10:00", "contaminacion", "J224", "laboratorio",
                             "Cloro residual 0,1 mg/L en la muestra semanal.")
    x = r.calcular("2026-05-08 00:00")
    assert (x["confirmadas"], x["descartadas"], x["no_detectados"], x["sin_verificar"]) == (2, 1, 1, 2)
    assert x["f1"] == pytest.approx(4 / 6) and x["precision"] == pytest.approx(2 / 3) and x["sensibilidad"] == 2 / 3
    assert x["estado"] == "bajo" and x["desde"] == "2026-05-01T00:00"


def test_no_detectado_valida_los_datos(r):
    for malo in [dict(tipo="otro"), dict(fuente="vecino"), dict(observaciones="x"), dict(fecha="ayer")]:
        datos = {"fecha": "2026-05-07 10:00", "tipo": "fuga", "lugar": None, "fuente": "reporte",
                 "observaciones": "Agua saliendo en la calle frente a la escuela.", **malo}
        with pytest.raises(ge.ErrorGestion):
            r.registrar_no_detectado(ANA, **datos)
    assert r.lista_no_detectados() == []


class MlflowFalso:
    def __init__(self, falla=False):
        self.corridas, self.falla = [], falla

    def registrar(self, x, params):
        if self.falla:
            raise ConnectionError("MLflow apagado")
        self.corridas.append((x["hasta"], x["f1"], params))
        return f"run{len(self.corridas)}"


def test_una_vez_por_dia_en_la_base_y_en_mlflow(g, r):
    for d in (2, 3, 4):
        alerta(g, f"2026-05-0{d} 06:00", "confirmada")
    r.mlflow = MlflowFalso()
    assert r.diario(None, "2026-05-08 03:00") is None                    # al arrancar no se calcula
    x = r.diario("2026-05-07 20:00", "2026-05-08 03:00")
    assert x["hasta"] == "2026-05-08T00:00" and x["f1"] == 1.0 and x["estado"] == "bien" and x["mlflow_run"] == "run1"
    assert r.diario("2026-05-07 20:00", "2026-05-08 05:00") is None      # ya estaba (servicio reiniciado)
    r.diario("2026-05-08 05:00", "2026-05-10 01:00")                     # pasa por dos medianoches
    h = r.historial()
    assert [d["fecha"] for d in h] == ["2026-05-08T00:00", "2026-05-09T00:00", "2026-05-10T00:00"]
    assert [c[0] for c in r.mlflow.corridas] == [d["fecha"] for d in h]
    assert r.mlflow.corridas[0][2] == {"ventana_dias": 7, "f1_minimo": 0.75, "minimo_casos": 3}


def test_sin_mlflow_se_guarda_igual(g, r, capsys):
    r.mlflow = MlflowFalso(falla=True)
    x = r.diario("2026-05-07 23:00", "2026-05-08 00:00")
    assert x["mlflow_run"] is None and "MLflow apagado" in r.ultimo_error_mlflow
    assert r.historial()[0]["estado"] == "sin_datos" and "No se pudo registrar" in capsys.readouterr().out


def test_cliente_rest_de_mlflow(monkeypatch):
    pedidos = []

    def urlopen(req, timeout):
        ruta = req.full_url.split("/api/2.0/mlflow/")[1]
        cuerpo = json.loads(req.data) if req.data else None
        pedidos.append((ruta.split("?")[0], cuerpo))
        if ruta.startswith("experiments/get-by-name"):
            raise urllib.error.HTTPError(req.full_url, 404, "no existe", {}, io.BytesIO(b"{}"))
        respuesta = {"experiments/create": {"experiment_id": "7"},
                     "runs/create": {"run": {"info": {"run_id": "abc"}}}}.get(ruta, {})
        return io.BytesIO(json.dumps(respuesta).encode())

    monkeypatch.setattr(re_.urllib.request, "urlopen", urlopen)
    m = re_.Mlflow("http://mlflow:5000/")
    x = {"hasta": "2026-05-08T00:00", "estado": "bajo", "f1": 0.6, "precision": 0.75, "sensibilidad": None,
         "confirmadas": 3, "descartadas": 1, "no_detectados": 0, "sin_verificar": 2}
    assert m.registrar(x, {"ventana_dias": 7}) == "abc"
    assert [p[0] for p in pedidos] == ["experiments/get-by-name", "experiments/create", "runs/create",
                                       "runs/log-batch", "runs/update"]
    assert pedidos[1][1] == {"name": "monitoreo_produccion"} and pedidos[2][1]["experiment_id"] == "7"
    metricas = {m_["key"]: m_["value"] for m_ in pedidos[3][1]["metrics"]}
    assert metricas["f1_7d"] == 0.6 and "sensibilidad_7d" not in metricas and metricas["sin_verificar_7d"] == 2
    assert pedidos[4][1]["status"] == "FINISHED"


def test_se_avisa_cuando_el_f1_baja(cfg, g):
    class RendimientoBajo:
        dias, f1_minimo = 7, 0.75

        def diario(self, anterior, ahora):
            return {"estado": "bajo", "f1": 0.5, "confirmadas": 2, "descartadas": 2, "no_detectados": 2}

    al = alertas.Alertas(canal=alertas.CanalConsola(), rendimiento=RendimientoBajo())
    al.avisos = []
    al.avisar = lambda texto, nivel="rojo", asunto=None, enlace=None: al.avisos.append((texto, nivel, asunto))
    motor = Motor(cfg, ModelosFalsos(), registrar=False)
    for k in range(3):
        for x in lecturas(3)[k * 4:(k + 1) * 4]:
            motor.recibir(x["fecha"], x["valores"])
        al.revisar(motor, motor.procesar())
    texto, nivel, asunto = next(a for a in al.avisos if "F1" in (a[2] or ""))
    assert nivel == "amarillo" and "50 %" in asunto and "meta ≥ 75 %" in asunto
    assert "2 eventos que no se detectaron" in texto


# ---------------------------------------------------------------------------- por la API
CLAVE = "una-clave-larga-1"


@pytest.fixture
def api(tmp_path, monkeypatch):
    for v in ("TELEGRAM_TOKEN", "SMTP_SERVIDOR", "MLFLOW_URL"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setattr(srv, "Motor", lambda cfg: Motor(cfg, ModelosFalsos(), registrar=False))
    monkeypatch.setattr(srv, "ClienteDatos", lambda url: type("D", (), {"lecturas_desde": lambda self, d=None: []})())
    cfg = configuracion(tmp_path, inicio_sesion=True)
    cuentas = us.Usuarios(cfg.base_usuarios)
    cuentas.crear("Ana Mora", "ana@asada.cr", "operador", CLAVE, debe_cambiar=False)
    cuentas.crear("Carmen Solís", "carmen@asada.cr", "junta", CLAVE, debe_cambiar=False)
    with TestClient(srv.crear_app(cfg)) as c:
        yield c


def entrar(c, correo):
    assert c.post("/api/sesion", json={"correo": correo, "contrasena": CLAVE}).status_code == 200


def test_rendimiento_por_la_api(api):
    datos = {"fecha": "2026-05-07T10:00", "tipo": "fuga", "lugar": "Calle de la escuela", "fuente": "reporte",
             "observaciones": "Un vecino reportó agua saliendo en la calle."}
    assert api.get("/api/rendimiento").status_code == 401
    entrar(api, "carmen@asada.cr")
    x = api.get("/api/rendimiento").json()
    assert x["actual"]["estado"] == "sin_datos" and x["ventana_dias"] == 7 and x["f1_minimo"] == 0.75
    assert x["mlflow"]["configurado"] is False
    r = api.post("/api/rendimiento/no-detectados", json=datos)
    assert r.status_code == 403                                          # la junta no registra
    api.delete("/api/sesion")
    entrar(api, "ana@asada.cr")
    r = api.post("/api/rendimiento/no-detectados", json=datos)
    assert r.status_code == 201 and r.json()["tipo"] == "fuga"
    (n,) = api.get("/api/rendimiento/no-detectados").json()
    assert n["nombre"] == "Ana Mora" and n["fuente_nombre"] == "Reporte de un abonado"
    assert api.post("/api/rendimiento/no-detectados", json={**datos, "tipo": "x"}).status_code == 400
    assert api.post("/api/rendimiento/no-detectados", json={"tipo": "fuga"}).status_code == 422
