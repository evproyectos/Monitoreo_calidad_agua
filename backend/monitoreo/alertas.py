"""
Alertas del servicio de monitoreo, por correo (SMTP, RF-003.3) y por Telegram.

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

Cada aviso tiene un nivel: rojo (alarmas y fugas), amarillo (aviso anticipado, riesgo en 24 h y
deriva) o resumen. Por correo lo reciben los usuarios que el administrador marcó para ese nivel en la
página Usuarios (ver correo.py); el asunto dice el nivel, qué pasa y en qué sensor o tramo (CU-04).
Por Telegram lo reciben los chats de TELEGRAM_CHAT_ID, sin importar el nivel.

Las horas son las de los datos: con el emisor en tiempo real coinciden con el reloj.
Cada canal manda en su propio hilo, con 3 reintentos con espera creciente (5, 10 y 20 s, RNF-002),
así un problema de red no frena al motor ni a los otros canales. Cada envío, logrado o no, queda
registrado (tabla notificaciones, visible para el administrador). Si no hay canal configurado, las
alertas solo se escriben en la consola.

Configuración (en el archivo .env o como variables de entorno; nunca en el código ni en git):
  SMTP_SERVIDOR, SMTP_PUERTO, SMTP_USUARIO, SMTP_CONTRASENA, SMTP_REMITENTE, SMTP_SEGURIDAD
                         servidor de correo (ver correo.py y .env.ejemplo)
  TELEGRAM_TOKEN         token del bot (te lo da @BotFather)
  TELEGRAM_CHAT_ID       chat o chats que reciben las alertas, separados por coma
  ALERTAS_RIESGO         1 (por defecto) o 0: avisar del riesgo en 24 h
  ALERTAS_ANTICIPACION   1 (por defecto) o 0: mandar los avisos anticipados
  ALERTAS_RESUMEN_HORA   hora del resumen diario (por defecto 7; -1 para no enviarlo)
  URL_DASHBOARD          enlace que va en los mensajes (por defecto http://127.0.0.1:8001)

Herramientas (desde backend/):
  python -m monitoreo.correo --prueba destino@correo.com   correo de prueba (con SMTP_... definidas)
  python -m monitoreo.alertas --chat-id    muestra el chat id de quien le escribió al bot
  python -m monitoreo.alertas --prueba     manda un mensaje de prueba a TELEGRAM_CHAT_ID
"""

import argparse
import html
import os
import queue
import threading
import time
from datetime import datetime

import numpy as np
import pandas as pd
import requests

from calidad_agua import calidad, carga
from monitoreo import correo

TIPOS = {"contaminacion": "Contaminación", "falla_cloro": "Falla de cloración",
         "turbidez_fuente": "Turbidez en la fuente", "falla_ph": "Falla de pH", "fuga": "Fuga",
         "?": "Evento sin clasificar"}
NOMBRE = {"CL2": "cloro", "TURB": "turbidez", "PH": "pH"}
UNIDAD = {"CL2": " mg/L", "TURB": " UNT", "PH": ""}
ESPERAS_S = (5, 10, 20)         # espera antes de cada reintento (RNF-002: al menos 3 reintentos)
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


def _minus(texto):
    """Primera letra en minúscula, sin tocar el resto ("Falla de pH" -> "falla de pH")."""
    return texto[:1].lower() + texto[1:]


def _nodos(nodos, maximo=1):
    """['J439', 'J224', 'J69'] -> 'J439 y 2 sensores más' (para el asunto del correo)."""
    nodos = list(nodos)
    if len(nodos) <= maximo:
        return ", ".join(nodos)
    resto = len(nodos) - maximo
    return ", ".join(nodos[:maximo]) + f" y {resto} sensor{'es' if resto > 1 else ''} más"


class Aviso:
    """Un mensaje con su nivel (rojo, amarillo, resumen o prueba) y su asunto. `para` fija los
    destinatarios del correo (solo en la prueba); si no, salen del nivel. `enlace` es la alerta en el
    tablero (el botón del correo)."""

    def __init__(self, texto, nivel="rojo", asunto=None, para=None, enlace=None):
        self.texto, self.nivel, self.para, self.enlace = texto, nivel, para, enlace
        self.asunto = asunto or _texto_plano(texto.split("\n")[0])
        self.pendientes, self.entregados = None, []            # para los reintentos del correo

    @classmethod
    def prueba(cls, para):
        texto = ("✅ <b>Correo de prueba</b>\n"
                 f"{_fecha(datetime.now())} · el servicio de monitoreo puede enviar las alertas por correo.\n"
                 "Las alertas reales dicen en el asunto el nivel (roja o amarilla), qué pasa y en qué sensor o "
                 "tramo; adentro, la probabilidad, la antelación y qué hacer.")
        return cls(texto, "prueba", "ASADA La Lucha · Correo de prueba de las alertas", para)


def _texto_plano(texto):
    return html.unescape(texto.replace("<b>", "").replace("</b>", ""))


# ---------------------------------------------------------------------------- canales
class CanalTelegram:
    nombre = "telegram"

    def __init__(self, token, chats):
        self.url = f"https://api.telegram.org/bot{token}/sendMessage"
        self.chats = chats

    def enviar(self, aviso):
        for chat in self.chats:
            r = requests.post(self.url, json={"chat_id": chat, "text": aviso.texto, "parse_mode": "HTML",
                                              "disable_web_page_preview": True}, timeout=15)
            if r.status_code != 200:
                raise RuntimeError(f"Telegram respondió {r.status_code}: {r.text[:200]}")
        return [f"{len(self.chats)} chat{'s' if len(self.chats) > 1 else ''} de Telegram"]


class CanalConsola:
    nombre = "consola"

    def enviar(self, aviso):
        texto = "[alerta] " + _texto_plano(aviso.texto)
        try:
            print(texto, flush=True)
        except UnicodeEncodeError:                         # consola que no acepta emojis
            print(texto.encode("ascii", "replace").decode(), flush=True)
        return []


def canales_desde_entorno(destinatarios=None, url=None):
    """Correo si hay SMTP_SERVIDOR, Telegram si hay TELEGRAM_TOKEN y TELEGRAM_CHAT_ID; si no hay
    ninguno, la consola."""
    canales = []
    if correo.configurado():
        canales.append(correo.CanalCorreo.desde_entorno(destinatarios, url))
    token = os.environ.get("TELEGRAM_TOKEN", "").strip()
    chats = [c.strip() for c in os.environ.get("TELEGRAM_CHAT_ID", "").split(",") if c.strip()]
    if token and chats:
        canales.append(CanalTelegram(token, chats))
    return canales or [CanalConsola()]


class _Envio:
    """La cola y el hilo de un canal: manda en orden, con reintentos, y registra cada resultado."""

    def __init__(self, canal, registro):
        self.canal, self.registro = canal, registro
        self.enviadas, self.fallidas, self.ultimo_error = 0, 0, None
        self.cola = queue.Queue()
        threading.Thread(target=self._en_fondo, daemon=True, name=f"alertas-{canal.nombre}").start()

    def estado(self):
        return {"enviadas": self.enviadas, "fallidas": self.fallidas, "ultimo_error": self.ultimo_error,
                "en_cola": self.cola.qsize()}

    def _anotar(self, aviso, estado, para, intentos, error=None):
        if self.registro is None or self.canal.nombre == "consola":
            return
        try:
            self.registro(canal=self.canal.nombre, nivel=aviso.nivel, asunto=aviso.asunto, estado=estado,
                          destinatarios=", ".join(para or []), intentos=intentos, error=error)
        except Exception as e:                            # sin base: el envío no se frena por esto
            print(f"No se pudo registrar la notificación: {e}", flush=True)

    def mandar(self, aviso, esperas=ESPERAS_S):
        """Manda un aviso con sus reintentos. Devuelve True si llegó."""
        for intento in range(len(esperas) + 1):
            try:
                para = self.canal.enviar(aviso)
            except correo.SinDestinatarios as e:
                self._anotar(aviso, "sin_destinatarios", [], intento + 1, str(e))
                return False
            except Exception as e:                        # sin red, clave mala...: se reintenta
                self.ultimo_error = correo.explicar(e)[:200]
                if intento < len(esperas):
                    time.sleep(esperas[intento])
                continue
            # primero el registro y después el contador: quien vea el contador ya encuentra el registro
            self._anotar(aviso, "enviada", para, intento + 1)
            self.enviadas += 1
            return True
        self._anotar(aviso, "fallida", getattr(aviso, "pendientes", None), len(esperas) + 1, self.ultimo_error)
        self.fallidas += 1
        print(f"[alerta no enviada por {self.canal.nombre}] {aviso.asunto}: {self.ultimo_error}", flush=True)
        return False

    def _en_fondo(self):
        while True:
            self.mandar(self.cola.get())


# ---------------------------------------------------------------------------- alertas
class Alertas:
    def __init__(self, canal=None, canales=None, destinatarios=None, registro=None, gestion=None):
        """`destinatarios(nivel)` da los correos de un nivel (Usuarios.destinatarios), `registro(...)`
        anota cada envío (Usuarios.anotar_notificacion) y `gestion` (GestionAlertas) guarda cada alerta
        para atenderla (CU-06): una alerta que ya existía no se vuelve a notificar."""
        self.con_riesgo = os.environ.get("ALERTAS_RIESGO", "1") != "0"
        self.con_anticipacion = os.environ.get("ALERTAS_ANTICIPACION", "1") != "0"
        self.hora_resumen = int(os.environ.get("ALERTAS_RESUMEN_HORA", "7"))
        self.url = os.environ.get("URL_DASHBOARD", "http://127.0.0.1:8001").rstrip("/")
        self.canales = canales or ([canal] if canal else canales_desde_entorno(destinatarios, self.url))
        self.riesgo = {}                    # (sensor, parámetro) -> horas seguidas en norma (episodio abierto)
        self.gestion = gestion
        self._envios = [_Envio(c, registro) for c in self.canales]

    @property
    def nombre(self):
        return " + ".join(c.nombre for c in self.canales)

    @property
    def correo(self):
        return next((c for c in self.canales if c.nombre == "correo"), None)

    @property
    def enviadas(self):
        return sum(e.enviadas for e in self._envios)

    @property
    def fallidas(self):
        return sum(e.fallidas for e in self._envios)

    @property
    def ultimo_error(self):
        return next((e.ultimo_error for e in self._envios if e.ultimo_error), None)

    def estado(self):
        return {"canal": self.nombre, "enviadas": self.enviadas, "fallidas": self.fallidas,
                "ultimo_error": self.ultimo_error, "riesgo_24h": self.con_riesgo,
                "resumen_hora": self.hora_resumen if self.hora_resumen >= 0 else None,
                "canales": {e.canal.nombre: e.estado() for e in self._envios}}

    def avisar(self, texto, nivel="rojo", asunto=None, enlace=None):
        for e in self._envios:
            e.cola.put(Aviso(texto, nivel, asunto, enlace=enlace))   # uno por canal: cada uno con sus pendientes

    def _alerta(self, texto, nivel, asunto, **datos):
        """Guarda la alerta para atenderla y la notifica, salvo que ya existiera (deduplicación)."""
        enlace = None
        if self.gestion is not None:
            try:
                uid, nueva = self.gestion.abrir(nivel=nivel, **datos)
            except Exception as e:                        # sin base de datos se notifica igual
                print(f"No se pudo guardar la alerta: {e}", flush=True)
            else:
                if not nueva:
                    return
                enlace = f"{self.url}/#/alertas/{uid}"
        self.avisar(texto, nivel, asunto, enlace=enlace)

    def _terminar(self, grupo, hora):
        """Marca la alerta como terminada. Devuelve su enlace en el tablero (para cerrarla), None si
        no hay gestión, o False si ya había terminado (al reiniciar el servicio): no se reavisa."""
        if self.gestion is not None:
            try:
                ids = self.gestion.terminar(grupo, hora)
            except Exception as e:
                print(f"No se pudo actualizar la alerta: {e}", flush=True)
            else:
                return f"{self.url}/#/alertas/{ids[0]}" if ids else False
        return None

    def _cierre(self, texto, nivel, asunto, enlace):
        if enlace is not False:
            self.avisar(texto, nivel, asunto, enlace=enlace)

    def probar_correo(self, para):
        """Correo de prueba inmediato (sin reintentos), para el botón de la página Usuarios.
        Devuelve None si llegó o el texto del error."""
        envio = next((e for e in self._envios if e.canal.nombre == "correo"), None)
        if envio is None:
            return "El envío por correo no está configurado (falta SMTP_SERVIDOR en el .env)."
        if envio.mandar(Aviso.prueba([para]), esperas=()):
            return None
        return f"No se pudo enviar el correo de prueba: {envio.ultimo_error}."

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
                valores = _valores(motor, n["hora"])
                self._alerta(*self._texto_abierta(motor, n, valores), **self._datos_alarma(motor, n, valores))
            elif n["evento"] == "alarma_cerrada":
                self._cierre(*self._texto_cerrada(motor, n), self._terminar("alarma", n["hora"]))
            elif n["evento"] == "aviso_anticipado" and self.con_anticipacion:
                self._alerta(*self._texto_aviso(motor, n), **self._datos_aviso(n))
            elif n["evento"] == "aviso_terminado":
                self._terminar(f"aviso:{n['tipo']}", n["hora"])
            elif n["evento"] == "fuga_abierta":
                self._alerta(*self._texto_fuga(n), **self._datos_fuga(n))
            elif n["evento"] == "fuga_cerrada":
                self._cierre(*self._texto_fuga_cerrada(motor, n), self._terminar("fuga", n["hora"]))
            elif n["evento"] == "deriva":
                self.avisar(*self._texto_deriva(n))
        if self.con_riesgo:
            self._revisar_riesgo(motor, sensores, ahora, horas_nuevas)
        if self.hora_resumen >= 0:
            # al arrancar no se manda: solo cuando el procesamiento pasa por la hora del resumen
            horas = pd.date_range(anterior, ahora, freq="1h")[1:] if anterior is not None else []
            if any(h.hour == self.hora_resumen for h in horas):
                self.avisar(*self._texto_resumen(motor, sensores, ahora))

    @staticmethod
    def _tipo_alarma(motor, n):
        """Tipo sugerido de la alarma, que puede seguir abierta o haberse cerrado en el mismo ciclo."""
        a = motor.alarma_abierta
        if a is not None and a["id"] == n["id"]:
            return carga.TIPOS_EVENTO.get(a["tipos"].most_common(1)[0][0], "?") if a["tipos"] else "?"
        return next((x["tipo_sugerido"] for x in motor.alarmas if x["id"] == n["id"]), "?")

    @staticmethod
    def _orden(n, sensores):
        """Los sensores en alarma, primero los de más probabilidad de evento."""
        return sorted(n["sensores"], key=lambda x: (-(sensores.get(x, {}).get("p_evento") or 0), x))

    def _datos_alarma(self, motor, n, sensores):
        tipo = self._tipo_alarma(motor, n)
        orden = self._orden(n, sensores)
        probs = [sensores.get(x, {}).get("p_evento") for x in orden]
        valores = "; ".join(f"{x}: " + ", ".join(f"{NOMBRE[p]} {_num(sensores.get(x, {}).get(p))}{UNIDAD[p]}"
                                                 for p in ["CL2", "TURB", "PH"]) for x in orden[:6])
        return {"grupo": "alarma", "inicio": n["hora"], "tipo": "alarma", "evento": tipo,
                "titulo": f"{TIPOS.get(tipo, 'Evento sin clasificar')} en {_nodos(orden, 3)}",
                "lugar": ("Sensor " if len(orden) == 1 else "Sensores ") + ", ".join(orden), "nodos": orden,
                "probabilidad": max((p for p in probs if p is not None), default=None), "antelacion_h": 0,
                "parametros": valores, "accion": ACCION_ALARMA.get(tipo, ACCION_ALARMA["?"])}

    def _datos_fuga(self, n):
        tramo = str(n["tramo"])
        return {"grupo": "fuga", "inicio": n["hora"], "tipo": "fuga", "evento": "fuga",
                "titulo": f"Posible fuga en el tramo {tramo}", "lugar": f"Tramo {tramo}",
                "nodos": [x.strip() for x in tramo.replace("–", ",").split(",") if x.strip()],
                "probabilidad": n["probabilidad"], "antelacion_h": 0,
                "parametros": f"La fuente entrega {_num(n['caudal_residuo'], 1)} L/s más de lo esperado; "
                              f"tramo más probable con {_pct(n['p_tramo'])}",
                "accion": ACCION_ALARMA["fuga"]}

    def _datos_aviso(self, n):
        tipo = n["tipo"]
        nombre = TIPOS.get(tipo, "Evento fuera de lo normal") if tipo != "anomalia" else "Operación fuera de lo normal"
        planta = tipo in EMPIEZAN_EN_LA_FUENTE
        return {"grupo": f"aviso:{tipo}", "inicio": n["hora"], "tipo": "aviso", "evento": tipo,
                "titulo": f"Posible {_minus(nombre)} en las próximas 24 h",
                "lugar": "Empezaría en la planta (J280)" if planta else "Toda la red",
                "nodos": ["J280"] if planta else [], "probabilidad": n["probabilidad"], "antelacion_h": 24,
                "parametros": f"Señal: {SENALES.get(tipo, SENALES['anomalia'])}",
                "accion": ACCION_AVISO.get(tipo, ACCION_AVISO["anomalia"])}

    def _texto_abierta(self, motor, n, sensores):
        tipo = self._tipo_alarma(motor, n)
        tipo_txt = TIPOS.get(tipo, "Evento sin clasificar")
        plural = "es" if len(n["sensores"]) > 1 else ""
        lineas = [f"🔴 <b>Alarma #{n['id']}: {html.escape(tipo_txt)}</b> (tipo sugerido)",
                  f"{_fecha(n['hora'])} · {len(n['sensores'])} sensor{plural} en alarma"]
        orden = self._orden(n, sensores)
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
        asunto = f"Alerta roja · Alarma #{n['id']}: {_minus(tipo_txt)} en {_nodos(orden)}"
        return "\n".join(lineas), "rojo", asunto

    def _texto_fuga(self, n):
        lineas = [f"🔴 <b>Posible fuga #{n['id']}</b>",
                  f"{_fecha(n['hora'])} · probabilidad {_pct(n['probabilidad'])} (umbral {_pct(n['umbral'])})",
                  f"Tramo más probable: <b>{html.escape(str(n['tramo']))}</b> ({_pct(n['p_tramo'])})",
                  f"La fuente entrega {_num(n['caudal_residuo'], 1)} L/s más de lo esperado a esta hora.",
                  f"<b>Qué hacer:</b> {ACCION_ALARMA['fuga']}.",
                  f"{self.url}/#/fugas"]
        return "\n".join(lineas), "rojo", f"Alerta roja · Posible fuga #{n['id']} en el tramo {n['tramo']}"

    def _texto_fuga_cerrada(self, motor, n):
        a = next((x for x in motor.fugas if x["id"] == n["id"]), None)
        if a is None:
            return f"🟢 <b>Fuga #{n['id']}: alarma cerrada</b> · {_fecha(n['hora'])}", "rojo", None
        return (f"🟢 <b>Fuga #{a['id']}: alarma cerrada</b> · tramo {html.escape(str(a['tramo']))}\n"
                f"De {_fecha(a['inicio'])} a {_fecha(a['fin'])} ({a['horas']} h) · hasta "
                f"{_num(a['caudal_extra_Ls'], 1)} L/s de más"), "rojo", f"Fuga #{a['id']} cerrada · tramo {a['tramo']}"

    def _texto_deriva(self, n):
        cols = " · ".join(f"{html.escape(c)} (PSI {_num(v)})" for c, v in n["columnas"][:8])
        asunto = "Alerta amarilla · Los datos se apartan de lo habitual: " + ", ".join(
            str(c) for c, _ in n["columnas"][:3]) + (" y otros" if len(n["columnas"]) > 3 else "")
        return (f"🟠 <b>Los datos se apartan de los del entrenamiento</b> · {_fecha(n['hora'])}\n"
                f"Última semana: {cols}\n"
                "<b>Qué hacer:</b> revisar y calibrar esos sensores; si las lecturas están bien, la operación "
                "cambió y conviene volver a entrenar los modelos (Modelo_calidad_agua/herramientas/reentrenar.py)."), \
            "amarillo", asunto

    def _texto_cerrada(self, motor, n):
        a = next((x for x in motor.alarmas if x["id"] == n["id"]), None)
        if a is None:
            return f"🟢 <b>Alarma #{n['id']} cerrada</b> · {_fecha(n['hora'])}", "rojo", None
        nombre = TIPOS.get(a["tipo_sugerido"], a["tipo_sugerido"])
        return (f"🟢 <b>Alarma #{a['id']} cerrada</b> · {html.escape(nombre)}\n"
                f"De {_fecha(a['inicio'])} a {_fecha(a['fin'])} ({a['horas']} h) · sensores: {a['sensores']}"), \
            "rojo", f"Alarma #{a['id']} cerrada · {_minus(nombre)} · {a['sensores']}"

    def _texto_aviso(self, motor, n):
        tipo = n["tipo"]
        nombre = TIPOS.get(tipo, "Evento fuera de lo normal") if tipo != "anomalia" else "Operación fuera de lo normal"
        lineas = [f"🟡 <b>Aviso anticipado: posible {html.escape(_minus(nombre))} en las próximas 24 h</b>",
                  f"{_fecha(n['hora'])} · probabilidad {_pct(n['probabilidad'])} (umbral {_pct(n['umbral'])})",
                  f"Señal: {SENALES.get(tipo, SENALES['anomalia'])}."]
        llegadas = _llegada(motor, set()) if tipo in EMPIEZAN_EN_LA_FUENTE else []
        if llegadas:
            lineas.append("Si ocurre, empieza en la planta (J280) y llegaría a los sensores en: "
                          + _por_horas(llegadas))
        lineas.append(f"<b>Qué hacer:</b> {ACCION_AVISO.get(tipo, ACCION_AVISO['anomalia'])}.")
        lineas.append(self.url)
        donde = " · empezaría en la planta (J280)" if tipo in EMPIEZAN_EN_LA_FUENTE else " · toda la red"
        asunto = f"Alerta amarilla · Posible {_minus(nombre)} en las próximas 24 h{donde}"
        return "\n".join(lineas), "amarillo", asunto

    def _revisar_riesgo(self, motor, sensores, ahora, horas_nuevas=1):
        nuevos = []
        tipicos = getattr(motor.modelos, "tipicos", {}) or {}
        for nodo, s in sensores.items():
            for par in ["CL2", "TURB", "PH"]:
                # un sensor que en operación normal ya está fuera de la norma (el cloro bajo al final
                # de la red) no es un riesgo nuevo cada día: el tablero lo muestra, pero no se avisa
                if fuera_de_norma(par, tipicos.get((par, nodo))):
                    continue
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
                        self._terminar(f"riesgo:{nodo}:{par}", ahora)
        nuevos, enlace = self._guardar_riesgos(nuevos, ahora)
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
            nodos = list(dict.fromkeys(nodo for nodo, *_ in nuevos))
            pars = ", ".join(dict.fromkeys(NOMBRE[par] for _, par, *_ in nuevos))
            self.avisar("\n".join(lineas), "amarillo", f"Alerta amarilla · Riesgo en 24 h: {pars} en {_nodos(nodos)}",
                        enlace=enlace)

    def _guardar_riesgos(self, nuevos, ahora):
        """Una alerta por sensor y parámetro. Devuelve los que de verdad son nuevos (al reiniciar el
        servicio, los que ya estaban activos no se vuelven a avisar) y el enlace del correo."""
        if self.gestion is None or not nuevos:
            return nuevos, None
        quedan, ids = [], []
        for nodo, par, v, limite in nuevos:
            try:
                uid, nueva = self.gestion.abrir(
                    grupo=f"riesgo:{nodo}:{par}", inicio=ahora, tipo="riesgo", nivel="amarillo", evento=par,
                    titulo=f"Riesgo en 24 h: {NOMBRE[par]} fuera de norma en {nodo}", lugar=f"Sensor {nodo}",
                    nodos=[nodo], antelacion_h=24,
                    parametros=f"Pronóstico de {NOMBRE[par]} a 24 h: {_num(v)}{UNIDAD[par]} ({limite})",
                    accion=ACCION_RIESGO[(par, limite.split()[0])])
            except Exception as e:
                print(f"No se pudo guardar la alerta: {e}", flush=True)
                quedan.append((nodo, par, v, limite))
                continue
            if nueva:
                quedan.append((nodo, par, v, limite))
                ids.append(uid)
        enlace = f"{self.url}/#/alertas/{ids[0]}" if len(ids) == 1 else f"{self.url}/#/alertas"
        return quedan, enlace

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
            activos = [_minus(TIPOS.get(a["tipo"], "anomalía")) for a in motor.avisos_abiertos.values()]
            lineas.append("Avisos anticipados activos: " + (", ".join(activos) if activos else "ninguno"))
        lineas.append(self.url)
        cuantas = f"{len(alarmas)} alarma{'s' if len(alarmas) != 1 else ''} en 24 h"
        return "\n".join(lineas), "resumen", f"Resumen diario · {pd.Timestamp(ahora):%d/%m/%Y} · {cuantas}"


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
        canal = next((c for c in canales_desde_entorno() if c.nombre == "telegram"), None)
        if canal is None:
            raise SystemExit("Faltan TELEGRAM_TOKEN y TELEGRAM_CHAT_ID.")
        canal.enviar(Aviso("✅ <b>Prueba</b> del servicio de monitoreo de calidad de agua. "
                           "Las alertas llegan a este chat."))
        print("Mensaje enviado.")
    else:
        ap.print_help()
