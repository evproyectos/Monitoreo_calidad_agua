"""Nombres de los lugares de medición (lugares.py y /api/lugares)."""

import time

import pytest
from fastapi.testclient import TestClient

from conftest import ModelosFalsos, configuracion
from monitoreo import alertas
from monitoreo import lugares as lg
from monitoreo import servicio as srv
from monitoreo import usuarios as us
from monitoreo.motor import Motor

CLAVE = "una-clave-larga-1"
CODIGOS = ["J280", "J10", "J101"]


@pytest.fixture
def lugares(tmp_path):
    return lg.Lugares(f"sqlite:///{tmp_path / 'lugares.db'}")


def test_sin_cambios_usa_los_ejemplos_y_si_no_el_codigo(lugares):
    lista = lugares.lista(CODIGOS)
    assert [x["codigo"] for x in lista] == CODIGOS                       # en el orden pedido
    assert lista[0] == {"codigo": "J280", "nombre": "Tanque de almacenamiento", "zona": "Salida de la naciente",
                        "propio": False}
    assert lista[1]["nombre"] == "J10" and lista[1]["zona"] == ""        # sin ejemplo: el código


def test_el_administrador_cambia_los_nombres(lugares):
    lugares.guardar([{"codigo": "J10", "nombre": "  Pulpería   La Esquina ", "zona": "Centro"}], CODIGOS, por="a@b.cr")
    por_codigo = {x["codigo"]: x for x in lugares.lista(CODIGOS)}
    assert por_codigo["J10"] == {"codigo": "J10", "nombre": "Pulpería La Esquina", "zona": "Centro", "propio": True}
    assert lugares.nombres(CODIGOS)["J280"] == "Tanque de almacenamiento"
    # en otra instancia (otro proceso, o al reiniciar) sigue igual
    otra = lg.Lugares(str(lugares.motor.url))
    assert otra.nombres(CODIGOS)["J10"] == "Pulpería La Esquina"


@pytest.mark.parametrize("cambio, mensaje", [
    ({"codigo": "J999", "nombre": "X"}, "No hay ningún sensor J999"),
    ({"codigo": "J10", "nombre": "   "}, "Falta el nombre"),
    ({"codigo": "J10", "nombre": "x" * (lg.NOMBRE_MAX + 1)}, "hasta"),
    ({"codigo": "J10", "nombre": "escuela"}, "no pueden llamarse igual"),           # J101 ya es «Escuela»
])
def test_validaciones(lugares, cambio, mensaje):
    with pytest.raises(lg.ErrorLugares, match=mensaje):
        lugares.guardar([cambio], CODIGOS)


def test_codigos_por_nombres_en_los_mensajes():
    n = {"J10": "Plaza", "J101": "Escuela <norte>", "J280": "J280"}
    assert lg.con_nombres("Cloro bajo en J10 y J101; J1010 no existe", n) == \
        "Cloro bajo en Plaza (J10) y Escuela &lt;norte&gt; (J101); J1010 no existe"
    assert lg.con_nombres("Sensores J10, J280", n, escapar=False) == "Sensores Plaza (J10), J280"
    assert lg.con_nombres("sin sensores", n) == "sin sensores" and lg.con_nombres(None, n) is None


def test_las_alertas_salen_con_el_nombre_del_lugar():
    class Canal:
        nombre = "prueba"

        def __init__(self):
            self.avisos = []

        def enviar(self, aviso):
            self.avisos.append(aviso)
            return ["alguien"]
    canal = Canal()
    al = alertas.Alertas(canal=canal, nombres=lambda: {"J10": "Plaza"})
    al.avisar("<b>Cloro bajo en J10</b>\nRevisar la dosis", asunto="Alerta roja: cloro bajo en J10")
    for _ in range(200):
        if canal.avisos:
            break
        time.sleep(0.01)
    assert canal.avisos[0].texto.startswith("<b>Cloro bajo en Plaza (J10)</b>")
    assert canal.avisos[0].asunto == "Alerta roja: cloro bajo en Plaza (J10)"


# ---------------------------------------------------------------------------- por la API
@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.delenv("TELEGRAM_TOKEN", raising=False)
    monkeypatch.setattr(srv, "Motor", lambda cfg: Motor(cfg, ModelosFalsos(), registrar=False))
    monkeypatch.setattr(srv, "ClienteDatos", lambda url: type("D", (), {"lecturas_desde": lambda self, d=None: []})())
    cfg = configuracion(tmp_path, inicio_sesion=True)
    cuentas = us.Usuarios(cfg.base_usuarios)
    cuentas.crear("Admin", "admin@asada.cr", "administrador", CLAVE, debe_cambiar=False)
    cuentas.crear("Beto", "beto@asada.cr", "junta", CLAVE, debe_cambiar=False)
    with TestClient(srv.crear_app(cfg)) as c:
        c.cuentas = cuentas
        yield c


def entrar(c, correo):
    assert c.post("/api/sesion", json={"correo": correo, "contrasena": CLAVE}).status_code == 200


def test_todos_ven_los_lugares_y_solo_el_administrador_los_cambia(api):
    entrar(api, "beto@asada.cr")
    r = api.get("/api/lugares")
    assert r.status_code == 200
    assert {x["codigo"]: x["nombre"] for x in r.json()["lugares"]}["J280"] == "Tanque de almacenamiento"
    cambio = {"lugares": [{"codigo": "J10", "nombre": "Plaza", "zona": "Centro"}]}
    assert api.put("/api/lugares", json=cambio).status_code == 403
    entrar(api, "admin@asada.cr")
    r = api.put("/api/lugares", json=cambio)
    assert r.status_code == 200 and {x["codigo"]: x["nombre"] for x in r.json()["lugares"]}["J10"] == "Plaza"
    assert api.cuentas.ver_bitacora()[0]["accion"] == "lugares_modificados"
    r = api.put("/api/lugares", json={"lugares": [{"codigo": "J10", "nombre": "x" * 61}]})
    assert r.status_code == 422
    r = api.put("/api/lugares", json={"lugares": [{"codigo": "NO", "nombre": "Otro"}]})
    assert r.status_code == 400 and "No hay ningún sensor" in r.json()["detail"]["error"]
