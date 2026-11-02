"""Seguridad (seguridad.py): clave de API, registro de intentos, .env y HTTPS con TLS 1.2 o más."""

import socket
import ssl
import threading
import time

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

import monitoreo
from monitoreo import seguridad
from monitoreo.config import Config


@pytest.fixture
def app_protegida(tmp_path):
    registro = seguridad.RegistroAccesos(tmp_path)
    app = FastAPI()

    @app.post("/protegido", dependencies=[Depends(seguridad.exigir_clave(registro))])
    def protegido():
        return {"ok": True}

    @app.get("/libre")
    def libre():
        return {"ok": True}

    return TestClient(app), registro.ruta


def test_sin_claves_configuradas_el_endpoint_no_queda_abierto(app_protegida, monkeypatch):
    cliente, _ = app_protegida
    monkeypatch.delenv("CLAVES_API", raising=False)
    r = cliente.post("/protegido", headers={"X-API-Key": "cualquiera"})
    assert r.status_code == 503 and "CLAVES_API" in r.json()["detail"]["detalles"][0]


def test_clave_valida_ausente_o_equivocada(app_protegida, monkeypatch):
    cliente, registro = app_protegida
    monkeypatch.setenv("CLAVES_API", " clave-vieja , clave-nueva ")
    assert cliente.post("/protegido", headers={"X-API-Key": "clave-nueva"}).status_code == 200
    assert cliente.post("/protegido", headers={"X-API-Key": "clave-vieja"}).status_code == 200
    r = cliente.post("/protegido")
    assert r.status_code == 401 and r.headers["WWW-Authenticate"] == "ApiKey"
    assert r.json()["detail"]["error"] == "Clave de API ausente o inválida."
    assert cliente.post("/protegido", headers={"X-API-Key": "adivinada"}).status_code == 401
    assert cliente.get("/libre").status_code == 200               # lo demás no pide clave
    # cada intento rechazado queda anotado, sin la clave que se mandó
    lineas = registro.read_text(encoding="utf-8").splitlines()
    assert len(lineas) == 2
    assert lineas[0].endswith("POST /protegido · sin clave") and lineas[1].endswith("· clave inválida")
    assert "adivinada" not in registro.read_text(encoding="utf-8")


def test_el_env_carga_variables_sin_pisar_las_del_sistema(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("PRUEBA_DESDE_ENV=del-archivo\nPRUEBA_DEL_SISTEMA=del-archivo\n", encoding="utf-8")
    monkeypatch.setenv("PRUEBA_DEL_SISTEMA", "del-sistema")
    monkeypatch.delenv("PRUEBA_DESDE_ENV", raising=False)
    assert monitoreo.cargar_env(env) is True
    import os
    assert os.environ["PRUEBA_DESDE_ENV"] == "del-archivo"
    assert os.environ["PRUEBA_DEL_SISTEMA"] == "del-sistema"
    monkeypatch.delenv("PRUEBA_DESDE_ENV")
    assert monitoreo.cargar_env(tmp_path / "no_existe.env") is False


def test_rutas_tls_relativas_a_la_raiz(monkeypatch):
    monkeypatch.setenv("CERTIFICADO_TLS", "secretos/certificado.pem")
    monkeypatch.setenv("CLAVE_TLS", "  ")
    c = Config()
    assert c.certificado_tls == monitoreo.ARCHIVO_ENV.parent / "secretos" / "certificado.pem"
    assert c.clave_tls is None and c.esquema == "https"
    monkeypatch.delenv("CERTIFICADO_TLS")
    assert Config().esquema == "http"


def test_https_falta_un_archivo_o_una_variable(tmp_path):
    with pytest.raises(SystemExit, match="CERTIFICADO_TLS y CLAVE_TLS"):
        seguridad.servidor(FastAPI(), "127.0.0.1", 0, certificado=tmp_path / "c.pem")
    with pytest.raises(SystemExit, match="No se encontró"):
        seguridad.servidor(FastAPI(), "127.0.0.1", 0, tmp_path / "c.pem", tmp_path / "k.pem")


def puerto_libre():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.mark.filterwarnings("ignore::DeprecationWarning")    # el cliente TLS 1.1 es a propósito
def test_https_con_tls_12_como_minimo(tmp_path):
    r = seguridad.generar_certificado(tmp_path)
    assert r["windows"].stat().st_size > 0
    app = FastAPI()

    @app.get("/health")
    def salud():
        return {"estado": "ok"}

    puerto = puerto_libre()
    srv = seguridad.servidor(app, "127.0.0.1", puerto, r["certificado"], r["clave"], log_level="warning")
    assert srv.config.ssl.minimum_version == ssl.TLSVersion.TLSv1_2
    hilo = threading.Thread(target=srv.run, daemon=True)
    hilo.start()
    try:
        for _ in range(200):
            if srv.started:
                break
            time.sleep(0.02)
        # un cliente que confía en el certificado se conecta con TLS 1.2 o más
        ctx = ssl.create_default_context(cafile=str(r["certificado"]))
        with socket.create_connection(("127.0.0.1", puerto)) as s, ctx.wrap_socket(s, server_hostname="127.0.0.1") as t:
            assert t.version() in ("TLSv1.2", "TLSv1.3")
        # uno que solo habla TLS 1.1 es rechazado
        viejo = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        viejo.check_hostname, viejo.verify_mode = False, ssl.CERT_NONE
        try:
            viejo.minimum_version = viejo.maximum_version = ssl.TLSVersion.TLSv1_1
        except (ValueError, ssl.SSLError):
            pytest.skip("este Python no permite clientes TLS 1.1")
        with pytest.raises((ssl.SSLError, ConnectionResetError, OSError)):
            with socket.create_connection(("127.0.0.1", puerto)) as s, viejo.wrap_socket(s):
                pass
    finally:
        srv.should_exit = True
        hilo.join(timeout=5)
