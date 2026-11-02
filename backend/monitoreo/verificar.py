"""
Verificación del motor en vivo, sin API.

Reproduce el periodo de prueba lectura por lectura a través del Motor, como si
llegara en vivo (solo las columnas de los sensores, sin etiquetas), y compara con el cálculo por
lotes de los notebooks sobre la tabla completa:

  1. pronósticos: mismos valores en cada sensor y hora;
  2. detector: misma probabilidad de evento y mismas alarmas por sensor;
  3. métricas: acierto del pronóstico (notebook 08) y eventos detectados / falsas alarmas
     (notebook 07).

Uso (desde backend/):
  python -m monitoreo.verificar                 # periodo de prueba completo (~5 min)
  python -m monitoreo.verificar --dias 10       # solo los primeros días
  python -m monitoreo.verificar --lote-h 1      # procesar hora por hora (más lento)
"""

import argparse
import time

import numpy as np
import pandas as pd

from calidad_agua import carga, calidad, metas, variables, detector
from calidad_agua.red_neuronal import SALIDAS

from monitoreo.config import Config
from monitoreo.modelos import Modelos
from monitoreo.motor import Motor


def referencia_por_lotes(modelos, crudo, horas):
    """Lo que calculan los notebooks: tabla completa (todo el periodo), mismos modelos."""
    t15 = calidad.lecturas_operativas(crudo)
    pron = modelos.pronosticar(variables.horario(t15), horas)
    det = modelos.detectar(detector.horario(t15), horas)
    return pron, det


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dias", type=int, default=None, help="días de prueba a reproducir (por defecto todos)")
    ap.add_argument("--precarga-dias", type=int, default=5)
    ap.add_argument("--lote-h", type=int, default=24, help="cada cuántas horas simuladas se llama a procesar()")
    args = ap.parse_args()

    cfg = Config()
    print(f"Modelos: {cfg.carpeta_modelos} · modo {cfg.modo_pronostico}")
    modelos = Modelos(cfg.carpeta_modelos, cfg.modo_pronostico)
    crudo = carga.cargar_todo()
    INICIO_PRUEBA = carga.periodos()["prueba"][0]          # viene en metadatos.json con los datos
    sensores_cols = [c for c in crudo.columns if not c.startswith(("evento_", "falla_")) and c != "particion"]
    fin = (crudo.index[-1] if args.dias is None
           else INICIO_PRUEBA + pd.Timedelta(days=args.dias) - pd.Timedelta(minutes=15))
    envio = crudo.loc[INICIO_PRUEBA - pd.Timedelta(days=args.precarga_dias): fin, sensores_cols]

    # ---------------------------------------------------------------- en vivo
    motor = Motor(cfg, modelos, registrar=False)
    t0 = time.time()
    siguiente = envio.index[0] + pd.Timedelta(hours=args.lote_h)
    for fecha, fila in zip(envio.index, envio.to_dict("records")):
        motor.recibir(fecha, {k: (None if v != v else v) for k, v in fila.items()})
        if fecha >= siguiente:
            motor.procesar()
            siguiente = fecha + pd.Timedelta(hours=args.lote_h)
    motor.procesar()
    seg = time.time() - t0
    horas_vivo = motor.tabla_deteccion()["fecha"].nunique()
    print(f"En vivo: {len(envio):,} lecturas, {horas_vivo:,} horas procesadas en {seg:.0f} s "
          f"({1000 * seg / horas_vivo:.0f} ms por hora)")

    pron_v = motor.tabla_pronosticos()
    pron_v = pron_v[pron_v["fecha"] >= INICIO_PRUEBA]
    det_todo = motor.tabla_deteccion()
    det_v = det_todo[det_todo["fecha"] >= INICIO_PRUEBA]
    horas = pd.DatetimeIndex(sorted(det_v["fecha"].unique()))
    # horas en que el motor ya contaba alarmas (desde el fin del calentamiento, en la precarga)
    horas_con_alarma = pd.DatetimeIndex(sorted(det_todo["fecha"].unique()))
    listas = (horas_con_alarma - motor.primera_lectura) >= pd.Timedelta(hours=cfg.historia_h)
    horas_con_alarma = horas_con_alarma[listas]

    # ---------------------------------------------------------------- por lotes
    pron_b, det_b = referencia_por_lotes(modelos, crudo, horas_con_alarma)

    # 1. pronósticos
    m = pron_v.merge(pron_b[pron_b["fecha"] >= INICIO_PRUEBA], on=["fecha", "nodo"], suffixes=("_v", "_b"))
    print("\n1. Pronósticos (vivo contra lotes)")
    ok_pron = True
    # Igual que en el detector: si una variable cae justo en el corte de un árbol, el último decimal
    # de una suma móvil puede mandar esa fila por otra rama. El cambio es mínimo; se exige que quede
    # por debajo de la mitad de la resolución del sensor (0,01) y que los faltantes coincidan.
    for p in SALIDAS:
        dif = np.abs(m[f"{p}_v"] - m[f"{p}_b"])
        mismos_nan = (m[f"{p}_v"].isna() == m[f"{p}_b"].isna()).all()
        ok_pron &= np.nanmax(dif) < 5e-3 and mismos_nan
        print(f"   {p}: {len(m):,} pronósticos · diferencia máxima {np.nanmax(dif):.2e} "
              f"(filas con más de 0,001: {int((dif > 1e-3).sum())}) · faltantes iguales: {mismos_nan}")

    # 2. detector
    d = det_v.merge(det_b[det_b["fecha"] >= INICIO_PRUEBA], on=["fecha", "nodo"], suffixes=("_v", "_b"))
    dif = np.abs(d["p_evento_v"] - d["p_evento_b"])
    dif_p, n_dif = np.nanmax(dif), int((dif > 1e-3).sum())
    print("\n2. Detector")
    # Las variables del detector usan sumas y medias móviles: en vivo la ventana empieza en otro
    # lugar y el último decimal puede cambiar. Casi siempre eso no mueve la probabilidad, pero si una
    # variable cae justo en el corte de un árbol, esa fila cambia de rama. Lo que importa es que sean
    # muy pocas filas y que no cambie ninguna alarma.
    print(f"   probabilidad de evento: diferencia máxima {dif_p:.2e}; filas con diferencia mayor a 0,001: "
          f"{n_dif} de {len(d):,} (umbral de alarma: {modelos.umbral})")
    # alarmas por sensor según la regla del notebook 07 aplicada a la referencia por lotes
    alto_b = det_b.assign(alto=det_b["p_evento"] >= modelos.umbral).pivot(index="fecha", columns="nodo", values="alto")
    ancho_b = (alto_b.astype(int).rolling(modelos.confirmar_h, min_periods=1).sum() >= modelos.confirmar_h).loc[horas]
    A_v = motor.matriz_alarmas().loc[horas]
    distintas = int((A_v != ancho_b.reindex_like(A_v)).values.sum())
    print(f"   alarmas por sensor distintas: {distintas} de {A_v.size:,}")

    # 3. métricas contra los notebooks
    print("\n3. Métricas (deben coincidir con los notebooks 07 y 08)")
    h_real = variables.horario(calidad.lecturas_validas(crudo))
    ev = crudo[[f"evento_{n}" for n in modelos.sensores]].resample("1h").max()
    for p in SALIDAS:
        x = pron_v[pron_v["fecha_pronosticada"] <= h_real.index[-1]]
        obs = np.array([h_real.at[f, f"{p}_{n}"] for f, n in zip(x["fecha_pronosticada"], x["nodo"])])
        normal = np.array([ev.at[f, f"evento_{n}"] == 0 for f, n in zip(x["fecha_pronosticada"], x["nodo"])])
        validos = ~np.isnan(x[p].values) & ~np.isnan(x[f"base_{p}"].values)
        ok = metas.acierto(p, obs, x[p].values)
        print(f"   {p}: acierto en operación normal {100 * np.nanmean(ok[normal & validos]):.1f} %")
    h_det = detector.horario(calidad.lecturas_operativas(crudo))
    h_det["evento_red"] = crudo["evento_red"].resample("1h").max()
    det_ep, alarmas, r = detector.evaluar(h_det, A_v, str(horas[0]), str(horas[-1] + pd.Timedelta(hours=1)))
    print(f"   eventos visibles detectados: {r['detectados']} de {r['episodios visibles']} · "
          f"falsas alarmas: {r['falsas alarmas']} ({r['falsas por semana']:.2f} por semana)")
    print(f"   alarmas de red abiertas por el motor: {len(motor.lista_alarmas())}")

    print("\nRESULTADO:", "VERIFICACIÓN SUPERADA" if ok_pron and n_dif <= 0.001 * len(d) and distintas == 0
          else "HAY DIFERENCIAS: revisar")


if __name__ == "__main__":
    main()
