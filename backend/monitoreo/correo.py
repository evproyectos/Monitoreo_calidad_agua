"""
Envío de las alertas por correo electrónico (SMTP) a los destinatarios que elige el administrador en
la página Usuarios del dashboard (RF-003.3, CU-04 y CU-07).

Quién recibe qué
  rojo       alarmas y posibles fugas (al abrirse y al cerrarse): quien tiene marcadas las críticas
  amarillo   avisos anticipados, riesgo en 24 h y sensores que se apartan de lo habitual: quien
             tiene marcadas las predictivas
  resumen    el resumen diario: quien tiene marcada cualquiera de las dos
Cada destinatario recibe su propio correo (no ve a los demás). Si un envío falla, se reintenta solo
con los que faltan, así nadie lo recibe dos veces.

Configuración (en el .env o como variables de entorno; la contraseña nunca va en el código ni en git):
  SMTP_SERVIDOR     p. ej. smtp.gmail.com; sin él no se mandan correos
  SMTP_PUERTO       587 por defecto (465 para SSL directo, 1025 para Mailpit)
  SMTP_SEGURIDAD    starttls (por defecto), ssl o ninguna (solo para un servidor de prueba local);
                    con el puerto 465 es ssl si no se indica
  SMTP_USUARIO      cuenta con la que se entra al servidor (con Gmail, el correo completo)
  SMTP_CONTRASENA   su contraseña (con Gmail, una contraseña de aplicación de 16 letras)
  SMTP_REMITENTE    dirección que aparece como remitente (por defecto SMTP_USUARIO)

Prueba (desde backend/, con las variables definidas):
  python -m monitoreo.correo --prueba destino@correo.com
"""

import argparse
import html
import os
import re
import smtplib
import socket
import ssl
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

NOMBRE_REMITENTE = "ASADA La Lucha · Alertas"
COLOR = {"rojo": "#c62828", "amarillo": "#b7791f", "resumen": "#1f6feb", "prueba": "#1f6feb"}
MOTIVO = {"rojo": "las alertas críticas (alarmas y fugas)",
          "amarillo": "las alertas predictivas (avisos anticipados y riesgo en 24 h)",
          "resumen": "las alertas", "prueba": "las alertas"}
URL = re.compile(r"^https?://\S+$")


class SinDestinatarios(Exception):
    """Nadie tiene marcado ese nivel: no hay a quién mandarlo (no se reintenta)."""


def explicar(e):
    """El error del envío en palabras para el administrador."""
    if isinstance(e, smtplib.SMTPAuthenticationError):
        return ("el servidor rechazó el usuario o la contraseña (con Gmail hace falta una contraseña de "
                "aplicación, no la contraseña normal de la cuenta)")
    if isinstance(e, smtplib.SMTPRecipientsRefused):
        return "el servidor no aceptó la dirección de destino: " + ", ".join(e.recipients)
    if isinstance(e, smtplib.SMTPSenderRefused):
        return f"el servidor no aceptó el remitente {e.sender} (SMTP_REMITENTE debe ser la cuenta o un alias suyo)"
    if isinstance(e, ssl.SSLCertVerificationError):
        return f"no se pudo verificar el certificado del servidor de correo ({e.verify_message})"
    if isinstance(e, smtplib.SMTPNotSupportedError):
        return "el servidor no acepta STARTTLS en ese puerto (prueba SMTP_PUERTO=465)"
    if isinstance(e, (TimeoutError, ConnectionRefusedError)) or "timed out" in str(e):
        return "no hubo respuesta del servidor de correo (revisa SMTP_SERVIDOR, SMTP_PUERTO y la conexión a internet)"
    if isinstance(e, socket.gaierror):
        return "no se encontró el servidor de correo (revisa SMTP_SERVIDOR)"
    return str(e)


def configurado():
    return bool(os.environ.get("SMTP_SERVIDOR", "").strip())


def _texto_plano(texto):
    return html.unescape(re.sub(r"</?b>", "", texto))


def cuerpo_html(texto, nivel, url=None):
    """El mensaje de la alerta (el mismo de Telegram: líneas con <b> y texto ya escapado) como
    correo HTML sencillo, con estilos en línea para que se vea igual en Gmail, Outlook y el celular."""
    lineas = texto.split("\n")
    titulo, resto = lineas[0], lineas[1:]
    enlace = url
    partes, lista = [], []

    def cerrar_lista():
        if lista:
            partes.append('<ul style="margin:8px 0 12px;padding-left:20px">' + "".join(
                f'<li style="margin:3px 0">{x}</li>' for x in lista) + "</ul>")
            lista.clear()

    for ln in resto:
        if URL.match(ln.strip()):
            enlace = ln.strip()
            continue
        if ln.startswith("• "):
            lista.append(ln[2:])
            continue
        cerrar_lista()
        if ln.strip():
            partes.append(f'<p style="margin:0 0 10px">{ln}</p>')
    cerrar_lista()
    boton = (f'<p style="margin:18px 0 6px"><a href="{html.escape(enlace, quote=True)}" '
             'style="background:#0b5cad;color:#ffffff;text-decoration:none;padding:10px 18px;'
             'border-radius:8px;font-weight:700;display:inline-block">Abrir el tablero</a></p>') if enlace else ""
    return (
        '<!doctype html><html lang="es"><body style="margin:0;padding:16px;background:#f2f5f8">'
        '<div style="max-width:620px;margin:0 auto;background:#ffffff;border-radius:12px;overflow:hidden;'
        'font-family:Segoe UI,Roboto,Arial,sans-serif;font-size:15px;line-height:1.5;color:#1f2933">'
        f'<div style="border-left:6px solid {COLOR.get(nivel, "#1f6feb")};padding:14px 18px;background:#f7f9fb">'
        '<div style="font-size:12px;color:#52606d;letter-spacing:.04em;text-transform:uppercase">'
        'ASADA La Lucha · Alertas tempranas de calidad del agua</div>'
        f'<div style="font-size:19px;font-weight:700;margin-top:4px">{titulo}</div></div>'
        f'<div style="padding:16px 18px 18px">{"".join(partes)}{boton}</div>'
        '<div style="padding:12px 18px;border-top:1px solid #e4e7eb;font-size:12px;color:#7b8794">'
        f'Recibes este correo porque el administrador de la ASADA te incluyó entre quienes reciben '
        f'{MOTIVO.get(nivel, "las alertas")}. Para dejar de recibirlas, pídele que lo cambie en la página '
        'Usuarios del tablero.</div></div></body></html>')


class CanalCorreo:
    nombre = "correo"

    def __init__(self, servidor, puerto=587, usuario=None, contrasena=None, remitente=None, seguridad=None,
                 destinatarios=None, url=None, timeout=20):
        self.servidor, self.puerto = servidor, int(puerto)
        self.usuario, self.contrasena = usuario or None, contrasena or None
        self.remitente = remitente or usuario
        self.seguridad = (seguridad or ("ssl" if self.puerto == 465 else "starttls")).lower()
        if self.seguridad not in ("starttls", "ssl", "ninguna"):
            raise ValueError("SMTP_SEGURIDAD debe ser starttls, ssl o ninguna")
        if not self.remitente:
            raise ValueError("Falta SMTP_REMITENTE (o SMTP_USUARIO)")
        self.destinatarios = destinatarios or (lambda nivel: [])
        self.url, self.timeout = url, timeout

    @classmethod
    def desde_entorno(cls, destinatarios=None, url=None):
        e = os.environ.get
        return cls(e("SMTP_SERVIDOR", "").strip(), e("SMTP_PUERTO", "587").strip() or 587,
                   e("SMTP_USUARIO", "").strip(), e("SMTP_CONTRASENA", ""), e("SMTP_REMITENTE", "").strip(),
                   e("SMTP_SEGURIDAD", "").strip() or None, destinatarios, url)

    def descripcion(self):
        return {"servidor": f"{self.servidor}:{self.puerto}", "seguridad": self.seguridad,
                "remitente": self.remitente}

    # ------------------------------------------------------------------ envío
    def _conectar(self):
        contexto = ssl.create_default_context()
        if self.seguridad == "ssl":
            s = smtplib.SMTP_SSL(self.servidor, self.puerto, timeout=self.timeout, context=contexto)
        else:
            s = smtplib.SMTP(self.servidor, self.puerto, timeout=self.timeout)
            if self.seguridad == "starttls":
                s.starttls(context=contexto)
        if self.usuario and self.contrasena:
            s.login(self.usuario, self.contrasena)
        return s

    def mensaje(self, aviso, para):
        m = EmailMessage()
        m["Subject"] = aviso.asunto
        m["From"] = formataddr((NOMBRE_REMITENTE, self.remitente))
        m["To"] = para
        m["Message-ID"] = make_msgid(domain=self.remitente.split("@")[-1])
        m.set_content(_texto_plano(aviso.texto))
        m.add_alternative(cuerpo_html(aviso.texto, aviso.nivel, self.url), subtype="html")
        return m

    def enviar(self, aviso):
        """Manda el aviso a cada destinatario de su nivel. En un reintento, solo a los que faltan.
        Devuelve la lista de correos a los que llegó."""
        if aviso.pendientes is None:
            if aviso.para:
                aviso.pendientes = list(aviso.para)
            elif aviso.nivel == "resumen":
                aviso.pendientes = list(dict.fromkeys(self.destinatarios("rojo") + self.destinatarios("amarillo")))
            else:
                aviso.pendientes = list(self.destinatarios(aviso.nivel))
            aviso.entregados = []
        if not aviso.pendientes and not aviso.entregados:
            raise SinDestinatarios("nadie tiene marcado este nivel en Usuarios")
        with self._conectar() as s:
            for para in list(aviso.pendientes):
                s.send_message(self.mensaje(aviso, para))
                aviso.pendientes.remove(para)
                aviso.entregados.append(para)
        return aviso.entregados


if __name__ == "__main__":
    from monitoreo.alertas import Aviso
    ap = argparse.ArgumentParser(description="Prueba del envío de alertas por correo")
    ap.add_argument("--prueba", metavar="CORREO", required=True, help="manda un correo de prueba a esta dirección")
    args = ap.parse_args()
    if not configurado():
        raise SystemExit("Falta SMTP_SERVIDOR (y SMTP_USUARIO, SMTP_CONTRASENA): ver .env.ejemplo.")
    canal = CanalCorreo.desde_entorno(url=os.environ.get("URL_DASHBOARD", "http://127.0.0.1:8001"))
    try:
        canal.enviar(Aviso.prueba([args.prueba]))
    except (smtplib.SMTPException, OSError) as e:
        raise SystemExit(f"No se pudo enviar: {explicar(e)}")
    print(f"Correo de prueba enviado a {args.prueba} desde {canal.remitente} ({canal.servidor}:{canal.puerto}).")
