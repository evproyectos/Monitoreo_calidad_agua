"""
Prepara los modelos para Docker en una máquina nueva (RNF-008). Corre antes que el servicio
(docker-compose.yml, servicio `preparar`) y solo usa la biblioteca estándar de Python.

Lee Modelo_calidad_agua/artefactos.json (lo escribe herramientas/publicar_modelos.py) y, por cada
archivo del release de GitHub que ahí se nombra:
  - si lo que trae ya está en la carpeta (por ejemplo, los modelos entrenados en esta máquina), no
    descarga nada ni lo cambia: avisa si los modelos son distintos de los del release;
  - si falta, lo descarga (con 4 intentos y espera creciente entre ellos), comprueba su huella
    SHA-256 y lo descomprime.
Así, correrlo dos veces da lo mismo que una (idempotente).

Variables de entorno (opcionales):
  MODELO_DIR       carpeta de Modelo_calidad_agua (en Docker, /modelo)
  ARTEFACTOS_URL   otra dirección de descarga en vez de la del release (un espejo, o para probar)
"""

import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

MODELO = Path(os.environ.get("MODELO_DIR", "/modelo"))
ESPERAS_S = [2, 4, 8]


def sha256(ruta):
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def descargar(url, destino):
    for intento in range(len(ESPERAS_S) + 1):
        try:
            with urllib.request.urlopen(url, timeout=60) as r, open(destino, "wb") as f:
                shutil.copyfileobj(r, f, 1 << 20)
            return
        except OSError as e:
            if intento == len(ESPERAS_S):
                raise RuntimeError(f"no se pudo descargar {url}: {e}") from e
            print(f"  falló la descarga ({e}); otro intento en {ESPERAS_S[intento]} s", flush=True)
            time.sleep(ESPERAS_S[intento])


def descomprimir(zip_, carpeta):
    """Saca solo lo que no está: nunca reemplaza un archivo que ya existe en la carpeta."""
    carpeta = carpeta.resolve()
    with zipfile.ZipFile(zip_) as z:
        nombres = z.namelist()
        for nombre in nombres:
            if not (carpeta / nombre).resolve().is_relative_to(carpeta):
                raise RuntimeError(f"{zip_.name} trae una ruta fuera de la carpeta: {nombre}")
        nuevos = [n for n in nombres if not n.endswith("/") and not (carpeta / n).exists()]
        z.extractall(carpeta, members=nuevos)


def preparar(archivo, base_url):
    carpeta = MODELO / archivo["destino"]
    contenido = archivo["contenido"]
    faltan = [n for n in contenido if not (carpeta / n).is_file()]
    if not faltan:
        distintos = [n for n, h in contenido.items() if h and sha256(carpeta / n) != h]
        if distintos:
            print(f"{archivo['nombre']}: ya está en la carpeta, distinto del release en {len(distintos)} archivo(s) "
                  f"(se usa lo de esta máquina)")
        else:
            print(f"{archivo['nombre']}: ya está en la carpeta")
        return
    print(f"{archivo['nombre']}: faltan {len(faltan)} archivo(s); descargando "
          f"{archivo['bytes'] / 1e6:.0f} MB ...", flush=True)
    carpeta.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=MODELO) as tmp:
        zip_ = Path(tmp) / archivo["nombre"]
        descargar(f"{base_url}/{archivo['nombre']}", zip_)
        if sha256(zip_) != archivo["sha256"]:
            raise RuntimeError(f"{archivo['nombre']}: la huella SHA-256 no coincide con artefactos.json")
        descomprimir(zip_, carpeta)
    print(f"{archivo['nombre']}: listo en {carpeta}")


def main():
    ruta = MODELO / "artefactos.json"
    if not ruta.exists():
        sys.exit(f"No está {ruta}: ¿Modelo_calidad_agua está clonado al lado de Monitoreo_calidad_agua?")
    m = json.loads(ruta.read_text(encoding="utf-8"))
    base_url = os.environ.get("ARTEFACTOS_URL") or m["url"]
    print(f"Modelos del release {m['release']} ({base_url})")
    error = False
    for archivo in m["archivos"]:
        try:
            preparar(archivo, base_url)
        except Exception as e:                       # noqa: BLE001 - se informa y se decide abajo
            if archivo.get("obligatorio", True):
                print(f"ERROR: {e}", flush=True)
                error = True
            else:
                print(f"Aviso: {e} (no hace falta para el servicio)", flush=True)
    sys.exit(1 if error else 0)


if __name__ == "__main__":
    main()
