"""
Motor de monitoreo en vivo.

  1. recibir(fecha, valores): guarda cada lectura de 15 min (todos los sensores) en memoria.
  2. procesar(): toma TODAS las horas ya cerradas que falten por procesar (una hora se cierra
     cuando llega una lectura de la hora siguiente) y, de una sola vez:
       - limpia las lecturas con las reglas de operación y el preprocesamiento: quita los picos
         (IQR), interpola los huecos de hasta 30 min y marca los más largos
         (calidad.lecturas_operativas, RF-001.3);
       - arma las variables con las mismas funciones del entrenamiento, sobre las últimas
         `historia_h` horas;
       - pronostica cloro, turbidez y pH a 24 h para cada sensor;
       - calcula la probabilidad de evento de cada sensor y actualiza las alarmas;
       - si hay modelo de anticipación (notebook 09), calcula la probabilidad de que empiece
         cada tipo de evento en las próximas 24 h y abre o cierra los avisos anticipados;
       - si hay modelo de fugas (notebook 10), calcula la probabilidad de fuga y el tramo más
         probable y abre o cierra las alarmas de fuga.
     Solo se usan los sensores del sistema (los del detector): si la fuente de datos manda más,
     los demás se ignoran.
     Procesar varias horas juntas cuesta casi lo mismo que una, así que el motor no se queda
     atrás aunque los datos lleguen acelerados.

Alarmas (igual que en la evaluación del notebook 07):
  - un sensor está en alarma si su probabilidad de evento supera el umbral durante
    `confirmar_h` horas seguidas;
  - la alarma de RED se abre cuando algún sensor entra en alarma y se cierra cuando pasan
    `horas_para_cerrar` horas seguidas sin ningún sensor en alarma.

Avisos anticipados (igual que en la evaluación del notebook 09): un tipo de evento entra en aviso
si su probabilidad supera su umbral durante sus horas de confirmación seguidas. El aviso de ese
tipo termina tras HORAS_FIN_AVISO horas seguidas sin aviso.

Fugas (igual que en la evaluación del notebook 10): hay alarma de fuga si la probabilidad supera
el umbral durante las horas de confirmación seguidas; se cierra tras `horas_para_cerrar` horas sin
alarma. El tramo de la alarma es el más votado en sus horas (pesado por su probabilidad).
"""

import csv
import os
import time
from collections import Counter

import numpy as np
import pandas as pd

from calidad_agua import anticipacion, calidad, carga, variables, detector
from calidad_agua import deriva as deriva_
from calidad_agua import fugas as fugas_
from calidad_agua.red_neuronal import SALIDAS

from monitoreo.config import Config
from monitoreo.modelos import Modelos


HORAS_FIN_AVISO = 6            # horas seguidas sin aviso para dar por terminado un aviso anticipado
HORA_DERIVA = 6                # cada día a esta hora se compara la última semana con el entrenamiento
DIAS_DERIVA = 7
DIAS_LLUVIA = 31               # historia de lluvia para la variable de 30 días de la anticipación


class Registro:
    """CSV que se escribe a medida que ocurren las cosas (y la misma tabla en la base de datos, si
    hay una: ver monitoreo/base_datos.py)."""

    def __init__(self, ruta, columnas, base=None):
        self.f = open(ruta, "w", newline="", encoding="utf-8")
        self.w = csv.DictWriter(self.f, fieldnames=columnas, extrasaction="ignore")
        self.w.writeheader()
        self.columnas, self.base = columnas, base
        self.tabla = os.path.splitext(os.path.basename(ruta))[0]

    def escribir(self, filas):
        self.w.writerows(filas)
        self.f.flush()
        if self.base is not None:
            self.base.escribir(self.tabla, [{c: f.get(c) for c in self.columnas} for f in filas])


class Motor:
    def __init__(self, config=None, modelos=None, registrar=True):
        self.cfg = config or Config()
        self.modelos = modelos or Modelos(self.cfg.carpeta_modelos, self.cfg.modo_pronostico)
        self.sensores = self.modelos.sensores
        self._nuevas = []                         # lecturas recibidas aún no pasadas al búfer
        self.bufer = pd.DataFrame()
        self.columnas = None
        self.ultima_lectura = None
        self.primera_lectura = None
        self.ultima_hora_procesada = None
        self.lecturas_recibidas = 0
        self.imputacion = {}                  # flag_imputacion de las lecturas del último ciclo
        self.inicio_reloj = time.time()

        # estado de las alarmas
        self.horas_alto = {n: 0 for n in self.sensores}
        self.alarma_abierta = None
        self.horas_sin_alarma = 0
        self.alarmas = []
        self._siguiente_id = 1

        # estado de los avisos anticipados: por tipo, horas seguidas sobre el umbral y, si hay un
        # aviso abierto, sus datos y las horas que lleva sin aviso
        self.horas_alto_tipo = {}
        self.horas_alto_48h = {}
        self.avisos_abiertos = {}
        self.avisos = []
        self.ultima_anticipacion = {}
        self.lluvia_horaria = pd.Series(dtype="float64")
        self.anticipaciones = []                  # probabilidades por hora y tipo (DataFrames por lote)

        # estado de las fugas
        self.horas_alto_fuga = 0
        self.fuga_abierta = None
        self.fugas = []
        self.ultima_fuga = {}
        self.probabilidades_fuga = []             # DataFrames por lote (solo horas listas)
        # caudal, presión, temperatura y lluvia horarios de los últimos días: la línea base de las
        # fugas compara con la misma hora de la semana anterior (el búfer guarda menos historia)
        self.historia_fugas = pd.DataFrame()
        # deriva de los datos: lecturas horarias de la última semana y la última revisión
        self.historia_deriva = pd.DataFrame()
        self.ultima_deriva = None

        # resultados acumulados (para la API y la verificación)
        self.pronosticos = []                     # DataFrames por lote
        self.deteccion = []
        self.ultimo_estado_sensores = {}

        self.carpeta_sesion = None
        if registrar:
            self.carpeta_sesion = os.path.join(self.cfg.carpeta_registros,
                                               "sesion_" + time.strftime("%Y%m%d_%H%M%S"))
            os.makedirs(self.carpeta_sesion, exist_ok=True)
            base = None
            if self.cfg.base_de_datos:
                from monitoreo.base_datos import BaseDatos
                base = BaseDatos(self.cfg.base_de_datos, os.path.basename(self.carpeta_sesion))
            self.base = base
            self.reg_pron = Registro(os.path.join(self.carpeta_sesion, "pronosticos.csv"),
                                     ["fecha", "nodo", "fecha_pronosticada"] + SALIDAS + [f"base_{p}" for p in SALIDAS],
                                     base)
            self.reg_det = Registro(os.path.join(self.carpeta_sesion, "deteccion.csv"),
                                    ["fecha", "nodo", "p_evento", "tipo", "en_alarma"], base)
            self.reg_alarmas = Registro(os.path.join(self.carpeta_sesion, "alarmas.csv"),
                                        ["id", "inicio", "fin", "horas", "sensores", "tipo_sugerido"], base)
            if getattr(self.modelos, "fugas", None) is not None:
                self.reg_fugas = Registro(os.path.join(self.carpeta_sesion, "fugas.csv"),
                                          ["fecha", "p_fuga", "tramo", "p_tramo", "caudal_residuo", "en_alarma"], base)
            if getattr(self.modelos, "anticipacion", None) is not None:
                self.reg_ant = Registro(os.path.join(self.carpeta_sesion, "anticipacion.csv"),
                                        ["fecha", "tipo", "probabilidad", "umbral", "en_aviso"], base)

    # ------------------------------------------------------------------ entrada
    def recibir(self, fecha, valores):
        fecha = pd.Timestamp(fecha)
        if self.ultima_lectura is not None and fecha <= self.ultima_lectura:
            return                                # repetida o fuera de orden: se ignora
        fila = {k: (np.nan if v is None else float(v)) for k, v in valores.items()}
        fila["fecha"] = fecha
        self._nuevas.append(fila)
        if self.primera_lectura is None:
            self.primera_lectura = fecha
        self.ultima_lectura = fecha
        self.lecturas_recibidas += 1

    def _pasar_al_bufer(self):
        if not self._nuevas:
            return
        nuevas = pd.DataFrame(self._nuevas).set_index("fecha")
        self._nuevas = []
        self.bufer = nuevas if self.bufer.empty else pd.concat([self.bufer, nuevas])
        if self.columnas is None:
            self.columnas = list(self.bufer.columns)

    def horas_pendientes(self):
        """Horas completas que todavía no se procesaron (la hora en curso no cuenta)."""
        if self.ultima_lectura is None:
            return pd.DatetimeIndex([])
        ultima_cerrada = self.ultima_lectura.floor("h") - pd.Timedelta(hours=1)
        if self.ultima_hora_procesada is not None:
            primera = self.ultima_hora_procesada + pd.Timedelta(hours=1)
        else:
            primera = self.primera_lectura.ceil("h")
        if primera > ultima_cerrada:
            return pd.DatetimeIndex([])
        return pd.date_range(primera, ultima_cerrada, freq="1h")

    # ------------------------------------------------------------------ proceso
    def procesar(self):
        """Procesa todas las horas cerradas pendientes. Devuelve la lista de novedades."""
        self._pasar_al_bufer()
        horas = self.horas_pendientes()
        if len(horas) == 0:
            return []
        desde = horas[0] - pd.Timedelta(hours=self.cfg.historia_h) + pd.Timedelta(minutes=15)
        hasta = horas[-1] + pd.Timedelta(minutes=45)
        # el preprocesamiento (picos e interpolación) mira las lecturas vecinas: se le pasan las que
        # ya llegaron después de la hora (hasta 30 min) y después se recorta
        extra = hasta + pd.Timedelta(minutes=30)
        ventana = carga.filtrar_sensores(self.bufer.loc[desde:extra], self.sensores)
        w15 = calidad.lecturas_operativas(ventana).loc[:hasta]
        self.imputacion = w15["flag_imputacion"].loc[horas[0]:].value_counts().to_dict() \
            if "flag_imputacion" in w15 else {}

        pron = self.modelos.pronosticar(variables.horario(w15), horas)
        hd = detector.horario(w15)
        det = self.modelos.detectar(hd, horas)
        # al arrancar, hasta tener `historia_h` horas de datos las variables están incompletas:
        # se calcula todo pero no se encienden alarmas (y los pronósticos se marcan)
        listas = horas[(horas - self.primera_lectura) >= pd.Timedelta(hours=self.cfg.historia_h)]
        pron["calentando"] = ~pron["fecha"].isin(listas)

        novedades = []
        det["en_alarma"] = False
        for hora in horas:
            filas = det["fecha"] == hora
            sub = det[filas].set_index("nodo")
            en_alarma = []
            if hora not in listas:
                continue
            for n in self.sensores:
                p = sub["p_evento"].get(n, np.nan)
                self.horas_alto[n] = self.horas_alto[n] + 1 if (p == p and p >= self.modelos.umbral) else 0
                if self.horas_alto[n] >= self.modelos.confirmar_h:
                    en_alarma.append(n)
            det.loc[filas & det["nodo"].isin(en_alarma), "en_alarma"] = True
            tipos = sub.loc[en_alarma, "tipo"].tolist() if en_alarma else []
            novedades += self._actualizar_alarma(hora, en_alarma, tipos)
            self.ultimo_estado_sensores = {
                n: {"p_evento": float(sub["p_evento"].get(n, np.nan)),
                    "tipo": carga.TIPOS_EVENTO.get(int(sub["tipo"].get(n, 0)), "?"),
                    "en_alarma": n in en_alarma} for n in self.sensores}

        if getattr(self.modelos, "anticipacion", None) is not None:
            novedades += self._anticipar(w15, horas, listas)
        if getattr(self.modelos, "fugas", None) is not None:
            novedades += self._revisar_fugas(hd, horas, listas)
        if getattr(self.modelos, "deriva", None) is not None:
            novedades += self._revisar_deriva(w15, horas)

        self.pronosticos.append(pron)
        self.deteccion.append(det)
        self._actualizar_reciente(pron, det)
        if self.carpeta_sesion:
            self.reg_pron.escribir(pron.to_dict("records"))
            self.reg_det.escribir(det.assign(tipo=det["tipo"].map(carga.TIPOS_EVENTO)).to_dict("records"))
        self.ultima_hora_procesada = horas[-1]

        # el búfer solo necesita la historia de las variables
        limite = self.ultima_hora_procesada - pd.Timedelta(hours=self.cfg.historia_h + 2)
        self.bufer = self.bufer.loc[self.bufer.index > limite]
        return novedades

    # ------------------------------------------------------------------ deriva de los datos
    def _revisar_deriva(self, w15, horas):
        ref = self.modelos.deriva["referencia"]
        h = w15[[c for c in ref if c in w15]].resample("1h").mean().reindex(horas)
        viejas = self.historia_deriva[~self.historia_deriva.index.isin(h.index)] if len(self.historia_deriva) else None
        self.historia_deriva = pd.concat([viejas, h]).sort_index() if viejas is not None else h
        corte = horas[-1] - pd.Timedelta(days=DIAS_DERIVA)
        self.historia_deriva = self.historia_deriva[self.historia_deriva.index > corte]
        if not any(x.hour == HORA_DERIVA for x in horas) and self.ultima_deriva is not None:
            return []
        r = deriva_.revisar(ref, self.historia_deriva)
        self.ultima_deriva = {"hora": str(horas[-1]), "desde": str(self.historia_deriva.index.min()),
                              "periodo_referencia": self.modelos.deriva.get("periodo"),
                              "columnas": [{"columna": f.columna, "psi": _num(f.psi, 3), "estado": f.estado,
                                            "horas": int(f.horas)} for f in r.itertuples()]}
        con_deriva = r[r["estado"] == "deriva"]
        if len(con_deriva) and any(x.hour == HORA_DERIVA for x in horas):
            return [{"evento": "deriva", "hora": str(horas[-1]),
                     "columnas": [(f.columna, float(f.psi)) for f in con_deriva.itertuples()]}]
        return []

    # ------------------------------------------------------------------ fugas
    def _revisar_fugas(self, hd, horas, listas):
        f = self.modelos.fugas
        cols = [c for c in hd.columns if c.startswith(("Q_", "P_")) or c in (f"TEMP_{fugas_.FUENTE}", "lluvia_mm_h")]
        # se guardan las horas nuevas; las que ya estaban no se reemplazan: se calcularon cuando eran
        # las últimas de su ventana, con toda su historia (al principio de una ventana la limpieza de
        # lecturas no ve las anteriores y puede dar otro promedio)
        if len(self.historia_fugas):
            nuevas = hd.loc[~hd.index.isin(self.historia_fugas.index), cols]
            self.historia_fugas = pd.concat([self.historia_fugas, nuevas]).sort_index()
        else:
            self.historia_fugas = hd[cols]
        corte = horas[-1] - pd.Timedelta(hours=fugas_.HISTORIA_H + 24)
        self.historia_fugas = self.historia_fugas[self.historia_fugas.index > corte]
        F = self.modelos.detectar_fugas(self.historia_fugas, horas)
        F["en_alarma"] = False
        novedades = []
        for hora in horas:
            if hora not in listas:
                continue
            fila = F.loc[hora]
            p = float(fila["p_fuga"])
            self.horas_alto_fuga = self.horas_alto_fuga + 1 if (p == p and p >= f["umbral"]) else 0
            en_alarma = self.horas_alto_fuga >= f["confirmar_h"]
            F.loc[hora, "en_alarma"] = en_alarma
            novedades += self._actualizar_fuga(hora, en_alarma, fila)
            self.ultima_fuga = {"hora": hora, "probabilidad": p, "umbral": f["umbral"], "en_alarma": en_alarma,
                                "tramo": fila["tramo"], "p_tramo": float(fila["p_tramo"]),
                                "caudal_residuo": float(fila["caudal_residuo"])}
        lista = F[F.index.isin(listas)]
        self.probabilidades_fuga.append(lista)
        if self.carpeta_sesion and len(lista):
            self.reg_fugas.escribir(lista.rename_axis("fecha").reset_index().to_dict("records"))
        return novedades

    def _actualizar_fuga(self, hora, en_alarma, fila):
        a = self.fuga_abierta
        if en_alarma:
            if a is None:
                a = self.fuga_abierta = {"id": len(self.fugas) + 1, "inicio": hora, "fin": hora, "tramos": Counter(),
                                         "probabilidad_maxima": 0.0, "caudal_maximo": np.nan, "sin_alarma": 0}
                nueva = True
            else:
                nueva = False
            a.update(fin=hora, sin_alarma=0, probabilidad_maxima=max(a["probabilidad_maxima"], float(fila["p_fuga"])))
            a["tramos"][fila["tramo"]] += float(fila["p_tramo"])
            q = float(fila["caudal_residuo"])
            a["caudal_maximo"] = q if not a["caudal_maximo"] == a["caudal_maximo"] else max(a["caudal_maximo"], q)
            if nueva:
                return [{"evento": "fuga_abierta", "id": a["id"], "hora": str(hora), "tramo": fila["tramo"],
                         "p_tramo": float(fila["p_tramo"]), "probabilidad": float(fila["p_fuga"]),
                         "umbral": self.modelos.fugas["umbral"], "caudal_residuo": q}]
            return []
        if a is not None:
            a["sin_alarma"] += 1
            if a["sin_alarma"] >= self.cfg.horas_para_cerrar:
                self.fugas.append(self._fuga_json(a))
                self.fuga_abierta = None
                return [{"evento": "fuga_cerrada", "id": a["id"], "hora": str(hora)}]
        return []

    @staticmethod
    def _fuga_json(a, abierta=False):
        return {"id": a["id"], "inicio": str(a["inicio"]), "fin": None if abierta else str(a["fin"]),
                "horas": int((a["fin"] - a["inicio"]).total_seconds() // 3600) + 1,
                "tramo": a["tramos"].most_common(1)[0][0] if a["tramos"] else None,
                "probabilidad_maxima": _num(a["probabilidad_maxima"], 3),
                "caudal_extra_Ls": _num(a["caudal_maximo"], 1)}

    def lista_fugas(self):
        return self.fugas + ([self._fuga_json(self.fuga_abierta, abierta=True)] if self.fuga_abierta else [])

    def tabla_fugas(self):
        """Probabilidad de fuga y tramo por hora (solo horas listas)."""
        return pd.concat(self.probabilidades_fuga).sort_index() if self.probabilidades_fuga else pd.DataFrame()

    def resumen_fugas(self, horas=168):
        """Estado actual y las últimas `horas` de probabilidad de fuga (para el dashboard)."""
        u = self.ultima_fuga
        t = self.tabla_fugas()
        if t.empty or not u:
            return {"hora": None, "actual": None, "serie": [], "fugas": self.lista_fugas(), "tramos": []}
        t = t[t.index > t.index.max() - pd.Timedelta(hours=horas)]
        f = self.modelos.fugas
        return {"hora": str(u["hora"]),
                "actual": {"probabilidad": _num(u["probabilidad"], 3), "umbral": u["umbral"],
                           "en_alarma": bool(u["en_alarma"]), "tramo": u["tramo"], "p_tramo": _num(u["p_tramo"], 3),
                           "caudal_extra_Ls": _num(u["caudal_residuo"], 1)},
                "serie": [{"fecha": str(i), "probabilidad": _num(r.p_fuga, 3),
                           "caudal_extra_Ls": _num(r.caudal_residuo, 2),
                           "en_alarma": bool(r.en_alarma),
                           "riesgo": ({k: _num(v, 3) for k, v in r.riesgo.items()}
                                      if isinstance(getattr(r, "riesgo", None), dict) else None)}
                          for i, r in t.iterrows()],
                "fugas": self.lista_fugas(), "tramos": sorted(set(f["tramos"].values())),
                "modelo": f["nombre"], "confirmar_h": f["confirmar_h"]}

    # ------------------------------------------------------------------ anticipación
    def _anticipar(self, w15, horas, listas):
        ha = anticipacion.horario(w15)
        # lluvia de 30 días: el búfer guarda solo `historia_h` horas, así que la lluvia horaria se
        # guarda aparte
        lluvia = ha["lluvia_mm_h"].dropna()
        self.lluvia_horaria = pd.concat([self.lluvia_horaria[~self.lluvia_horaria.index.isin(lluvia.index)],
                                         lluvia]).sort_index()
        corte = horas[-1] - pd.Timedelta(days=DIAS_LLUVIA)
        self.lluvia_horaria = self.lluvia_horaria[self.lluvia_horaria.index > corte]
        completa = self.lluvia_horaria.reindex(pd.date_range(self.lluvia_horaria.index.min(), horas[-1], freq="1h"))
        lluvia_mes = anticipacion.lluvia_30d(completa)
        P = self.modelos.anticipar(ha, horas, lluvia_mes=lluvia_mes)
        self.anticipaciones.append(P[P.index.isin(listas)])
        eleccion = self.modelos.anticipacion["eleccion"]
        # a 48 h (RF-003.2 d): solo se muestra en el dashboard; los avisos y alertas son los de 24 h
        con_48h = getattr(self.modelos, "tiene_48h", lambda: False)()
        P48 = self.modelos.anticipar(ha, horas, lluvia_mes=lluvia_mes, horizonte=48) if con_48h else None
        eleccion_48h = self.modelos.anticipacion.get("eleccion_48h", {}) if con_48h else {}
        novedades, filas = [], []
        for hora in horas:
            if hora not in listas:
                continue
            estado = {}
            for k, (umbral, confirmar) in eleccion.items():
                p = float(P.loc[hora, k]) if k in P else np.nan
                alto = p == p and p >= umbral
                self.horas_alto_tipo[k] = self.horas_alto_tipo.get(k, 0) + 1 if alto else 0
                en_aviso = self.horas_alto_tipo[k] >= confirmar
                estado[k] = {"probabilidad": p, "umbral": umbral, "en_aviso": en_aviso}
                if k in eleccion_48h and P48 is not None and k in P48:
                    u48, c48 = eleccion_48h[k]
                    p48 = float(P48.loc[hora, k])
                    alto48 = p48 == p48 and p48 >= u48
                    self.horas_alto_48h[k] = self.horas_alto_48h.get(k, 0) + 1 if alto48 else 0
                    estado[k].update(probabilidad_48h=p48, umbral_48h=u48, en_aviso_48h=self.horas_alto_48h[k] >= c48)
                filas.append({"fecha": hora, "tipo": _nombre_tipo(k), "probabilidad": p, "umbral": umbral,
                              "en_aviso": en_aviso})
                novedades += self._actualizar_aviso(hora, k, p, umbral, en_aviso)
            self.ultima_anticipacion = {"hora": hora, "tipos": estado}
        if self.carpeta_sesion and filas:
            self.reg_ant.escribir(filas)
        return novedades

    def _actualizar_aviso(self, hora, k, p, umbral, en_aviso):
        a = self.avisos_abiertos.get(k)
        if en_aviso:
            if a is None:
                a = self.avisos_abiertos[k] = {"id": len(self.avisos) + len(self.avisos_abiertos) + 1,
                                               "tipo": _nombre_tipo(k), "inicio": hora, "fin": hora,
                                               "probabilidad_maxima": p, "sin_aviso": 0}
                return [{"evento": "aviso_anticipado", "id": a["id"], "tipo": a["tipo"], "codigo": k,
                         "hora": str(hora), "probabilidad": p, "umbral": umbral}]
            a.update(fin=hora, sin_aviso=0, probabilidad_maxima=max(a["probabilidad_maxima"], p))
            return []
        if a is not None:
            a["sin_aviso"] += 1
            if a["sin_aviso"] >= HORAS_FIN_AVISO:
                self.avisos.append(self._aviso_json(a))
                del self.avisos_abiertos[k]
                return [{"evento": "aviso_terminado", "id": a["id"], "tipo": a["tipo"], "hora": str(hora)}]
        return []

    @staticmethod
    def _aviso_json(a, abierto=False):
        return {"id": a["id"], "tipo": a["tipo"], "inicio": str(a["inicio"]),
                "fin": None if abierto else str(a["fin"]), "probabilidad_maxima": _num(a["probabilidad_maxima"], 3)}

    def tabla_anticipacion(self):
        """Probabilidad de que empiece cada tipo de evento en 24 h, por hora (solo horas listas)."""
        return pd.concat(self.anticipaciones).sort_index() if self.anticipaciones else pd.DataFrame()

    def lista_avisos(self):
        return self.avisos + [self._aviso_json(a, abierto=True) for a in self.avisos_abiertos.values()]

    def resumen_anticipacion(self):
        """Probabilidad actual de cada tipo de evento en las próximas 24 h, con su umbral."""
        u = self.ultima_anticipacion
        if not u:
            return {"hora": None, "tipos": []}
        return {"hora": str(u["hora"]),
                "tipos": [{"tipo": _nombre_tipo(k), "probabilidad": _num(e["probabilidad"], 3),
                           "umbral": e["umbral"], "en_aviso": e["en_aviso"],
                           "probabilidad_48h": _num(e.get("probabilidad_48h"), 3), "umbral_48h": e.get("umbral_48h"),
                           "en_aviso_48h": e.get("en_aviso_48h")} for k, e in u["tipos"].items()]}

    def _actualizar_alarma(self, hora, en_alarma, tipos):
        a = self.alarma_abierta
        if en_alarma:
            self.horas_sin_alarma = 0
            if a is None:
                a = self.alarma_abierta = {"id": self._siguiente_id, "inicio": hora, "fin": hora,
                                           "sensores": set(), "tipos": Counter()}
                self._siguiente_id += 1
                nueva = [{"evento": "alarma_abierta", "id": a["id"], "hora": str(hora), "sensores": sorted(en_alarma)}]
            else:
                nueva = []
            a["fin"] = hora
            a["sensores"].update(en_alarma)
            a["tipos"].update(tipos)
            return nueva
        if a is not None:
            self.horas_sin_alarma += 1
            if self.horas_sin_alarma >= self.cfg.horas_para_cerrar:
                cerrada = self._alarma_json(a)
                self.alarmas.append(cerrada)
                self.alarma_abierta = None
                if self.carpeta_sesion:
                    self.reg_alarmas.escribir([cerrada])
                return [{"evento": "alarma_cerrada", "id": cerrada["id"], "hora": str(hora)}]
        return []

    @staticmethod
    def _alarma_json(a, abierta=False):
        tipo = carga.TIPOS_EVENTO.get(a["tipos"].most_common(1)[0][0], "?") if a["tipos"] else "?"
        return {"id": a["id"], "inicio": str(a["inicio"]), "fin": None if abierta else str(a["fin"]),
                "horas": int((a["fin"] - a["inicio"]).total_seconds() // 3600) + 1,
                "sensores": ", ".join(sorted(a["sensores"])), "tipo_sugerido": tipo}

    # ------------------------------------------------------------------ consultas (dashboard)
    DIAS_RECIENTES = 8

    def _actualizar_reciente(self, pron, det):
        """Últimos días de pronósticos y detección, para responder rápido a la API."""
        corte = det["fecha"].max() - pd.Timedelta(days=self.DIAS_RECIENTES)
        self.reciente_pron = pd.concat([getattr(self, "reciente_pron", pd.DataFrame()), pron], ignore_index=True)
        self.reciente_det = pd.concat([getattr(self, "reciente_det", pd.DataFrame()), det], ignore_index=True)
        self.reciente_pron = self.reciente_pron[self.reciente_pron["fecha"] > corte]
        self.reciente_det = self.reciente_det[self.reciente_det["fecha"] > corte]

    def resumen_sensores(self):
        """Estado actual de cada sensor: última hora observada, pronóstico a 24 h y detector."""
        if not hasattr(self, "reciente_pron") or self.reciente_pron.empty:
            return []
        hora = self.reciente_pron["fecha"].max()
        p = self.reciente_pron[self.reciente_pron["fecha"] == hora].set_index("nodo")
        d = self.reciente_det[self.reciente_det["fecha"] == hora].set_index("nodo")
        tip = self.modelos.tipicos
        filas = []
        for n in self.sensores:
            fila = {"nodo": n, "hora": str(hora), "cloro_tipico": round(float(tip[("CL2", n)]), 3),
                    # valor típico en operación normal: si ya está fuera de la norma, el incumplimiento
                    # es habitual en ese punto (el dashboard no lo trata como alerta crítica)
                    "tipicos": {par: _num(tip.get((par, n))) for par in SALIDAS}}
            for par in SALIDAS:
                fila[par] = _num(p[f"base_{par}"].get(n))
                fila[f"pronostico_{par}"] = _num(p[par].get(n))
            fila["p_evento"] = _num(d["p_evento"].get(n))
            fila["tipo_sugerido"] = carga.TIPOS_EVENTO.get(int(d["tipo"].get(n, 0)), "?")
            fila["en_alarma"] = bool(d["en_alarma"].get(n, False))
            filas.append(fila)
        return filas

    def serie_sensor(self, nodo, horas=72):
        """
        Serie horaria de un sensor para graficar: lo observado en las últimas `horas`, el pronóstico
        que se había hecho 24 h antes para cada una de esas horas, el pronóstico de las próximas 24 h
        y la probabilidad de evento.
        """
        if not hasattr(self, "reciente_pron") or self.reciente_pron.empty:
            return {"ahora": None, "puntos": []}
        p = self.reciente_pron[self.reciente_pron["nodo"] == nodo]
        d = self.reciente_det[self.reciente_det["nodo"] == nodo].set_index("fecha")
        ahora = p["fecha"].max()
        desde = ahora - pd.Timedelta(hours=horas - 1)
        obs = p.set_index("fecha")
        pron = p.set_index("fecha_pronosticada")
        puntos = []
        for f in pd.date_range(desde, ahora + pd.Timedelta(hours=24), freq="1h"):
            pt = {"fecha": str(f)}
            for par in SALIDAS:
                pt[par] = _num(obs[f"base_{par}"].get(f)) if f <= ahora else None
                pt[f"pronostico_{par}"] = _num(pron[par].get(f))
            pt["p_evento"] = _num(d["p_evento"].get(f)) if f <= ahora else None
            pt["en_alarma"] = bool(d["en_alarma"].get(f, False)) if f <= ahora else None
            puntos.append(pt)
        return {"ahora": str(ahora), "puntos": puntos}

    def series_red(self, horas=48):
        """
        Series de todos los sensores del sistema a la vez (para la vista general): observado de las últimas
        `horas` y pronóstico de las próximas 24 h, por parámetro.
        """
        if not hasattr(self, "reciente_pron") or self.reciente_pron.empty:
            return {"ahora": None, "fechas": [], "sensores": {}}
        p = self.reciente_pron
        ahora = p["fecha"].max()
        fechas = pd.date_range(ahora - pd.Timedelta(hours=horas - 1), ahora + pd.Timedelta(hours=24), freq="1h")
        pasado = fechas <= ahora
        sensores = {n: {} for n in self.sensores}
        for par in SALIDAS:
            obs = p.pivot(index="fecha", columns="nodo", values=f"base_{par}").reindex(fechas)
            pron = p.pivot(index="fecha_pronosticada", columns="nodo", values=par).reindex(fechas)
            for n in self.sensores:
                o = obs[n].where(pasado) if n in obs else pd.Series(np.nan, index=fechas)
                f = pron[n] if n in pron else pd.Series(np.nan, index=fechas)
                sensores[n][par] = [_num(x, 3) for x in o.values]
                sensores[n][f"pronostico_{par}"] = [_num(x, 3) for x in f.values]
        return {"ahora": str(ahora), "fechas": [str(f) for f in fechas], "sensores": sensores}

    def lista_alarmas(self):
        abiertas = [self._alarma_json(self.alarma_abierta, abierta=True)] if self.alarma_abierta else []
        return self.alarmas + abiertas

    def tabla_pronosticos(self):
        return pd.concat(self.pronosticos, ignore_index=True) if self.pronosticos else pd.DataFrame()

    def tabla_deteccion(self):
        return pd.concat(self.deteccion, ignore_index=True) if self.deteccion else pd.DataFrame()

    def matriz_alarmas(self):
        """Hora × sensor con True donde el sensor estaba en alarma."""
        d = self.tabla_deteccion()
        if d.empty:
            return pd.DataFrame()
        return d.pivot(index="fecha", columns="nodo", values="en_alarma").astype(bool)

    def estado(self):
        seg = time.time() - self.inicio_reloj
        return {"hora_simulada": str(self.ultima_lectura) if self.ultima_lectura is not None else None,
                "ultima_hora_procesada": (str(self.ultima_hora_procesada)
                                          if self.ultima_hora_procesada is not None else None),
                "lecturas_recibidas": self.lecturas_recibidas,
                "lecturas_por_segundo": round(self.lecturas_recibidas / max(seg, 1e-9), 1),
                "alarma_activa": self.alarma_abierta is not None,
                "alarmas_totales": len(self.alarmas) + (1 if self.alarma_abierta else 0),
                "modo_pronostico": self.modelos.modo, "umbral": self.modelos.umbral,
                "pronostico_lluvia": self.modelos.pronostico.descripcion,
                "error_pronostico_lluvia": getattr(self.modelos.pronostico, "error", None),
                "confirmar_h": self.modelos.confirmar_h,
                "anticipacion": getattr(self.modelos, "anticipacion", None) is not None,
                "avisos_anticipados_activos": sorted(a["tipo"] for a in self.avisos_abiertos.values()),
                "sensores": list(self.sensores),
                # lecturas del último ciclo: cuántas filas medidas, con algo rellenado o con un hueco largo
                "imputacion_ultimo_ciclo": {str(k): int(v) for k, v in self.imputacion.items()},
                "fugas": getattr(self.modelos, "fugas", None) is not None,
                "fuga_activa": self.fuga_abierta is not None}


def _nombre_tipo(k):
    return "anomalia" if k == 0 else carga.TIPOS_EVENTO.get(k, "?")


def _num(x, dec=4):
    """Número para JSON (None si falta)."""
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return None if x != x else round(x, dec)
