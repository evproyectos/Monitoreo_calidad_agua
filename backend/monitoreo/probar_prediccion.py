"""
Prueba de POST /predict/contaminacion contra el servicio en marcha (RF-003.1).

  1. Latencia: manda solicitudes con lecturas reales del periodo de prueba (98 h de toda la red,
     horas al azar) y reporta los percentiles 50 y 95 (criterio: p95 ≤ 500 ms).
  2. Datos faltantes: manda solicitudes incompletas y revisa que la respuesta sea 422 con detalle,
     y que sin clave de API o con una equivocada la respuesta sea 401.
  3. Con --comparar, revisa que los números coincidan con el cálculo por lotes de los notebooks.

Usa la primera clave de CLAVES_API (del .env) y, si el servicio está en HTTPS (CERTIFICADO_TLS),
se conecta por HTTPS confiando en ese certificado.

Uso (desde backend/, con el servicio corriendo en el puerto 8001):
  python -m monitoreo.probar_prediccion                  # 100 solicitudes
  python -m monitoreo.probar_prediccion -n 300 --comparar
"""

import argparse
import math
import time

import numpy as np
import pandas as pd
import requests

from calidad_agua import carga
from calidad_agua.red_neuronal import SALIDAS

from monitoreo import prediccion, seguridad
from monitoreo.config import Config

HORAS_ENVIO = 98


def solicitud(crudo, columnas, hora):
    """Lecturas de las últimas 98 h hasta la primera lectura de la hora siguiente (cierra `hora`)."""
    t = crudo.loc[hora - pd.Timedelta(hours=HORAS_ENVIO) + pd.Timedelta(minutes=15): hora + pd.Timedelta(hours=1),
                  columnas]
    lecturas = [{"fecha": f.isoformat(),
                 "valores": {c: (None if v != v else float(v)) for c, v in zip(columnas, fila)}}
                for f, fila in zip(t.index, t.to_numpy())]
    return {"lecturas": lecturas}


def percentil(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, math.ceil(q / 100 * len(xs)) - 1)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=None, help="por defecto http(s)://127.0.0.1:8001 según el .env")
    ap.add_argument("--clave", default=None, help="clave de API (por defecto la primera de CLAVES_API)")
    ap.add_argument("-n", type=int, default=100, help="solicitudes para medir la latencia")
    ap.add_argument("--comparar", action="store_true", help="comparar con el cálculo por lotes (más lento)")
    args = ap.parse_args()
    cfg = Config()
    base_url = args.url or f"{cfg.esquema}://127.0.0.1:8001"
    url = f"{base_url}/predict/contaminacion"
    clave = args.clave or next(iter(seguridad.claves_configuradas()), None)
    if not clave:
        raise SystemExit("Falta la clave de API: defina CLAVES_API en el .env o pase --clave.")
    s = requests.Session()
    s.headers[seguridad.ENCABEZADO] = clave
    # certificado propio (autofirmado): se pasa en cada llamada, porque REQUESTS_CA_BUNDLE del sistema
    # tendría prioridad sobre el de la sesión
    verificar = str(cfg.certificado_tls) if cfg.certificado_tls else True

    salud = s.get(f"{base_url}/health", timeout=10, verify=verificar).json()
    print(f"Servicio {salud['version']} · {salud['estado']}")

    crudo = carga.cargar_todo()
    inicio, fin = carga.periodos()["prueba"]
    sensores = [n for n in carga.sensores(crudo)]
    columnas = prediccion.columnas_esperadas(sensores)
    rng = np.random.default_rng(0)
    candidatas = pd.date_range(inicio + pd.Timedelta(hours=HORAS_ENVIO), pd.Timestamp(fin) - pd.Timedelta(hours=2),
                               freq="1h")
    horas = sorted(rng.choice(candidatas, size=min(args.n, len(candidatas)), replace=False))
    horas = [pd.Timestamp(h) for h in horas]

    # ------------------------------------------------------------- 1. latencia
    print(f"\n1. Latencia con {len(horas)} solicitudes (98 h de lecturas de {len(sensores)} sensores cada una)")
    cuerpos = [solicitud(crudo, columnas, h) for h in horas]
    s.post(url, json=cuerpos[0], timeout=30, verify=verificar)                  # la primera calienta TensorFlow
    total, servidor, respuestas = [], [], []
    for h, cuerpo in zip(horas, cuerpos):
        t0 = time.perf_counter()
        r = s.post(url, json=cuerpo, timeout=30, verify=verificar)
        total.append((time.perf_counter() - t0) * 1000)
        if r.status_code != 200:
            raise SystemExit(f"   la hora {h} respondió {r.status_code}: {r.text[:300]}")
        d = r.json()
        assert d["hora_evaluada"] == str(h), (d["hora_evaluada"], h)
        servidor.append(d["duracion_ms"])
        respuestas.append(d)
    p95 = percentil(total, 95)
    print(f"   de punta a punta (incluye enviar ~{len(str(cuerpos[0])) // 1024} KB): "
          f"p50 {percentil(total, 50):.0f} ms · p95 {p95:.0f} ms · máx {max(total):.0f} ms")
    print(f"   solo el cálculo en el servidor:          "
          f"p50 {percentil(servidor, 50):.0f} ms · p95 {percentil(servidor, 95):.0f} ms")
    ok_latencia = p95 <= 500
    print(f"   {'CUMPLE' if ok_latencia else 'NO CUMPLE'} p95 ≤ 500 ms")
    niveles = pd.Series([d["nivel_red"] for d in respuestas]).value_counts().to_dict()
    print(f"   nivel de la red en las horas probadas: {niveles}")

    # ------------------------------------------------------------- 2. datos faltantes
    print("\n2. Solicitudes incompletas o sin clave (deben responder 422 o 401)")
    base = cuerpos[0]
    sin_columna = {"lecturas": [{"fecha": lec["fecha"],
                                 "valores": {k: v for k, v in lec["valores"].items() if k != "CL2_J144"}}
                                for lec in base["lecturas"]]}
    sin_cloro = {"lecturas": [{"fecha": lec["fecha"], "valores": {**lec["valores"], "CL2_J144": None}}
                              for lec in base["lecturas"]]}
    casos = {
        "falta la columna CL2_J144": sin_columna,
        "CL2_J144 llega siempre en null": sin_cloro,
        "solo 24 h de lecturas": {"lecturas": base["lecturas"][-97:]},
        "lecturas desordenadas": {"lecturas": base["lecturas"][::-1]},
        "una lectura sin fecha": {"lecturas": [{"valores": base["lecturas"][0]["valores"]}] + base["lecturas"][1:]},
        "un valor que no es número": {"lecturas": [{"fecha": base["lecturas"][0]["fecha"],
                                                    "valores": {**base["lecturas"][0]["valores"], "PH_J27": "siete"}}]
                                      + base["lecturas"][1:]},
        "cuerpo vacío": {},
        "sensor desconocido": {**base, "sensores": ["J999"]},
    }
    ok_422 = True
    for nombre, encabezado in [("sin clave de API", None), ("clave de API equivocada", "no-es-la-clave")]:
        r = requests.post(url, json=base, timeout=30, verify=verificar,
                          headers={seguridad.ENCABEZADO: encabezado} if encabezado else {})
        bien = r.status_code == 401
        ok_422 &= bien
        print(f"   {'ok ' if bien else 'MAL'} {nombre}: {r.status_code} · {r.json()['detail']['error']}")
    for nombre, cuerpo in casos.items():
        r = s.post(url, json=cuerpo, timeout=30, verify=verificar)
        det = r.json().get("detail", {})
        bien = r.status_code == 422 and isinstance(det, dict) and det.get("error")
        ok_422 &= bool(bien)
        primero = (det.get("detalles") or [""])[0] if isinstance(det, dict) else ""
        error = det.get("error") if isinstance(det, dict) else det
        print(f"   {'ok ' if bien else 'MAL'} {nombre}: {r.status_code} · {error}"
              + (f" ({primero})" if primero else ""))

    # ------------------------------------------------------------- 3. comparación
    ok_igual = True
    if args.comparar:
        print("\n3. Comparación con el cálculo por lotes de los notebooks")
        from monitoreo.modelos import Modelos
        from monitoreo.verificar import referencia_por_lotes
        pron_b, det_b = referencia_por_lotes(Modelos(cfg.carpeta_modelos, cfg.modo_pronostico), crudo,
                                             pd.DatetimeIndex(horas))
        api = pd.DataFrame([{"fecha": pd.Timestamp(d["hora_evaluada"]), "nodo": x["sensor"],
                             "p_evento": x["probabilidad_evento"], **{p: x["pronostico_24h"][p] for p in SALIDAS}}
                            for d in respuestas for x in d["sensores"]])
        m = api.merge(pron_b[["fecha", "nodo"] + SALIDAS], on=["fecha", "nodo"], suffixes=("", "_b")) \
               .merge(det_b[["fecha", "nodo", "p_evento"]], on=["fecha", "nodo"], suffixes=("", "_b"))
        for p in SALIDAS:
            dif = np.nanmax(np.abs(m[p] - m[f"{p}_b"]))
            print(f"   pronóstico {p}: diferencia máxima {dif:.2e}")
            ok_igual &= dif < 5e-3
        dif = np.abs(m["p_evento"] - m["p_evento_b"])
        print(f"   probabilidad de evento: diferencia máxima {np.nanmax(dif):.2e} · "
              f"filas con diferencia > 0,001: {(dif > 1e-3).sum()} de {len(m)}")
        ok_igual &= (dif > 1e-3).mean() <= 0.001

    print("\n" + ("PRUEBA SUPERADA" if ok_latencia and ok_422 and ok_igual else "HAY PROBLEMAS (ver arriba)"))


if __name__ == "__main__":
    main()
