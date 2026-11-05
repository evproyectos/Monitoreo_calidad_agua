"""
Predicciones a pedido en procesos aparte (RNF-001: el 95 % de las respuestas en 500 ms o menos
con 10 usuarios a la vez).

Python ejecuta el código de un proceso de a un hilo a la vez (el GIL), y armar las variables con
pandas es casi todo el tiempo de una predicción (unos 100 ms). En un solo proceso, con 10 usuarios
las solicitudes hacen fila entre ellas y con el motor en vivo. Aquí cada proceso trabajador carga
su propia copia de los modelos y atiende solicitudes completas; el proceso principal recibe la
solicitud, se la pasa a un trabajador libre y devuelve la respuesta.

Los trabajadores usan los mismos modelos que el motor: cada solicitud lleva la firma de los
archivos de modelos que usa el motor en ese momento (nombre, fecha y tamaño), y si un trabajador
tiene otros los vuelve a cargar antes de responder. Así la recarga sin reiniciar (RF-004.2) también
vale para /predict, y la respuesta es la misma que daría el motor.

TRABAJADORES_PREDICCION fija cuántos procesos se usan (por defecto, los núcleos menos uno, hasta
3; cada uno ocupa unos 800 MB con TensorFlow). Con 0 se predice en el mismo proceso del servicio,
como antes (las pruebas lo usan así). Si un trabajador se cae, el servicio predice en su propio
proceso y lo informa en /health.
"""

import multiprocessing as mp
import os
from concurrent.futures import ProcessPoolExecutor

ESPERA_S = 120                       # una solicitud nunca debería tardar tanto: algo se trabó

_local = {}                          # lo que tiene cargado cada proceso trabajador


def cuantos_por_defecto():
    return max(1, min(3, (os.cpu_count() or 2) - 1))


def _iniciar(carpeta, modo, fabrica):
    """Al arrancar cada trabajador: un hilo de cálculo por proceso y los modelos cargados."""
    from threadpoolctl import threadpool_limits
    threadpool_limits(1)             # OpenMP y BLAS: varios procesos a la vez no deben pelear los núcleos
    try:
        import tensorflow as tf
        tf.config.threading.set_intra_op_parallelism_threads(1)
        tf.config.threading.set_inter_op_parallelism_threads(1)
    except (ImportError, RuntimeError):                  # sin TensorFlow (modo árboles)
        pass
    _local.update(carpeta=carpeta, modo=modo, fabrica=fabrica, modelos=None)
    _modelos(None)


def _modelos(firma):
    """Los modelos del trabajador; si el motor usa otros (`firma`), se cargan los de la carpeta una
    vez por cada firma nueva (si el motor rechazó los archivos nuevos, no se reintenta con cada solicitud)."""
    m = _local["modelos"]
    if m is None or (firma is not None and getattr(m, "firma", None) != firma and _local.get("intento") != firma):
        _local["intento"] = firma
        fabrica = _local["fabrica"]
        if fabrica is None:
            from monitoreo.modelos import Modelos as fabrica
        _local["modelos"] = m = fabrica(_local["carpeta"], _local["modo"])
    return m


def _listo():
    return os.getpid()


def _atender(tipo, solicitud, firma, historia_h, umbral_amarillo):
    from monitoreo import prediccion
    m = _modelos(firma)
    if tipo == "contaminacion":
        return prediccion.predecir(solicitud, m, historia_h, umbral_amarillo)
    return prediccion.predecir_fugas(solicitud, m, historia_h)


class Trabajadores:
    def __init__(self, carpeta, modo, cuantos, fabrica=None):
        """`fabrica(carpeta, modo)` carga los modelos (por defecto monitoreo.modelos.Modelos)."""
        self.cuantos = cuantos
        # "spawn": procesos nuevos, sin copiar los hilos de TensorFlow del servicio (igual en Windows)
        self.pool = ProcessPoolExecutor(cuantos, mp_context=mp.get_context("spawn"), initializer=_iniciar,
                                        initargs=(os.fspath(carpeta), modo, fabrica))
        # que arranquen y carguen los modelos ahora, no con la primera solicitud
        for f in [self.pool.submit(_listo) for _ in range(cuantos)]:
            f.result(timeout=ESPERA_S * 3)

    def atender(self, tipo, solicitud, firma, historia_h, umbral_amarillo=None):
        return self.pool.submit(_atender, tipo, solicitud, firma, historia_h, umbral_amarillo).result(ESPERA_S)

    def cerrar(self):
        self.pool.shutdown(wait=False, cancel_futures=True)
