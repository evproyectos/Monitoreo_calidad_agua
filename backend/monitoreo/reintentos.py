"""
Reintentos con espera exponencial (RNF-002) para las consultas a fuentes externas: el pronóstico
de lluvia de Open-Meteo y la API de datos de los sensores.

Por defecto 4 intentos (el primero y 3 reintentos), con esperas de 1, 2 y 4 s entre ellos (cada
espera es el doble de la anterior, hasta `maximo_s`). Si todos fallan se lanza el último error y
quien llama decide qué hacer (seguir con el último pronóstico, volver a probar en el siguiente
ciclo). Los errores que no se arreglan reintentando (un 404, datos inválidos) se lanzan de una vez.
"""

import time

INTENTOS = 4
ESPERA_S = 1.0
FACTOR = 2.0
MAXIMO_S = 30.0


def esperas(intentos=INTENTOS, espera_s=ESPERA_S, factor=FACTOR, maximo_s=MAXIMO_S):
    """Las esperas entre intentos: 1, 2, 4… s (una menos que los intentos)."""
    return [min(maximo_s, espera_s * factor ** k) for k in range(intentos - 1)]


def reintentar(funcion, *, intentos=INTENTOS, espera_s=ESPERA_S, factor=FACTOR, maximo_s=MAXIMO_S,
               reintentable=lambda e: True, nombre="la consulta", dormir=time.sleep, avisar=print):
    """Llama a `funcion()` hasta que funcione o se acaben los intentos."""
    pausas = esperas(intentos, espera_s, factor, maximo_s)
    for k in range(intentos):
        try:
            return funcion()
        except Exception as e:
            if k == intentos - 1 or not reintentable(e):
                raise
            avisar(f"Falló {nombre} ({type(e).__name__}: {str(e)[:120]}); "
                   f"reintento {k + 1} de {intentos - 1} en {pausas[k]:g} s")
            dormir(pausas[k])
