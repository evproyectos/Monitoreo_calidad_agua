"""
Seguridad del servicio (RNF-004).

Clave de API
  POST /predict/contaminacion exige el encabezado X-API-Key con una de las claves de la variable
  CLAVES_API (separadas por coma, para poder cambiarlas sin cortar a nadie). Sin clave o con una
  equivocada responde 401 y deja constancia del intento en registros/accesos_rechazados.log (la
  clave que se mandó nunca se escribe). Si no hay ninguna clave configurada responde 503: el
  endpoint no queda abierto por olvido.
  El dashboard (/, /api/...) y /health no piden clave: son de solo lectura y los usa el
  navegador, que no puede guardar una clave en secreto. En un despliegue se protegen con HTTPS y
  el acceso al servidor (tarea de Docker).

HTTPS
  Con CERTIFICADO_TLS y CLAVE_TLS (rutas a archivos PEM) el servicio atiende solo por HTTPS, con
  TLS 1.2 como versión mínima. Sin ellas atiende por HTTP, para trabajar en la propia máquina.

Secretos
  Van en el archivo .env de la raíz del proyecto, que no se versiona (ver .env.ejemplo). Las
  variables definidas en el sistema tienen prioridad sobre las del .env.

Herramientas (desde backend/):
  python -m monitoreo.seguridad --nueva-clave     genera una clave de API
  python -m monitoreo.seguridad --certificado     genera un certificado para 127.0.0.1 y localhost
"""

import argparse
import hmac
import ipaddress
import os
import secrets
import ssl
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import HTTPException, Request, Security
from fastapi.security import APIKeyHeader

ENCABEZADO = "X-API-Key"
TLS_MINIMO = ssl.TLSVersion.TLSv1_2
esquema_clave = APIKeyHeader(name=ENCABEZADO, auto_error=False,
                             description="Clave de API (una de las de la variable CLAVES_API del servidor)")


def claves_configuradas():
    return [c.strip() for c in os.environ.get("CLAVES_API", "").split(",") if c.strip()]


class RegistroAccesos:
    """Intentos rechazados: fecha, origen, ruta y motivo (nunca la clave que se mandó)."""

    def __init__(self, carpeta):
        self.ruta = Path(carpeta) / "accesos_rechazados.log"
        self._candado = threading.Lock()

    def anotar(self, request, motivo):
        origen = request.client.host if request.client else "?"
        linea = (f"{datetime.now():%d/%m/%Y %H:%M:%S} · {origen} · {request.method} {request.url.path} "
                 f"· {motivo}")
        print(f"[seguridad] acceso rechazado: {linea}", flush=True)
        with self._candado:
            self.ruta.parent.mkdir(parents=True, exist_ok=True)
            with open(self.ruta, "a", encoding="utf-8") as f:
                f.write(linea + "\n")


def exigir_clave(registro):
    """Dependencia de FastAPI que deja pasar solo solicitudes con una clave válida."""

    def verificar(request: Request, clave: Optional[str] = Security(esquema_clave)):
        validas = claves_configuradas()
        if not validas:
            raise HTTPException(503, {"error": "El servicio no tiene claves de API configuradas.",
                                      "detalles": ["el administrador debe definir CLAVES_API en el .env"]})
        if clave and any(hmac.compare_digest(clave.encode(), v.encode()) for v in validas):
            return
        registro.anotar(request, "sin clave" if not clave else "clave inválida")
        raise HTTPException(401, {"error": "Clave de API ausente o inválida.",
                                  "detalles": [f"envíe la clave en el encabezado {ENCABEZADO}"]},
                            headers={"WWW-Authenticate": "ApiKey"})

    return verificar


# ---------------------------------------------------------------------------- HTTPS
def servidor(app, host, puerto, certificado=None, clave=None, **opciones):
    """Servidor uvicorn; con certificado y clave, solo HTTPS y con TLS 1.2 como mínimo."""
    import uvicorn
    if bool(certificado) != bool(clave):
        raise SystemExit("Para HTTPS hacen falta las dos variables: CERTIFICADO_TLS y CLAVE_TLS.")
    tls = {}
    if certificado:
        for nombre, ruta in [("CERTIFICADO_TLS", certificado), ("CLAVE_TLS", clave)]:
            if not Path(ruta).exists():
                raise SystemExit(f"No se encontró {ruta} ({nombre}). Para pruebas se puede generar con:\n"
                                 "  python -m monitoreo.seguridad --certificado")
        tls = {"ssl_certfile": str(certificado), "ssl_keyfile": str(clave)}
    config = uvicorn.Config(app, host=host, port=puerto, **tls, **opciones)
    config.load()
    if config.ssl is not None:
        config.ssl.minimum_version = TLS_MINIMO
    return uvicorn.Server(config)


def generar_certificado(carpeta, dias=825):
    """Certificado autofirmado para 127.0.0.1 y localhost (pruebas y uso en la propia máquina)."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    carpeta = Path(carpeta)
    carpeta.mkdir(parents=True, exist_ok=True)
    llave = ec.generate_private_key(ec.SECP256R1())
    nombre = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Monitoreo de calidad de agua (local)")])
    ahora = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder()
            .subject_name(nombre).issuer_name(nombre).public_key(llave.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(ahora - timedelta(minutes=5)).not_valid_after(ahora + timedelta(days=dias))
            .add_extension(x509.SubjectAlternativeName([
                x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
                x509.IPAddress(ipaddress.ip_address("::1"))]), critical=False)
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .sign(llave, hashes.SHA256()))
    rutas = {"certificado": carpeta / "certificado.pem", "clave": carpeta / "clave.pem",
             "windows": carpeta / "certificado.cer"}
    rutas["certificado"].write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    rutas["windows"].write_bytes(cert.public_bytes(serialization.Encoding.DER))
    rutas["clave"].write_bytes(llave.private_bytes(serialization.Encoding.PEM,
                                                   serialization.PrivateFormat.PKCS8,
                                                   serialization.NoEncryption()))
    return rutas


if __name__ == "__main__":
    from monitoreo.config import RAIZ
    ap = argparse.ArgumentParser(description="Herramientas de seguridad del servicio")
    ap.add_argument("--nueva-clave", action="store_true", help="generar una clave de API")
    ap.add_argument("--certificado", action="store_true", help="generar un certificado para 127.0.0.1")
    args = ap.parse_args()
    if args.nueva_clave:
        print("Clave nueva (agrégala a CLAVES_API en el .env y dásela solo a quien la necesite):")
        print(secrets.token_urlsafe(32))
    elif args.certificado:
        r = generar_certificado(RAIZ / "secretos")
        print(f"Certificado: {r['certificado']}\nClave:       {r['clave']}\n")
        print("Agrega al .env:\n  CERTIFICADO_TLS=secretos/certificado.pem\n  CLAVE_TLS=secretos/clave.pem")
        print("  URL_DASHBOARD=https://127.0.0.1:8001\n")
        print("Para que el navegador confíe en él (opcional, en PowerShell):")
        print(f'  Import-Certificate -FilePath "{r["windows"]}" -CertStoreLocation Cert:\\CurrentUser\\Root')
    else:
        ap.print_help()
