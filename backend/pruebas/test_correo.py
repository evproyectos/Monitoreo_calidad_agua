"""Alertas por correo (correo.py): destinatarios por nivel, mensaje, reintentos y registro (RF-003.3, CU-04)."""

import smtplib
import time

import pytest

from monitoreo import alertas, correo
from monitoreo.usuarios import Usuarios

TEXTO_ROJO = ("<b>Alarma #1: Contaminación</b> (tipo sugerido)\n01/05/2026 06:00:00 · 1 sensor\n"
              "• <b>J10</b> (95 %): cloro 0,10 mg/L\n<b>Qué hacer:</b> tomar muestras &amp; aislar.\n"
              "https://127.0.0.1:8001/#/sensor/J10")
ASUNTO_ROJO = "Alerta roja · Alarma #1: contaminación en J10"


def rojo():
    return alertas.Aviso(TEXTO_ROJO, "rojo", ASUNTO_ROJO)


class ServidorFalso:
    """Hace de smtplib.SMTP: guarda lo que se manda y puede fallar con ciertos destinatarios."""
    enviados, sesiones, fallar_con = [], [], set()

    def __init__(self, servidor, puerto, timeout=None, context=None):
        ServidorFalso.sesiones.append({"servidor": servidor, "puerto": puerto, "tls": context is not None})

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self, context=None):
        ServidorFalso.sesiones[-1]["starttls"] = True

    def login(self, usuario, contrasena):
        ServidorFalso.sesiones[-1]["login"] = usuario

    def send_message(self, m):
        if m["To"] in ServidorFalso.fallar_con:
            ServidorFalso.fallar_con.discard(m["To"])            # falla una sola vez
            raise smtplib.SMTPServerDisconnected("se cortó la conexión")
        ServidorFalso.enviados.append(m)


@pytest.fixture
def smtp(monkeypatch):
    ServidorFalso.enviados, ServidorFalso.sesiones, ServidorFalso.fallar_con = [], [], set()
    monkeypatch.setattr(correo.smtplib, "SMTP", ServidorFalso)
    monkeypatch.setattr(correo.smtplib, "SMTP_SSL", ServidorFalso)
    return ServidorFalso


DESTINOS = {"rojo": ["ana@asada.cr", "luis@asada.cr"], "amarillo": ["ana@asada.cr", "marta@asada.cr"]}


def canal(**kw):
    return correo.CanalCorreo("smtp.ejemplo.com", 587, "alertas@ejemplo.com", "clave-de-aplicacion",
                              destinatarios=lambda nivel: DESTINOS.get(nivel, []), url="https://127.0.0.1:8001", **kw)


def test_cada_destinatario_del_nivel_recibe_su_propio_correo(smtp):
    assert canal().enviar(rojo()) == ["ana@asada.cr", "luis@asada.cr"]
    assert [m["To"] for m in smtp.enviados] == ["ana@asada.cr", "luis@asada.cr"]
    assert smtp.sesiones == [{"servidor": "smtp.ejemplo.com", "puerto": 587, "tls": False, "starttls": True,
                              "login": "alertas@ejemplo.com"}]
    m = smtp.enviados[0]
    assert m["Subject"] == "Alerta roja · Alarma #1: contaminación en J10"
    assert m["From"] == "ASADA La Lucha · Alertas <alertas@ejemplo.com>"


def test_mensaje_en_texto_y_html(smtp):
    canal().enviar(rojo())
    m = smtp.enviados[0]
    texto = m.get_body("plain").get_content()
    assert "<b>" not in texto and "tomar muestras & aislar." in texto and "J10 (95 %)" in texto
    pagina = m.get_body("html").get_content()
    assert "<b>Alarma #1: Contaminación</b>" in pagina and "#c62828" in pagina           # borde rojo
    assert '<li style="margin:3px 0"><b>J10</b> (95 %): cloro 0,10 mg/L</li>' in pagina
    assert 'href="https://127.0.0.1:8001/#/sensor/J10"' in pagina and "Abrir el tablero" in pagina
    assert "alertas críticas" in pagina and "página Usuarios" in pagina


def test_resumen_va_a_quien_recibe_cualquier_nivel(smtp):
    canal().enviar(alertas.Aviso("<b>Resumen</b>", "resumen"))
    assert sorted(m["To"] for m in smtp.enviados) == ["ana@asada.cr", "luis@asada.cr", "marta@asada.cr"]


def test_sin_destinatarios_no_se_reintenta():
    with pytest.raises(correo.SinDestinatarios):
        correo.CanalCorreo("smtp.ejemplo.com", remitente="a@b.cr").enviar(alertas.Aviso("x", "amarillo"))


def test_el_reintento_solo_va_a_los_que_faltan(smtp):
    smtp.fallar_con = {"luis@asada.cr"}
    c, aviso = canal(), rojo()
    with pytest.raises(smtplib.SMTPServerDisconnected):
        c.enviar(aviso)
    assert aviso.pendientes == ["luis@asada.cr"] and aviso.entregados == ["ana@asada.cr"]
    assert c.enviar(aviso) == ["ana@asada.cr", "luis@asada.cr"]
    assert [m["To"] for m in smtp.enviados] == ["ana@asada.cr", "luis@asada.cr"]          # nadie lo recibe dos veces


def test_seguridad_del_servidor():
    assert canal().seguridad == "starttls"
    assert correo.CanalCorreo("smtp.ejemplo.com", 465, "a@b.cr").seguridad == "ssl"
    assert correo.CanalCorreo("mailpit", 1025, remitente="a@b.cr", seguridad="ninguna").seguridad == "ninguna"
    with pytest.raises(ValueError):
        correo.CanalCorreo("smtp.ejemplo.com", 587, "a@b.cr", seguridad="tls1")
    with pytest.raises(ValueError, match="REMITENTE"):
        correo.CanalCorreo("smtp.ejemplo.com")


def test_servidor_de_prueba_sin_cifrado_ni_clave(smtp):
    correo.CanalCorreo("mailpit", 1025, remitente="alertas@asada.local", seguridad="ninguna",
                       destinatarios=lambda n: ["ana@asada.cr"]).enviar(rojo())
    assert smtp.sesiones == [{"servidor": "mailpit", "puerto": 1025, "tls": False}]


def test_llega_en_segundos_y_queda_registrado(smtp, tmp_path):
    """RF-003.3: la notificación sale en menos de 60 s; CU-04: el envío queda registrado."""
    cuentas = Usuarios(f"sqlite:///{tmp_path}/u.db")
    a = alertas.Alertas(canales=[canal()], registro=cuentas.anotar_notificacion)
    inicio = time.time()
    a.avisar(TEXTO_ROJO, "rojo", ASUNTO_ROJO)
    while not a.enviadas and time.time() - inicio < 5:
        time.sleep(0.01)
    assert a.enviadas == 1 and time.time() - inicio < 60
    (n,) = cuentas.ver_notificaciones()
    assert n["canal"] == "correo" and n["nivel"] == "rojo" and n["estado"] == "enviada"
    assert n["destinatarios"] == "ana@asada.cr, luis@asada.cr" and n["asunto"] == ASUNTO_ROJO


def test_falla_persistente_se_registra_y_no_frena_a_telegram(monkeypatch, smtp, tmp_path):
    esperar = time.sleep
    monkeypatch.setattr(alertas.time, "sleep", lambda s: esperar(0.001))
    cuentas = Usuarios(f"sqlite:///{tmp_path}/u.db")

    class Caido(correo.CanalCorreo):
        def _conectar(self):
            raise OSError("no hay ruta al servidor")

    class Telegram:
        nombre = "telegram"

        def enviar(self, aviso):
            return ["1 chat de Telegram"]

    a = alertas.Alertas(canales=[Caido("smtp.ejemplo.com", remitente="a@b.cr", destinatarios=lambda n: ["x@y.cr"]),
                                 Telegram()], registro=cuentas.anotar_notificacion)
    a.avisar(TEXTO_ROJO, "rojo", ASUNTO_ROJO)
    for _ in range(500):
        if a.fallidas and a.enviadas:
            break
        esperar(0.01)
    estados = {n["canal"]: n for n in cuentas.ver_notificaciones()}
    assert estados["telegram"]["estado"] == "enviada"
    assert estados["correo"]["estado"] == "fallida" and estados["correo"]["intentos"] == 4      # 1 + 3 reintentos
    assert estados["correo"]["error"] == "no hay ruta al servidor"
    assert estados["correo"]["destinatarios"] == "x@y.cr"                                      # a quién no llegó
    assert a.estado()["canales"]["correo"]["fallidas"] == 1


def test_sin_destinatarios_se_registra(smtp, tmp_path):
    cuentas = Usuarios(f"sqlite:///{tmp_path}/u.db")
    a = alertas.Alertas(canales=[correo.CanalCorreo("smtp.ejemplo.com", remitente="a@b.cr")],
                        registro=cuentas.anotar_notificacion)
    a._envios[0].mandar(alertas.Aviso("<b>Aviso</b>", "amarillo"))
    (n,) = cuentas.ver_notificaciones()
    assert n["estado"] == "sin_destinatarios" and n["asunto"] == "Aviso" and not smtp.enviados


def test_correo_de_prueba(smtp):
    a = alertas.Alertas(canales=[canal()])
    assert a.probar_correo("admin@asada.cr") is None
    (m,) = smtp.enviados
    assert m["To"] == "admin@asada.cr" and m["Subject"] == "ASADA La Lucha · Correo de prueba de las alertas"
    sin = alertas.Alertas(canales=[alertas.CanalConsola()])
    assert "no está configurado" in sin.probar_correo("admin@asada.cr")


def test_destinatarios_desde_los_usuarios(tmp_path):
    cuentas = Usuarios(f"sqlite:///{tmp_path}/u.db")
    cuentas.crear("Ana", "ana@asada.cr", "operador", "una-clave-larga")
    cuentas.crear("Carmen", "carmen@asada.cr", "junta", "una-clave-larga")
    cuentas.crear("Beto", "beto@asada.cr", "administrador", "una-clave-larga")
    assert cuentas.destinatarios("rojo") == ["ana@asada.cr", "beto@asada.cr"]
    assert cuentas.destinatarios("amarillo") == ["ana@asada.cr"]
    ana = next(u for u in cuentas.lista() if u["correo"] == "ana@asada.cr")
    cuentas.modificar(ana["id"], {"activo": False}, por="beto@asada.cr")
    assert cuentas.destinatarios("rojo") == ["beto@asada.cr"]                # desactivada: no recibe
    assert cuentas.destinatarios("amarillo") == []


def test_errores_del_servidor_en_palabras():
    import socket
    assert "contraseña de aplicación" in correo.explicar(smtplib.SMTPAuthenticationError(535, b"5.7.8 rechazado"))
    assert "revisa SMTP_SERVIDOR" in correo.explicar(socket.gaierror(-2, "Name or service not known"))
    assert "no hubo respuesta" in correo.explicar(TimeoutError("timed out"))
    assert correo.explicar(RuntimeError("otra cosa")) == "otra cosa"
