"""Alertas (alertas.py): textos, riesgo en 24 h, resumen diario, canales y reintentos."""

import time

import pandas as pd
import pytest

from conftest import INICIO, ModelosFalsos, lecturas
from monitoreo import alertas
from monitoreo.motor import Motor


class CanalLista:
    nombre = "prueba"

    def __init__(self, fallar=0):
        self.mensajes, self.fallar = [], fallar

    def enviar(self, texto):
        if self.fallar:
            self.fallar -= 1
            raise ConnectionError("sin red")
        self.mensajes.append(texto)


def hora(k):
    return INICIO + pd.Timedelta(hours=k)


def correr(motor, al, horas):
    """Alimenta el motor hora por hora y revisa las alertas después de cada ciclo."""
    lec = lecturas(horas)
    for k in range(horas):
        for x in lec[k * 4:(k + 1) * 4]:
            motor.recibir(x["fecha"], x["valores"])
        al.revisar(motor, motor.procesar())


@pytest.fixture
def al(monkeypatch):
    monkeypatch.delenv("TELEGRAM_TOKEN", raising=False)
    a = alertas.Alertas(canal=CanalLista())
    a.textos = []
    a.avisar = a.textos.append                  # sin hilo: los mensajes quedan en la lista
    return a


def test_llegadas_agrupadas_por_hora():
    ll = [("J439", 1.0), ("J224", 2.0), ("J69", 2.0), ("J1", 2.4), ("J144", 15.0)]
    assert alertas._por_horas(ll) == "~1 h: J439 · ~2 h: J224, J69, J1 · ~15 h: J144"
    assert alertas._por_horas(ll, max_sensores=2) == "~1 h: J439 · ~2 h: J224, J69 y 1 más · ~15 h: J144"


def test_formatos_de_fecha_numero_y_norma():
    assert alertas._fecha("2026-09-02 11:00:00") == "02/09/2026 11:00:00"
    assert alertas._num(0.456) == "0,46" and alertas._num(None) == "—" and alertas._num(float("nan")) == "—"
    assert alertas.fuera_de_norma("CL2", 0.2) == "mínimo 0,3"
    assert alertas.fuera_de_norma("CL2", 1.2) == "máximo 1,0"
    assert alertas.fuera_de_norma("TURB", 6.0) == "máximo 5"
    assert alertas.fuera_de_norma("PH", 9.0) == "máximo 8,5"
    assert alertas.fuera_de_norma("CL2", 0.5) is None and alertas.fuera_de_norma("TURB", None) is None


def test_mensajes_de_alarma_abierta_y_cerrada(cfg, al):
    alto = {hora(k) for k in (5, 6, 7)}
    motor = Motor(cfg, ModelosFalsos(p_evento=lambda h, n: 0.95 if (n == "J10" and h in alto) else 0.1),
                  registrar=False)
    correr(motor, al, 12)
    abierta = next(t for t in al.textos if "Alarma #1:" in t)
    assert "Contaminación" in abierta and "01/05/2026 06:00:00" in abierta
    assert "<b>J10</b> (95 %): cloro" in abierta and "/#/sensor/J10" in abierta
    assert "Evento local" in abierta and "<b>Qué hacer:</b> tomar muestras" in abierta
    cerrada = next(t for t in al.textos if "cerrada" in t)
    assert "De 01/05/2026 06:00:00 a 01/05/2026 07:00:00 (2 h)" in cerrada


def test_alarma_de_la_planta_dice_a_donde_no_ha_llegado(cfg, al):
    alto = {hora(k) for k in (5, 6, 7)}
    modelos = ModelosFalsos(p_evento=lambda h, n: 0.95 if (n == "J280" and h in alto) else 0.1,
                            p_anticipa=lambda h, k: 0.1, tipo_evento=2)
    motor = Motor(cfg, modelos, registrar=False)
    correr(motor, al, 9)
    abierta = next(t for t in al.textos if "Alarma #1:" in t)
    assert "Falla de cloración" in abierta
    # retrasos del modelo de anticipación: J10 a 2 h y J20 a 9 h de la planta (conftest)
    linea = next(x for x in abierta.split("\n") if "todavía no llega" in x)
    assert linea.endswith("planta): ~2 h: J10 · ~9 h: J20") and "J280" not in linea
    assert abierta.endswith("/#/sensor/J280")                # enlace al sensor con más probabilidad
    assert "<b>Qué hacer:</b> revisar de inmediato la dosificación de cloro" in abierta


def test_alarma_sin_modelo_de_anticipacion_no_inventa_llegadas(cfg, al):
    alto = {hora(k) for k in (5, 6, 7)}
    motor = Motor(cfg, ModelosFalsos(p_evento=lambda h, n: 0.95 if (n == "J280" and h in alto) else 0.1,
                                     tipo_evento=3), registrar=False)
    correr(motor, al, 9)
    abierta = next(t for t in al.textos if "Alarma #1:" in t)
    assert "Turbidez en la fuente" in abierta and "todavía no llega" not in abierta
    assert "<b>Qué hacer:</b> revisar la planta (coagulación y filtros)" in abierta


def test_alarma_que_abre_y_cierra_en_el_mismo_ciclo(cfg, al):
    alto = {hora(k) for k in (5, 6)}
    motor = Motor(cfg, ModelosFalsos(p_evento=lambda h, n: 0.95 if (n == "J10" and h in alto) else 0.1),
                  registrar=False)
    for x in lecturas(12):
        motor.recibir(x["fecha"], x["valores"])
    al.revisar(motor, motor.procesar())                   # todas las horas de una vez
    assert len(al.textos) == 2 and "Contaminación" in al.textos[0]


def test_riesgo_en_24h_se_avisa_una_vez_por_episodio(cfg, al):
    modelos = ModelosFalsos(pronostico_24h={"J20": {"CL2": 0.2}})
    motor = Motor(cfg, modelos, registrar=False)
    correr(motor, al, 7)
    riesgo = [t for t in al.textos if "Riesgo en 24 h" in t]
    assert len(riesgo) == 1 and "<b>J20</b>: cloro 0,20 mg/L (mínimo 0,3)" in riesgo[0]
    assert "<b>Qué hacer:</b> revisar la dosis de cloro en la planta o la recloración" in riesgo[0]
    modelos.pronostico_24h = {}                            # el pronóstico vuelve a la norma…
    correr(motor, al, 7 + alertas.HORAS_FIN_RIESGO)        # (las horas ya procesadas se ignoran)
    assert ("J20", "CL2") not in al.riesgo                 # …y el episodio termina
    modelos.pronostico_24h = {"J20": {"CL2": 0.2}}
    correr(motor, al, 9 + alertas.HORAS_FIN_RIESGO)
    assert len([t for t in al.textos if "Riesgo en 24 h" in t]) == 2


def test_resumen_diario_al_pasar_por_la_hora(cfg, al):
    al.hora_resumen = 8
    motor = Motor(cfg, ModelosFalsos(pronostico_24h={"J10": {"PH": 9.0}}), registrar=False)
    correr(motor, al, 12)
    resumen = [t for t in al.textos if "Resumen" in t]
    assert len(resumen) == 1 and "01/05/2026 08:00:00" in resumen[0]
    assert "Con riesgo en 24 h: J10 (pH)" in resumen[0] and "Fuera de norma ahora: ninguno" in resumen[0]


def test_sin_horas_procesadas_no_hay_alertas(cfg, al):
    al.revisar(Motor(cfg, ModelosFalsos(), registrar=False), [])
    assert al.textos == []


def test_envio_en_segundo_plano_con_reintentos(monkeypatch):
    esperar = time.sleep
    monkeypatch.setattr(alertas.time, "sleep", lambda s: esperar(0.001))     # sin los 5, 10, 20 s
    canal = CanalLista(fallar=2)
    a = alertas.Alertas(canal=canal)
    a.avisar("hola")
    for _ in range(200):
        if a.enviadas:
            break
        esperar(0.01)
    assert canal.mensajes == ["hola"] and a.enviadas == 1 and a.ultimo_error == "sin red"
    malo = alertas.Alertas(canal=CanalLista(fallar=10))
    malo.avisar("no llega")
    for _ in range(200):
        if malo.fallidas:
            break
        esperar(0.01)
    assert malo.fallidas == 1 and malo.estado()["fallidas"] == 1


def test_canal_segun_variables_de_entorno(monkeypatch):
    monkeypatch.delenv("TELEGRAM_TOKEN", raising=False)
    assert alertas.canal_desde_entorno().nombre == "consola"
    monkeypatch.setenv("TELEGRAM_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "11, 22")
    canal = alertas.canal_desde_entorno()
    assert canal.nombre == "telegram" and canal.chats == ["11", "22"]
    monkeypatch.setenv("ALERTAS_RESUMEN_HORA", "-1")
    monkeypatch.setenv("ALERTAS_RIESGO", "0")
    e = alertas.Alertas(canal=CanalLista()).estado()
    assert e["resumen_hora"] is None and e["riesgo_24h"] is False


def test_telegram_manda_a_cada_chat_y_avisa_si_falla(monkeypatch):
    enviados = []

    class Respuesta:
        def __init__(self, codigo):
            self.status_code, self.text = codigo, "error de prueba"

    monkeypatch.setattr(alertas.requests, "post", lambda url, json, timeout: enviados.append(json) or Respuesta(200))
    alertas.CanalTelegram("tok", ["1", "2"]).enviar("<b>hola</b>")
    assert [e["chat_id"] for e in enviados] == ["1", "2"] and enviados[0]["parse_mode"] == "HTML"
    monkeypatch.setattr(alertas.requests, "post", lambda url, json, timeout: Respuesta(400))
    with pytest.raises(RuntimeError, match="400"):
        alertas.CanalTelegram("tok", ["1"]).enviar("hola")


def test_consola_quita_el_formato(capsys):
    alertas.CanalConsola().enviar("<b>Alarma</b> 🔴")
    assert capsys.readouterr().out.strip() == "[alerta] Alarma 🔴"


def test_llamadas_sin_horas_nuevas_no_cuentan_para_cerrar_el_riesgo(cfg, al):
    """El servicio llama a revisar() cada segundo: solo las horas procesadas cuentan."""
    modelos = ModelosFalsos(pronostico_24h={"J20": {"CL2": 0.2}})
    motor = Motor(cfg, modelos, registrar=False)
    correr(motor, al, 7)
    modelos.pronostico_24h = {}
    correr(motor, al, 8)                                   # una hora con el pronóstico en norma
    for _ in range(30):                                    # 30 ciclos sin datos nuevos
        al.revisar(motor, motor.procesar())
    assert al.riesgo[("J20", "CL2")] == 1


def test_aviso_anticipado_con_llegada_a_los_sensores(cfg, al):
    alto = {hora(k) for k in (5, 6)}
    motor = Motor(cfg, ModelosFalsos(p_anticipa=lambda h, k: 0.82 if h in alto else 0.1), registrar=False)
    correr(motor, al, 9)
    avisos = [t for t in al.textos if "Aviso anticipado" in t]
    assert len(avisos) == 1
    assert "posible turbidez en la fuente en las próximas 24 h" in avisos[0]
    assert "probabilidad 82 % (umbral 50 %)" in avisos[0] and "aguacero" in avisos[0]
    assert "~2 h: J10 · ~9 h: J20" in avisos[0] and "J280" not in avisos[0].split("llegaría")[1]
    assert "<b>Qué hacer:</b> preparar la planta para la crecida" in avisos[0]


def test_avisos_anticipados_se_pueden_apagar(cfg, al, monkeypatch):
    monkeypatch.setenv("ALERTAS_ANTICIPACION", "0")
    a = alertas.Alertas(canal=CanalLista())
    a.textos = []
    a.avisar = a.textos.append
    motor = Motor(cfg, ModelosFalsos(p_anticipa=lambda h, k: 0.9), registrar=False)
    correr(motor, a, 8)
    assert not [t for t in a.textos if "Aviso anticipado" in t]
    a.hora_resumen = 10
    correr(motor, a, 12)
    assert "Avisos anticipados activos: turbidez en la fuente" in [t for t in a.textos if "Resumen" in t][0]


def test_mensajes_de_fuga_con_tramo(cfg, al):
    alto = {hora(k) for k in (5, 6, 7)}
    motor = Motor(cfg, ModelosFalsos(p_fuga=lambda h: 0.9 if h in alto else 0.1, tramo="J10 – J20"), registrar=False)
    correr(motor, al, 12)
    abierta = next(t for t in al.textos if "Posible fuga #1" in t)
    assert "01/05/2026 06:00:00" in abierta and "probabilidad 90 % (umbral 50 %)" in abierta
    assert "<b>J10 – J20</b> (80 %)" in abierta and "3,6 L/s más" in abierta
    assert "<b>Qué hacer:</b> recorrer el tramo" in abierta and "/#/fugas" in abierta
    cerrada = next(t for t in al.textos if "Fuga #1: alarma cerrada" in t)
    assert "tramo J10 – J20" in cerrada and "(2 h)" in cerrada
