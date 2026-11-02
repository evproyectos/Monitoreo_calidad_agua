"""Servicio de monitoreo en vivo: recibe lecturas, pronostica a 24 h y detecta eventos."""

import os
from pathlib import Path

__version__ = "1.1.0"

# secretos y configuración local: archivo .env en la raíz del proyecto (no se versiona; ver
# .env.ejemplo). Las variables ya definidas en el sistema tienen prioridad.
ARCHIVO_ENV = Path(__file__).resolve().parents[2] / ".env"


def cargar_env(ruta=ARCHIVO_ENV):
    """Carga el .env si existe. Devuelve True si lo encontró."""
    from dotenv import load_dotenv
    return load_dotenv(ruta, override=False) if Path(ruta).exists() else False


if os.environ.get("MONITOREO_SIN_ENV") != "1":        # las pruebas no leen el .env de la máquina
    cargar_env()
