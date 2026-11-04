"""
Alertas del servicio de monitoreo (por ahora por Telegram).

Qué se avisa:
  - alarma abierta: tipo de evento sugerido, sensores con su probabilidad de evento y sus valores
    de cloro, turbidez y pH, a qué sensores todavía no llega (si empieza en la planta) y qué hacer;
  - alarma cerrada: cuánto duró y qué sensores involucró;
  - riesgo en 24 h: un sensor cuyo pronóstico sale de la norma, con qué hacer según el parámetro.
    Se avisa una vez por episodio (el episodio termina cuando el pronóstico vuelve a la norma
    durante HORAS_FIN_RIESGO horas);
  - aviso anticipado: el modelo de anticipación (notebook 09) espera que empiece un evento en las
    próximas 24 h; dice el tipo, la probabilidad, por qué (las señales de ese tipo) y, si el evento
    empieza en la planta, en cuántas horas llegaría a cada sensor, y qué revisar para evitarlo;
  - resumen diario, a la hora ALERTAS_RESUMEN_HORA de los datos.

Las horas son las de los datos: con el emisor en tiempo real coinciden con el reloj.
Los mensajes salen en un hilo aparte, con reintentos, así un problema de red no frena al motor.
Si no hay canal configurado, las alertas solo se escriben en la consola.

Configuración (en el archivo .env o como variables de entorno; nunca en el código ni en git):
  TELEGRAM_TOKEN         token del bot (te lo da @BotFather)
  TELEGRAM_CHAT_ID       chat o chats que reciben las alertas, separados por coma
  ALERTAS_RIESGO         1 (por defecto) o 0: avisar del riesgo en 24 h
  ALERTAS_ANTICIPACION   1 (por defecto) o 0: mandar los avisos anticipados
  ALERTAS_RESUMEN_HORA   hora del resumen diario (por defecto 7; -1 para no enviarlo)
  URL_DASHBOARD          enlace que va en los mensajes (por defecto http://127.0.0.1:8001)

Herramientas (desde backend/, con TELEGRAM_TOKEN definido):
  python -m monitoreo.alertas --chat-id    muestra el chat id de quien le escribió al bot
  python -m monitoreo.alertas --prueba     manda un mensaje de prueba a TELEGRAM_CHAT_ID
"""

import argparse
import html
import os
import queue
import threading
import time

import numpy as np
import pandas as pd
import requests

from calidad_agua import calidad, carga

TIPOS = {"contaminacion": "Contaminación", "falla_cloro": "Falla de cloración",
         "turbidez_fuente": "Turbidez en la fuente", "falla_ph": "Falla de pH", "fuga": "Fuga",
         "?": "Evento sin clasificar"}
NOMBRE = {"CL2": "cloro", "TURB": "turbidez", "PH": "pH"}
UNIDAD = {"CL2": " mg/L", "TURB": " UNT", "PH": ""}
HORAS_FIN_RIESGO = 6            # horas seguidas en norma para dar por terminado un episodio de riesgo
# qué se ve antes de cada tipo de evento (lo que aprende el modelo de anticipación, notebook 09)
SENALES = {"contaminacion": "lluvia fuerte reciente (suelo saturado) y horas de baja presión en la red",
           "falla_cloro": "el cloro viene bajando en la salida de la planta",
           "turbidez_fuente": "aguacero fuerte: la crecida llega a la toma horas después",
           "falla_ph": "el pH viene desviándose en la salida de la planta",
           "fuga": "la fuente entrega cada día un poco más de lo normal y la presión baja: una fuga pequeña "
                   "que crece",
           "anomalia": "la operación se aparta de lo normal"}
EMPIEZAN_EN_LA_FUENTE = {"falla_cloro", "turbidez_fuente", "falla_ph"}
# qué hacer: cuando el evento ya se ve (alarma) y cuando se espera (aviso anticipado). Son una guía
# general para el operador; la ASADA debe ajustarlas a sus procedimientos.
ACCION_ALARMA = {
    "contaminacion": "tomar muestras en los sensores en alarma para confirmar; si se confirma, aislar el "
                     "sector, avisar a los abonados y buscar fugas o trabajos recientes en la zona",
    "falla_cloro": "revisar de inmediato la dosificación de cloro en la planta (bomba dosificadora, tanque "
                   "de hipoclorito y línea) y reponer la dosis",
    "turbidez_fuente": "revisar la planta (coagulación y filtros): ajustar la dosis de coagulante y, si la "
                       "turbidez sigue sobre 5 UNT, valorar suspender la toma",
    "falla_ph": "revisar el ajuste de pH en la planta (dosificación de químicos)",
    "fuga": "recorrer el tramo indicado buscando agua que aflora, hundimientos o reportes de abonados; "
            "cerrar válvulas por sectores para acotarla y programar la reparación",
    "?": "revisar las lecturas de los sensores en alarma y confirmar en campo",
}
ACCION_AVISO = {
    "contaminacion": "evitar maniobras que bajen la presión, revisar fugas conocidas y estar listo para "
                     "muestrear las zonas de baja presión",
    "falla_cloro": "revisar la bomba dosificadora y el nivel del tanque de hipoclorito antes de que la "
                   "dosis caiga más",
    "turbidez_fuente": "preparar la planta para la crecida: revisar la dosis de coagulante y los filtros y "
                       "vigilar la turbidez del agua cruda",
    "falla_ph": "revisar la dosificación de químicos de pH antes de que la deriva siga",
    "fuga": "programar una revisión del tramo indicado y comparar el caudal mínimo de la madrugada con el "
            "de días anteriores, antes de que la fuga crezca",
    "anomalia": "revisar las lecturas de la red y de la planta",
}
ACCION_RIESGO = {
    ("CL2", "mínimo"): "revisar la dosis de cloro en la planta o la recloración en el tanque que abastece el sector",
    ("CL2", "máximo"): "bajar la dosis de cloro en la planta",
    ("TURB", "máximo"): "revisar la planta (coagulación y filtros) y el agua cruda",
    ("PH", "mínimo"): "revisar el ajuste de pH en la planta",
    ("PH", "máximo"): "revisar el ajuste de pH en la planta",
}


def _fecha(t):
    """Hora de Costa Rica en DD/MM/YYYY HH:mm:ss (RNF-010)."""
    return f"{pd.Timestamp(t):%d/%m/%Y %H:%M:%S}"


def _num(x, dec=2):
    return "—" if x is None or x != x else f"{x:.{dec}f}".replace(".", ",")


def _pct(x):
    return "—" if x is None or x != x else f"{100 * x:.0f} %"


def fuera_de_norma(par, valor):
    """Texto del límite que incumple el valor, o None si está en norma."""
    if valor is None or valor != valor:
        return None
    n = calidad.NORMA[par]
    if par == "TURB":
        return f"máximo {_num(n['maximo'], 0)}" if valor > n["maximo"] else None
    if valor < n["minimo"]:
        return f"mínimo {_num(n['minimo'], 1)}"
    if valor > n["maximo"]:
        return f"máximo {_num(n['maximo'], 1)}"
    return None


def _valores(motor, hora):
    """Cloro, turbidez y pH observados de cada sensor en una hora ya procesada."""
    p = getattr(motor, "reciente_pron", pd.DataFrame())
    if p.empty:
        return {}
    p = p[p["fecha"] == pd.Timestamp(hora)].set_index("nodo")
    d = getattr(motor, "reciente_det", pd.DataFrame())
    prob = d[d["fecha"] == pd.Timestamp(hora)].set_index("nodo")["p_evento"] if not d.empty else pd.Series(dtype=float)
    tip = motor.modelos.tipicos
    return {n: {**{par: (None if pd.isna(fila[f"base_{par}"]) else float(fila[f"base_{par}"]))
                   for par in ["CL2", "TURB", "PH"]}, "cloro_tipico": float(tip[("CL2", n)]),
                "p_evento": None if pd.isna(prob.get(n, np.nan)) else float(prob.get(n))}
            for n, fila in p.iterrows()}


def _por_horas(llegadas, max_sensores=6):
    """[(nodo, horas)] -> '~1 h: J439 · ~2 h: J224, J69 y 8 más · ~15 h: J144'."""
    grupos = {}
    for nodo, h in llegadas:
        grupos.setdefault(int(round(h)), []).append(nodo)
    partes = []
    for h, nodos in sorted(grupos.items()):
        resto = f" y {len(nodos) - max_sensores} más" if len(nodos) > max_sensores else ""
        txt = ", ".join(nodos[:max_sensores]) + resto
        partes.append(f"~{h} h: {txt}")
    return " · ".join(partes)


def _llegada(motor, ya):
    """Sensores a los que un evento de la planta todavía no llegó, con las horas típicas de llegada
    contadas desde la salida de la planta (retrasos del notebook 09). Lista vacía si no hay datos."""
    retrasos = (getattr(motor.modelos, "anticipacion", None) or {}).get("retrasos_propagacion")
    if retrasos is None:
        return []
    orden = retrasos["mediana"].dropna().sort_values()
    return [(nodo, horas) for nodo, horas in orden.items() if nodo not in ya and horas > 0]


# ---------------------------------------------------------------------------- canales
class CanalTelegram:
    nombre = "telegram"

    def __init__(self, token, chats):
        self.url = f"https://api.telegram.org/bot{token}/sendMessage"
        self.chats = chats

    def enviar(self, texto):
        for chat in self.chats:
            r = requests.post(self.url, json={"chat_id": chat, "text": texto, "parse_mode": "HTML",
                                              "disable_web_page_preview": True}, timeout=15)
            if r.status_code != 200:
                raise RuntimeError(f"Telegram respondió {r.status_code}: {r.text[:200]}")


class CanalConsola:
    nombre = "consola"

    def enviar(self, texto):
        texto = "[alerta] " + texto.replace("<b>", "").replace("</b>", "")
        try:
            print(texto, flush=True)
        except UnicodeEncodeError:                         # consola que no acepta emojis
            print(texto.encode("ascii", "replace").decode(), flush=True)


def canal_desde_entorno():
    token = os.environ.get("TELEGRAM_TOKEN", "").strip()
    chats = [c.strip() for c in os.environ.get("TELEGRAM_CHAT_ID", "").split(",") if c.strip()]
    if token and chats:
        return CanalTelegram(token, chats)
    return CanalConsola()


# ---------------------------------------------------------------------------- alertas
class Alertas:
    def __init__(self, canal=None):
        self.canal = canal or canal_desde_entorno()
        self.con_riesgo = os.environ.get("ALERTAS_RIESGO", "1") != "0"
        self.con_anticipacion = os.environ.get("ALERTAS_ANTICIPACION", "1") != "0"
        self.hora_resumen = int(os.environ.get("ALERTAS_RESUMEN_HORA", "7"))
        self.url = os.environ.get("URL_DASHBOARD", "http://127.0.0.1:8001").rstrip("/")
        self.riesgo = {}                    # (sensor, parámetro) -> horas seguidas en norma (episodio abierto)
        self.enviadas, self.fallidas, self.ultimo_error = 0, 0, None
        self._cola = queue.Queue()
        threading.Thread(target=self._enviar_en_fondo, daemon=True).start()

    def estado(self):
        return {"canal": self.canal.nombre, "enviadas": self.enviadas, "fallidas": self.fallidas,
                "ultimo_error": self.ultimo_error, "riesgo_24h": self.con_riesgo,
                "resumen_hora": self.hora_resumen if self.hora_resumen >= 0 else None}

    def avisar(self, texto):
        self._cola.put(texto)

    def _enviar_en_fondo(self):
        while True:
            texto = self._cola.get()
            for intento in range(4):
                try:
                    self.canal.enviar(texto)
                    self.enviadas += 1
                    break
                except Exception as e:                    # sin red, token malo...: se reintenta
                    self.ultimo_error = str(e)[:200]
                    time.sleep(2 ** intento * 5)
            else:
                self.fallidas += 1

    # ------------------------------------------------------------------ después de cada ciclo
    def revisar(self, motor, novedades):
        """Se llama después de motor.procesar(), con el candado del motor tomado."""
        if motor.ultima_hora_procesada is None:
            return
        ahora = motor.ultima_hora_procesada
        anterior = getattr(self, "_ultima_hora", None)
        if ahora == anterior:
            return                          # el servicio llama cada segundo: solo cuentan las horas nuevas
        self._ultima_hora = ahora
        horas_nuevas = 1 if anterior is None else int((ahora - anterior) / pd.Timedelta(hours=1))
        sensores = {s["nodo"]: s for s in motor.resumen_sensores()}
        # un ciclo puede procesar varias horas (al arrancar o con el emisor acelerado): cada aviso
        # lleva los valores de su propia hora
        for n in novedades:
            if n["evento"] == "alarma_abierta":
                self.avisar(self._texto_abierta(motor, n, _valores(motor, n["hora"])))
            elif n["evento"] == "alarma_cerrada":
                self.avisar(self._texto_cerrada(motor, n))
            elif n["evento"] == "aviso_anticipado" and self.con_anticipacion:
                self.avisar(self._texto_aviso(motor, n))
        if self.con_riesgo:
            self._revisar_riesgo(motor, sensores, ahora, horas_nuevas)
        if self.hora_resumen >= 0:
            # al arrancar no se manda: solo cuando el procesamiento pasa por la hora del resumen
            horas = pd.date_range(anterior, ahora, freq="1h")[1:] if anterior is not None else []
            if any(h.hour == self.hora_resumen for h in horas):
                self.avisar(self._texto_resumen(motor, sensores, ahora))

    def _texto_abierta(self, motor, n, sensores):
        # la alarma puede seguir abierta o haberse cerrado en el mismo ciclo
        a = motor.alarma_abierta
        if a is not None and a["id"] == n["id"]:
            tipo = carga.TIPOS_EVENTO.get(a["tipos"].most_common(1)[0][0], "?") if a["tipos"] else "?"
        else:
            tipo = next((x["tipo_sugerido"] for x in motor.alarmas if x["id"] == n["id"]), "?")
        tipo_txt = TIPOS.get(tipo, "Evento sin clasificar")
        plural = "es" if len(n["sensores"]) > 1 else ""
        lineas = [f"🔴 <b>Alarma #{n['id']}: {html.escape(tipo_txt)}</b> (tipo sugerido)",
                  f"{_fecha(n['hora'])} · {len(n['sensores'])} sensor{plural} en alarma"]
        # primero los sensores con más probabilidad de evento
        orden = sorted(n["sensores"], key=lambda x: (-(sensores.get(x, {}).get("p_evento") or 0), x))
        for nodo in orden[:6]:
            s = sensores.get(nodo, {})
            valores = " · ".join(f"{NOMBRE[p]} {_num(s.get(p))}{UNIDAD[p]}" for p in ["CL2", "TURB", "PH"])
            lineas.append(f"• <b>{nodo}</b> ({_pct(s.get('p_evento'))}): {valores} "
                          f"(cloro típico {_num(s.get('cloro_tipico'))})")
        if len(n["sensores"]) > 6:
            lineas.append(f"• y {len(n['sensores']) - 6} sensores más")
        if tipo in EMPIEZAN_EN_LA_FUENTE:
            faltan = _llegada(motor, set(n["sensores"]))
            if faltan:
                lineas.append("Empieza en la planta; todavía no llega a (horas típicas desde la salida de la "
                              "planta): " + _por_horas(faltan))
        elif tipo == "contaminacion":
            lineas.append("Evento local: afecta el agua que pasa por esos sensores.")
        lineas.append(f"<b>Qué hacer:</b> {ACCION_ALARMA.get(tipo, ACCION_ALARMA['?'])}.")
        lineas.append(f"{self.url}/#/sensor/{orden[0]}")
        return "\n".join(lineas)

    def _texto_cerrada(self, motor, n):
        a = next((x for x in motor.alarmas if x["id"] == n["id"]), None)
        if a is None:
            return f"🟢 <b>Alarma #{n['id']} cerrada</b> · {_fecha(n['hora'])}"
        tipo = html.escape(TIPOS.get(a["tipo_sugerido"], a["tipo_sugerido"]))
        return (f"🟢 <b>Alarma #{a['id']} cerrada</b> · {tipo}\n"
                f"De {_fecha(a['inicio'])} a {_fecha(a['fin'])} ({a['horas']} h) · sensores: {a['sensores']}")

    def _texto_aviso(self, motor, n):
        tipo = n["tipo"]
        nombre = TIPOS.get(tipo, "Evento fuera de lo normal") if tipo != "anomalia" else "Operación fuera de lo normal"
        lineas = [f"🟡 <b>Aviso anticipado: posible {html.escape(nombre.lower())} en las próximas 24 h</b>",
                  f"{_fecha(n['hora'])} · probabilidad {_pct(n['probabilidad'])} (umbral {_pct(n['umbral'])})",
                  f"Señal: {SENALES.get(tipo, SENALES['anomalia'])}."]
        llegadas = _llegada(motor, set()) if tipo in EMPIEZAN_EN_LA_FUENTE else []
        if llegadas:
            lineas.append("Si ocurre, empieza en la planta (J280) y llegaría a los sensores en: "
                          + _por_horas(llegadas))
        lineas.append(f"<b>Qué hacer:</b> {ACCION_AVISO.get(tipo, ACCION_AVISO['anomalia'])}.")
        lineas.append(self.url)
        return "\n".join(lineas)

    def _revisar_riesgo(self, motor, sensores, ahora, horas_nuevas=1):
        nuevos = []
        for nodo, s in sensores.items():
            for par in ["CL2", "TURB", "PH"]:
                limite = fuera_de_norma(par, s.get(f"pronostico_{par}"))
                clave = (nodo, par)
                if limite:
                    if clave not in self.riesgo:
                        nuevos.append((nodo, par, s.get(f"pronostico_{par}"), limite))
                    self.riesgo[clave] = 0
                elif clave in self.riesgo:
                    self.riesgo[clave] += horas_nuevas
                    if self.riesgo[clave] >= HORAS_FIN_RIESGO:
                        del self.riesgo[clave]
        if nuevos:
            para = _fecha(ahora + pd.Timedelta(hours=24))
            lineas = [f"🟠 <b>Riesgo en 24 h</b>: pronóstico fuera de norma para el {para}"]
            for nodo, par, v, limite in nuevos[:10]:
                lineas.append(f"• <b>{nodo}</b>: {NOMBRE[par]} {_num(v)}{UNIDAD[par]} ({limite})")
            if len(nuevos) > 10:
                lineas.append(f"• y {len(nuevos) - 10} más")
            acciones = dict.fromkeys(ACCION_RIESGO[(par, limite.split()[0])] for _, par, _, limite in nuevos)
            lineas.append("<b>Qué hacer:</b> " + "; ".join(acciones) + ".")
            lineas.append(self.url)
            self.avisar("\n".join(lineas))

    def _texto_resumen(self, motor, sensores, ahora):
        desde = ahora - pd.Timedelta(hours=24)
        alarmas = [a for a in motor.lista_alarmas() if a["fin"] is None or pd.Timestamp(a["fin"]) >= desde]
        fuera = [f"{nodo} ({NOMBRE[p]})" for nodo, s in sensores.items() for p in ["CL2", "TURB", "PH"]
                 if fuera_de_norma(p, s.get(p))]
        riesgo = sorted({f"{nodo} ({NOMBRE[p]})" for nodo, p in self.riesgo})
        lineas = [f"📋 <b>Resumen</b> · {_fecha(ahora)}",
                  f"Alarmas en las últimas 24 h: {len(alarmas)}"
                  + (" (una en curso)" if motor.alarma_abierta else "")]
        for a in alarmas[-5:]:
            tipo = html.escape(TIPOS.get(a["tipo_sugerido"], a["tipo_sugerido"]))
            lineas.append(f"• #{a['id']} {tipo}: {a['sensores']}")
        lineas.append("Fuera de norma ahora: " + (", ".join(fuera) if fuera else "ninguno"))
        if self.con_riesgo:
            lineas.append("Con riesgo en 24 h: " + (", ".join(riesgo) if riesgo else "ninguno"))
        if getattr(motor.modelos, "anticipacion", None) is not None:
            activos = [TIPOS.get(a["tipo"], "anomalía").lower() for a in motor.avisos_abiertos.values()]
            lineas.append("Avisos anticipados activos: " + (", ".join(activos) if activos else "ninguno"))
        lineas.append(self.url)
        return "\n".join(lineas)


# ---------------------------------------------------------------------------- herramientas
def _token():
    token = os.environ.get("TELEGRAM_TOKEN", "").strip()
    if not token:
        raise SystemExit("Falta TELEGRAM_TOKEN: pon el token del bot en el archivo .env (ver .env.ejemplo).")
    return token


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Herramientas de las alertas por Telegram")
    ap.add_argument("--chat-id", action="store_true", help="mostrar el chat id de quien le escribió al bot")
    ap.add_argument("--prueba", action="store_true", help="mandar un mensaje de prueba")
    args = ap.parse_args()
    if args.chat_id:
        r = requests.get(f"https://api.telegram.org/bot{_token()}/getUpdates", timeout=15).json()
        chats = {}
        for u in r.get("result", []):
            m = u.get("message") or u.get("channel_post") or {}
            if "chat" in m:
                c = m["chat"]
                chats[c["id"]] = c.get("title") or " ".join(x for x in [c.get("first_name"), c.get("last_name")] if x)
        if not chats:
            print("No hay mensajes. Abre el chat con tu bot en Telegram, mándale cualquier mensaje y repite.")
        for cid, nombre in chats.items():
            print(f"chat id: {cid}  ({nombre})")
    elif args.prueba:
        canal = canal_desde_entorno()
        if canal.nombre != "telegram":
            raise SystemExit("Faltan TELEGRAM_TOKEN y TELEGRAM_CHAT_ID.")
        canal.enviar("✅ <b>Prueba</b> del servicio de monitoreo de calidad de agua. Las alertas llegan a este chat.")
        print("Mensaje enviado.")
    else:
        ap.print_help()
