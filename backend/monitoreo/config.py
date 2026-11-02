"""
Configuración del servicio. Cada valor se puede cambiar con una variable de entorno.

  URL_DATOS          API de datos de los sensores           (por defecto http://127.0.0.1:8000)
  CARPETA_MODELOS    modelos entrenados                     (por defecto: modelos/ del proyecto de modelos)
  MODO_PRONOSTICO    "combinado" (árboles + LSTM) o "arboles" (sin TensorFlow)
  CARPETA_REGISTROS  CSV de cada sesión                     (por defecto registros/ de este proyecto)
  FUENTE_PRONOSTICO  pronóstico de lluvia: "archivo" (pronósticos pasados, para los datos del
                     emisor) u "open-meteo" (pronóstico vigente, para datos en tiempo real)
"""

import os
from dataclasses import dataclass, field
from pathlib import Path

import calidad_agua

RAIZ = Path(__file__).resolve().parents[2]


@dataclass
class Config:
    url_datos: str = field(default_factory=lambda: os.environ.get("URL_DATOS", "http://127.0.0.1:8000"))
    carpeta_modelos: Path = field(default_factory=lambda: Path(os.environ.get(
        "CARPETA_MODELOS", Path(calidad_agua.__file__).resolve().parents[1] / "modelos")))
    modo_pronostico: str = field(default_factory=lambda: os.environ.get("MODO_PRONOSTICO", "combinado"))
    carpeta_registros: Path = field(default_factory=lambda: Path(os.environ.get(
        "CARPETA_REGISTROS", RAIZ / "registros")))
    # historia que se usa para armar las variables: la que más mira hacia atrás es la lluvia de
    # 72 h; se dejan 96 h de margen (la prueba de variables en vivo lo verifica)
    historia_h: int = 96
    # sin alarma en ningún sensor durante estas horas seguidas = la alarma de red se cierra
    # (equivale a unir alarmas separadas por menos de 2 h, como en la evaluación del notebook 07)
    horas_para_cerrar: int = 2
    # cada cuántos segundos se consulta la API de datos
    intervalo_consulta_s: float = 1.0
    # POST /predict/contaminacion: probabilidad desde la que un sensor pasa a nivel amarillo
    # (rojo = umbral del detector). Pendiente de calibrar con la ASADA.
    umbral_amarillo: float = field(default_factory=lambda: float(os.environ.get("UMBRAL_AMARILLO", "0.5")))

    def __post_init__(self):
        if self.modo_pronostico not in ("combinado", "arboles"):
            raise ValueError("MODO_PRONOSTICO debe ser 'combinado' o 'arboles'")
