"""Cabeceras de seguridad, tope de tamaño, /health y documentación (servicio.Proteccion, RNF-004)."""

import pytest
from fastapi.testclient import TestClient

from conftest import ModelosFalsos, configuracion
from monitoreo import seguridad
from monitoreo import servicio as srv
from monitoreo import usuarios as us
from monitoreo.motor import Motor

CLAVE = "una-clave-larga-1"
CLAVE_API = "clave-de-api-de-prueba-1"


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.delenv("TELEGRAM_TOKEN", raising=False)
    monkeypatch.setenv("CLAVES_API", CLAVE_API)
    monkeypatch.setattr(srv, "Motor", lambda cfg: Motor(cfg, ModelosFalsos(), registrar=False))
    monkeypatch.setattr(srv, "ClienteDatos", lambda url: type("D", (), {"lecturas_desde": lambda self, d=None: []})())
    cfg = configuracion(tmp_path, inicio_sesion=True)
    cuentas = us.Usuarios(cfg.base_usuarios)
    cuentas.crear("Admin", "admin@asada.cr", "administrador", CLAVE, debe_cambiar=False)
    cuentas.crear("Beto", "beto@asada.cr", "junta", CLAVE, debe_cambiar=False)
    with TestClient(srv.crear_app(cfg)) as c:
        yield c


def entrar(c, correo):
    assert c.post("/api/sesion", json={"correo": correo, "contrasena": CLAVE}).status_code == 200


def test_cabeceras_de_seguridad_en_todas_las_respuestas(api):
    for r in (api.get("/api/sesion"), api.get("/health"), api.get("/no-existe")):
        h = r.headers
        assert "default-src 'self'" in h["content-security-policy"]
        assert "frame-ancestors 'none'" in h["content-security-policy"]
        assert "unsafe-inline" not in h["content-security-policy"]
        assert h["x-frame-options"] == "DENY" and h["x-content-type-options"] == "nosniff"
        assert h["referrer-policy"] == "same-origin"
        assert "strict-transport-security" not in h                    # sin HTTPS no tiene sentido


def test_el_script_en_linea_del_tablero_va_por_su_huella(tmp_path):
    """El script que precarga los datos (RNF-001) corre; cualquier otro en línea no."""
    import base64
    import hashlib
    script = "\n  window.__precarga = {};\n"
    html = f'<html><script type="module" src="/a.js"></script><script>{script}</script></html>'
    (tmp_path / "index.html").write_bytes(html.replace("\n", "\r\n").encode())        # como en Windows
    huella = base64.b64encode(hashlib.sha256(script.encode()).digest()).decode()   # con LF, como el navegador
    csp = srv.csp_del_tablero(tmp_path / "index.html")
    assert f"script-src 'self' 'sha256-{huella}';" in csp and "unsafe-inline" not in csp
    assert "script-src 'self';" in srv.csp_del_tablero(tmp_path / "no-existe.html")


def test_con_https_tambien_hsts(tmp_path):
    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})
    r = TestClient(srv.Proteccion(app, https=True)).get("/")
    assert r.headers["strict-transport-security"].startswith("max-age=")


def test_el_servidor_no_dice_que_es_uvicorn():
    s = seguridad.servidor(lambda *a: None, "127.0.0.1", 0)
    assert s.config.server_header is False


def test_solicitud_demasiado_grande_responde_413(api):
    grande = b'{"correo": "a@b.cr", "contrasena": "' + b"x" * srv.LIMITE_CUERPO + b'"}'
    r = api.post("/api/sesion", content=grande, headers={"content-type": "application/json"})
    assert r.status_code == 413 and "demasiado grande" in r.json()["detail"]["error"]
    assert r.headers["x-frame-options"] == "DENY"

    def por_partes():                                                  # sin Content-Length (chunked)
        yield b'{"correo": "a@b.cr", "contrasena": "'
        for _ in range(srv.LIMITE_CUERPO // 4096 + 2):
            yield b"x" * 4096
        yield b'"}'
    r = api.post("/api/sesion", content=por_partes(), headers={"content-type": "application/json"})
    assert r.status_code == 413
    # una solicitud normal sigue pasando
    assert api.post("/api/sesion", json={"correo": "admin@asada.cr", "contrasena": CLAVE}).status_code == 200


def test_predict_admite_mas_pero_no_sin_limite(api):
    r = api.post("/predict/contaminacion", content=b"x" * (srv.LIMITE_CUERPO + 1),
                 headers={"content-type": "application/json", seguridad.ENCABEZADO: CLAVE_API})
    assert r.status_code == 422                                          # pasó el tope; falla por el formato
    r = api.post("/predict/contaminacion", content=b"x" * (srv.LIMITE_CUERPO_PREDICT + 1),
                 headers={"content-type": "application/json", seguridad.ENCABEZADO: CLAVE_API})
    assert r.status_code == 413


def test_health_en_publico_solo_dice_el_estado(api):
    r = api.get("/health")
    assert r.status_code in (200, 503) and set(r.json()) == {"estado"}
    detalle = api.get("/health", headers={seguridad.ENCABEZADO: CLAVE_API}).json()
    assert {"problemas", "version", "modelos"} <= set(detalle)
    entrar(api, "beto@asada.cr")                                       # Junta: igual que en público
    assert set(api.get("/health").json()) == {"estado"}
    entrar(api, "admin@asada.cr")
    assert "modelos" in api.get("/health").json()


def test_documentacion_solo_para_el_administrador_o_con_clave(api):
    for ruta in ("/docs", "/redoc", "/openapi.json"):
        r = api.get(ruta)
        assert r.status_code == 401 and "administrador" in r.json()["detail"]["error"]
    assert api.get("/openapi.json", headers={seguridad.ENCABEZADO: CLAVE_API}).json()["info"]["title"]
    entrar(api, "beto@asada.cr")
    assert api.get("/docs").status_code == 401
    entrar(api, "admin@asada.cr")
    r = api.get("/docs")
    assert r.status_code == 200 and "swagger-ui" in r.text
    assert "cdn.jsdelivr.net" in r.headers["content-security-policy"]   # Swagger UI se carga de ahí
    assert "/predict/contaminacion" in api.get("/openapi.json").json()["paths"]
