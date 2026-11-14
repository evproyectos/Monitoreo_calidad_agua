"""Resiliencia (RNF-002): reintentos con espera exponencial, cola persistente y base de datos caída."""

import io
import json

import pandas as pd
import pytest
import requests

from conftest import INICIO, ModelosFalsos, configuracion, lecturas, tabla_lecturas
from monitoreo import cliente_datos, pronostico_lluvia
from monitoreo import gestion as ge
from monitoreo import servicio as srv
from monitoreo.cursor import Cursor
from monitoreo.motor import DIAS_LLUVIA, Motor, Registro
from monitoreo.reintentos import esperas, reintentar

H = pd.Timedelta(hours=1)


# ---------------------------------------------------------------------------- reintentos
def test_esperas_exponenciales():
    assert esperas() == [1.0, 2.0, 4.0]                       # 3 reintentos
    assert esperas(6, 1, 2, maximo_s=10) == [1, 2, 4, 8, 10]


def test_reintentar_hasta_que_funcione():
    intentos, pausas = [], []

    def falla_dos_veces():
        intentos.append(1)
        if len(intentos) < 3:
            raise ConnectionError("sin red")
        return "listo"
    assert reintentar(falla_dos_veces, dormir=pausas.append, avisar=lambda m: None) == "listo"
    assert pausas == [1.0, 2.0]


def test_reintentar_se_rinde_y_no_reintenta_lo_que_no_sirve():
    pausas = []
    with pytest.raises(ConnectionError):
        reintentar(lambda: (_ for _ in ()).throw(ConnectionError("x")), dormir=pausas.append, avisar=lambda m: None)
    assert pausas == [1.0, 2.0, 4.0]                          # 4 intentos en total
    pausas.clear()
    with pytest.raises(ValueError):
        reintentar(lambda: (_ for _ in ()).throw(ValueError("x")), reintentable=lambda e: False,
                   dormir=pausas.append)
    assert pausas == []


class Respuesta:
    def __init__(self, codigo=200, datos=()):
        self.status_code, self.datos = codigo, list(datos)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}", response=self)

    def json(self):
        return self.datos


def cliente_con(respuestas):
    pausas = []
    c = cliente_datos.ClienteDatos("http://datos", dormir=pausas.append)
    pendientes = list(respuestas)

    def get(url, params=None, timeout=None):
        r = pendientes.pop(0)
        if isinstance(r, Exception):
            raise r
        return r
    c.s.get = get
    return c, pausas


def test_api_de_datos_reintenta_caidas_y_errores_5xx():
    c, pausas = cliente_con([requests.ConnectionError("caída"), Respuesta(503), Respuesta(200, [{"fecha": "x"}])])
    assert c.lecturas_desde(None) == [{"fecha": "x"}]
    assert pausas == [0.5, 1.0]


def test_api_de_datos_no_reintenta_un_pedido_mal_hecho():
    c, pausas = cliente_con([Respuesta(404)])
    with pytest.raises(requests.HTTPError):
        c.lecturas_desde(None)
    assert pausas == []


def test_open_meteo_reintenta_y_si_falla_sigue_con_el_ultimo(monkeypatch):
    llamadas = []
    respuesta = {"hourly": {"time": ["2026-05-01T00:00", "2026-05-01T01:00"],
                            **{f"precipitation_{m}": [1.0, 2.0] for m in ("a", "b")}}}

    def urlopen(url, timeout):
        llamadas.append(url)
        if len(llamadas) <= 2:
            raise OSError("sin red")
        return io.BytesIO(json.dumps(respuesta).encode())
    monkeypatch.setattr(pronostico_lluvia.urllib.request, "urlopen", urlopen)
    pausas = []
    p = pronostico_lluvia.PronosticoOpenMeteo(modelos=["a", "b"], dormir=pausas.append)
    p._actualizar()
    assert len(llamadas) == 3 and pausas == [1.0, 2.0] and p.error is None
    assert list(p.serie) == [1.0, 2.0]

    monkeypatch.setattr(pronostico_lluvia.urllib.request, "urlopen",
                        lambda url, timeout: (llamadas.append(url), (_ for _ in ()).throw(OSError("caída")))[1])
    p.consultado = 0                                          # ya toca actualizar
    llamadas.clear()
    p._actualizar()
    assert len(llamadas) == 4 and "caída" in p.error and list(p.serie) == [1.0, 2.0]   # sigue con el último
    llamadas.clear()
    p._actualizar()                                           # no vuelve a probar enseguida (10 min)
    assert llamadas == []


# ---------------------------------------------------------------------------- base de datos caída
class BaseQueFalla:
    def __init__(self, fallas):
        self.fallas, self.escritas = fallas, []

    def escribir(self, tabla, filas):
        if self.fallas:
            self.fallas -= 1
            raise ConnectionError("la base no responde")
        self.escritas.append(list(filas))


def test_base_caida_las_filas_esperan_y_se_escriben_al_volver(tmp_path, capsys):
    base = BaseQueFalla(fallas=2)
    r = Registro(tmp_path / "deteccion.csv", ["fecha", "p"], base)
    for k in range(3):
        r.escribir([{"fecha": f"h{k}", "p": k}])
    assert base.escritas == [[{"fecha": "h0", "p": 0}, {"fecha": "h1", "p": 1}, {"fecha": "h2", "p": 2}]]
    assert r.pendientes == [] and r.error_base is None
    r.f.close()
    assert len(pd.read_csv(tmp_path / "deteccion.csv")) == 3   # el CSV las tiene todas desde el principio
    salida = capsys.readouterr().out
    assert salida.count("No se pudo escribir") == 1 and "3 filas de deteccion escritas" in salida


# ---------------------------------------------------------------------------- cola persistente
def test_cursor(tmp_path):
    g = ge.GestionAlertas(f"sqlite:///{tmp_path}/g.db")
    c = Cursor(g.motor)
    assert c.leer() is None
    c.guardar(pd.Timestamp("2026-05-01 05:00"))
    c.guardar(pd.Timestamp("2026-05-01 06:00"))
    assert Cursor(g.motor).leer() == pd.Timestamp("2026-05-01 06:00")
    g.motor.dispose()


class Fuente:
    """API de datos falsa: guarda las lecturas que 'mandan los sensores'; puede estar caída."""

    def __init__(self, todas):
        self.todas, self.hasta, self.caida, self.pedidos = todas, 0, False, []

    def llegan(self, horas):                                  # los sensores mandan `horas` horas más
        self.hasta += 4 * horas

    def lecturas_desde(self, desde=None):
        if self.caida:
            raise ConnectionError("la API de datos no responde")
        self.pedidos.append(desde)
        return [x for x in self.todas[:self.hasta] if desde is None or pd.Timestamp(x["fecha"]) >= desde]


@pytest.fixture
def servicio(tmp_path, monkeypatch):
    fuente = Fuente(lecturas(30))
    monkeypatch.setattr(srv, "Motor", lambda cfg: Motor(cfg, ModelosFalsos(), registrar=False))
    monkeypatch.setattr(srv, "ClienteDatos", lambda url: fuente)
    g = ge.GestionAlertas(f"sqlite:///{tmp_path}/g.db")

    def nuevo():
        return srv.Servicio(configuracion(tmp_path), None, g)
    yield nuevo, fuente
    g.motor.dispose()


def horas_procesadas(s):
    return sorted(pd.concat(s.motor.deteccion)["fecha"].unique()) if s.motor.deteccion else []


def test_corte_de_mas_de_dos_horas_no_pierde_ninguna_hora(servicio):
    nuevo, fuente = servicio
    s = nuevo()
    fuente.llegan(8)
    s.paso()
    hasta_ahora = s.motor.ultima_hora_procesada
    fuente.caida = True
    for _ in range(3):                                        # la API cae ~3 h y los sensores siguen
        fuente.llegan(1)
        with pytest.raises(ConnectionError):
            s.paso()
    assert s.motor.ultima_hora_procesada == hasta_ahora       # mientras tanto no se procesa nada
    fuente.caida = False
    s.paso()
    horas = horas_procesadas(s)
    assert s.motor.ultima_hora_procesada == hasta_ahora + 3 * H
    assert horas == list(pd.date_range(horas[0], horas[-1], freq="1h"))   # en orden y sin huecos


def test_reinicio_sigue_despues_del_cursor(servicio):
    nuevo, fuente = servicio
    s = nuevo()
    fuente.llegan(12)
    s.paso()
    cursor = s.motor.ultima_hora_procesada
    assert s.cursor.leer() == cursor
    fuente.llegan(5)                                          # llegan datos mientras el servicio está apagado
    s2 = nuevo()                                              # reinicio: motor nuevo, misma base
    fuente.pedidos.clear()
    s2.paso()
    historia = max(pd.Timedelta(hours=s2.cfg.historia_h), pd.Timedelta(days=DIAS_LLUVIA))   # y la lluvia de 30 días
    assert fuente.pedidos == [cursor - historia + pd.Timedelta(minutes=15)]   # no toda la historia
    assert s2.retomado["despues_de"] == str(cursor)
    horas = horas_procesadas(s2)
    assert horas[0] == cursor + H                             # no se repite ninguna hora ya procesada
    assert s2.motor.ultima_hora_procesada == cursor + 5 * H


def test_si_la_fuente_empezo_de_nuevo_se_procesa_desde_el_principio(servicio):
    nuevo, fuente = servicio
    s = nuevo()
    s.cursor.guardar(INICIO + pd.Timedelta(days=30))          # cursor de una corrida anterior, más adelante
    fuente.llegan(8)
    s.paso()
    assert s.retomado is None and fuente.pedidos[-1] is None
    assert horas_procesadas(s)[0] < INICIO + pd.Timedelta(days=1)
    assert s.cursor.leer() == s.motor.ultima_hora_procesada  # y el cursor se corrige


def test_al_reanudar_se_rearman_la_lluvia_de_30_dias_y_las_semanas_de_fugas_y_deriva(cfg):
    from calidad_agua import deriva
    modelos = ModelosFalsos(p_anticipa=lambda hora, tipo: 0.1, p_fuga=lambda hora: 0.1)
    modelos.deriva = {"referencia": deriva.referencia(tabla_lecturas(80).resample("1h").mean()), "periodo": "x"}
    vistas = []
    detectar = modelos.detectar_fugas
    modelos.detectar_fugas = lambda hd, horas: (vistas.append(hd.copy()), detectar(hd, horas))[1]
    motor = Motor(cfg, modelos, registrar=False)
    todas = lecturas(33 * 24)
    for x in todas[:4 * 4 * 24]:                              # llovió los primeros 4 días (cada 15 min)
        x["valores"]["lluvia_mm_h"] = 2.0
    cursor = pd.Timestamp(todas[-1]["fecha"]).floor("h") - 3 * H
    motor.reanudar(cursor)                                    # reinicio: ya se procesó hasta el cursor
    for x in todas:
        motor.recibir(x["fecha"], x["valores"])
    motor.procesar()
    assert motor.lluvia_horaria.index.min() < cursor - pd.Timedelta(days=25)   # no solo `historia_h` horas
    assert float(pd.Series(modelos.lluvia_mes).max()) > 0     # la lluvia de hace 29-30 días sí cuenta
    hd = vistas[-1]                                           # las fugas ven la semana anterior completa
    assert len(vistas) == 2                                   # (antes, el repaso de las horas ya procesadas)
    assert hd.index.min() <= cursor - pd.Timedelta(days=8) and hd.index.is_unique
    assert hd.index.max() == cursor + 2 * H
    assert motor.historia_deriva.index.min() <= cursor - pd.Timedelta(days=6)   # la semana de la deriva
    # la última revisión (la del repaso) ya vio la semana completa
    assert pd.Timestamp(motor.ultima_deriva["desde"]) <= cursor - pd.Timedelta(days=6)


def test_al_reanudar_el_dashboard_tiene_enseguida_el_estado_de_antes(cfg):
    """Sin lecturas nuevas después del reinicio, el dashboard muestra lo mismo que antes (no queda
    vacío hasta la hora siguiente) y no se avisa ni se registra otra vez lo que ya se procesó."""
    def modelos():
        return ModelosFalsos(p_evento=lambda h, n: 0.95 if n == "J10" and h >= INICIO + 100 * H else 0.1,
                             p_anticipa=lambda hora, tipo: 0.2, p_fuga=lambda hora: 0.3)
    todas = lecturas(10 * 24)
    antes = Motor(cfg, modelos(), registrar=False)
    for x in todas:
        antes.recibir(x["fecha"], x["valores"])
    antes.procesar()
    cursor = antes.ultima_hora_procesada
    assert antes.alarma_abierta is not None

    despues = Motor(cfg, modelos(), registrar=False)          # reinicio: motor nuevo
    despues.reanudar(cursor)
    for x in todas:                                           # la historia que pide el servicio; nada nuevo
        despues.recibir(x["fecha"], x["valores"])
    assert despues.procesar() == []                           # nada que avisar de nuevo
    assert despues.resumen_sensores() == antes.resumen_sensores()
    assert despues.series_red(168) == antes.series_red(168)
    assert despues.alarma_abierta["inicio"] == antes.alarma_abierta["inicio"]
    assert despues.resumen_anticipacion() == antes.resumen_anticipacion()
    assert despues.resumen_fugas()["serie"] == antes.resumen_fugas()["serie"]
    assert despues.deteccion == [] and despues.ultima_hora_procesada == cursor   # no se repite ninguna hora


# ---------------------------------------------------------------------------- datos que no llegan
def test_se_avisa_cuando_dejan_de_llegar_datos_y_cuando_vuelven(servicio):
    nuevo, fuente = servicio
    s = nuevo()
    avisos = []
    s.alertas.avisar = lambda texto, nivel="rojo", asunto=None, enlace=None: avisos.append((texto, nivel, asunto))
    t0 = s._vista_t
    fuente.llegan(8)
    s.paso()
    s.vigilar_datos(t0)
    fuente.caida = True
    with pytest.raises(ConnectionError):
        s.paso()
    s.conectado, s.ultimo_error = False, "la API de datos no responde"     # lo que hace el ciclo
    s.vigilar_datos(t0 + 59 * 60)
    assert avisos == []                                       # menos de una hora: todavía no
    s.vigilar_datos(t0 + 61 * 60)
    s.vigilar_datos(t0 + 120 * 60)                            # una sola vez
    (texto, nivel, asunto), = avisos
    assert nivel == "resumen" and "1 h 1 min" in asunto and "no responde" in texto
    fuente.caida = False
    fuente.llegan(3)
    s.paso()
    s.vigilar_datos(t0 + 150 * 60)
    datos = [a for a in avisos if "datos de los sensores" in a[2]]   # (el resumen diario también sale)
    assert len(datos) == 2 and "Vuelven" in datos[1][2] and "2 h 30 min" in datos[1][0]
    assert s.sin_datos_desde is None


def test_sensores_callados_con_la_api_funcionando(servicio):
    nuevo, fuente = servicio
    s = nuevo()
    avisos = []
    s.alertas.avisar = lambda texto, nivel="rojo", asunto=None, enlace=None: avisos.append(texto)
    s.paso()                                                  # la API responde pero no hay lecturas
    s.vigilar_datos(s._vista_t + 3600)
    assert len(avisos) == 1 and "no trae lecturas nuevas" in avisos[0] and "todavía no ha llegado" in avisos[0]


def test_sin_base_el_ciclo_sigue_y_el_cursor_se_guarda_al_volver(servicio):
    nuevo, fuente = servicio
    s = nuevo()
    guardar = s.cursor.guardar
    s.cursor.guardar = lambda hora: (_ for _ in ()).throw(ConnectionError("la base no responde"))
    fuente.llegan(8)
    s.paso()                                                  # no se cae aunque no pueda guardar el cursor
    assert s.conectado and "no responde" in s.error_cursor and s.cursor.leer() is None
    s.cursor.guardar = guardar
    fuente.llegan(2)
    s.paso()
    assert s.error_cursor is None and s.cursor.leer() == s.motor.ultima_hora_procesada
