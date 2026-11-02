"""
Motor en vivo conectado a la API de datos (sin dashboard todavía).

Consulta la API cada `intervalo_consulta_s` segundos, pasa las lecturas nuevas al motor,
procesa las horas cerradas e imprime las alarmas que se abren y se cierran.

Uso (desde backend/, con la API de datos y el emisor de Simulador_sensor corriendo):
  python -m monitoreo.ejecutar
  python -m monitoreo.ejecutar --modo arboles       # sin TensorFlow
"""

import argparse
import time


from monitoreo.cliente_datos import ClienteDatos
from monitoreo.config import Config
from monitoreo.motor import Motor


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=None, help="API de datos (por defecto URL_DATOS o http://127.0.0.1:8000)")
    ap.add_argument("--modo", choices=["combinado", "arboles"], default=None)
    args = ap.parse_args()
    cfg = Config()
    if args.url:
        cfg.url_datos = args.url
    if args.modo:
        cfg.modo_pronostico = args.modo

    cliente = ClienteDatos(cfg.url_datos)
    while not cliente.disponible():
        print(f"Esperando la API de datos en {cfg.url_datos} ...")
        time.sleep(3)
    print("Cargando modelos...")
    motor = Motor(cfg)
    print(f"Listo · modo {cfg.modo_pronostico} · umbral {motor.modelos.umbral} · "
          f"confirmación {motor.modelos.confirmar_h} h · registros en {motor.carpeta_sesion}")

    ultimo_dia = None
    try:
        while True:
            t0 = time.time()
            for lec in cliente.lecturas_desde(motor.ultima_lectura):
                motor.recibir(lec["fecha"], lec["valores"])
            horas = len(motor.horas_pendientes())
            for n in motor.procesar():
                if n["evento"] == "alarma_abierta":
                    print(f"  >>> ALARMA #{n['id']} abierta a las {n['hora']} · sensores: {', '.join(n['sensores'])}")
                else:
                    a = next(x for x in motor.alarmas if x["id"] == n["id"])
                    print(f"  <<< alarma #{n['id']} cerrada · {a['horas']} h · tipo sugerido: {a['tipo_sugerido']}")
            if motor.ultima_hora_procesada is not None and motor.ultima_hora_procesada.normalize() != ultimo_dia:
                ultimo_dia = motor.ultima_hora_procesada.normalize()
                e = motor.estado()
                print(f"{ultimo_dia.date()}  lecturas: {e['lecturas_recibidas']:6d}  "
                      f"última hora procesada: {e['ultima_hora_procesada'][11:16]}  "
                      f"({horas} h en el último ciclo, {time.time() - t0:.1f} s)  "
                      f"alarma activa: {'SI' if e['alarma_activa'] else 'no'}")
            time.sleep(max(0.0, cfg.intervalo_consulta_s - (time.time() - t0)))
    except KeyboardInterrupt:
        print(f"\nDetenido. {len(motor.lista_alarmas())} alarmas. Registros en {motor.carpeta_sesion}")


if __name__ == "__main__":
    main()
