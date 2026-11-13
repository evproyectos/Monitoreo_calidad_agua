"""Gestión de las alertas (gestion.py, CU-06): reconocer, atender, cerrar, deduplicar e historial."""

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from conftest import INICIO, ModelosFalsos, configuracion, lecturas
from monitoreo import alertas
from monitoreo import gestion as ge
from monitoreo import servicio as srv
from monitoreo import usuarios as us
from monitoreo.motor import Motor

ANA = {"correo": "ana@asada.cr", "nombre": "Ana Mora"}
LUIS = {"correo": "luis@asada.cr", "nombre": "Luis Vega"}


@pytest.fixture
def g(tmp_path):
    return ge.GestionAlertas(f"sqlite:///{tmp_path}/g.db")


def alarma(g, inicio="2026-05-01 06:00:00", nodos=("J10",), p=0.9, grupo="alarma", nivel="rojo", tipo="alarma"):
    return g.abrir(grupo=grupo, inicio=inicio, tipo=tipo, nivel=nivel, titulo=f"Contaminación en {nodos[0]}",
                   evento="contaminacion", lugar="Sensor " + ", ".join(nodos), nodos=nodos, probabilidad=p,
                   accion="tomar muestras")


def test_no_se_duplica_mientras_siga_activa(g):
    uid, nueva = alarma(g)
    assert nueva
    assert alarma(g) == (uid, False)                                     # misma alarma (al reiniciar)
    assert alarma(g, inicio="2026-05-01 08:00:00", p=0.97) == (uid, False)  # el mismo grupo sigue activo
    assert g.detalle(uid)["probabilidad"] == 0.97                        # se actualiza la probabilidad
    g.terminar("alarma", "2026-05-01 10:00:00")
    otra, nueva = alarma(g, inicio="2026-05-02 06:00:00")
    assert nueva and otra != uid                                         # ya terminó: es otra alerta


def test_un_aviso_que_nadie_tomo_se_cierra_solo(g):
    """RF-003.3 (3): la alerta predictiva se resuelve sola cuando el riesgo baja del umbral."""
    aviso, _ = alarma(g, grupo="aviso:falla_cloro", nivel="amarillo", tipo="aviso")
    roja, _ = alarma(g)
    assert g.terminar("aviso:falla_cloro", "2026-05-01 12:00:00") == [aviso]
    g.terminar("alarma", "2026-05-01 12:00:00")
    assert g.terminar("alarma", "2026-05-01 13:00:00") == []              # ya había terminado
    a = g.detalle(aviso)
    assert a["estado"] == "cerrada" and a["resultado"] == "automatica" and a["fin"] == "2026-05-01 12:00:00"
    r = g.detalle(roja)
    assert r["estado"] == "nueva" and not r["activa"]                    # la roja espera que alguien la verifique
    assert [h["accion"] for h in r["historial"]] == ["creada", "termino"]


def test_atender_y_cerrar_con_historial(g):
    uid, _ = alarma(g)
    a = g.reconocer(uid, ANA)
    assert a["estado"] == "en_atencion" and a["responsable_nombre"] == "Ana Mora"
    with pytest.raises(ge.ErrorGestion, match="Ya la atiende Ana Mora") as e:
        g.reconocer(uid, LUIS)                                           # 3a: otra persona
    assert e.value.codigo == 409
    g.nota(uid, LUIS, "Muestra tomada en la llave del parque.")          # pero sí puede anotar
    with pytest.raises(ge.ErrorGestion, match="resultado"):
        g.cerrar(uid, ANA, "", "algo que pasó")
    with pytest.raises(ge.ErrorGestion, match="obligatorias"):
        g.cerrar(uid, ANA, "confirmada", " ")
    a = g.cerrar(uid, ANA, "confirmada", "Coliformes positivos en el laboratorio.")
    assert a["estado"] == "cerrada" and a["resultado_nombre"] == "Confirmada" and a["cerrada"]
    h = a["historial"]
    assert [x["accion"] for x in h] == ["creada", "reconocida", "nota", "cerrada"]
    assert h[0]["correo"] is None and h[2]["nombre"] == "Luis Vega"
    assert h[3]["texto"] == "Confirmada. Coliformes positivos en el laboratorio."
    for accion in (lambda: g.reconocer(uid, ANA), lambda: g.nota(uid, ANA, "otra nota más"),
                   lambda: g.cerrar(uid, ANA, "descartada", "cambio de opinión")):
        with pytest.raises(ge.ErrorGestion, match="ya está cerrada"):
            accion()
    with pytest.raises(ge.ErrorGestion) as e:
        g.detalle(999)
    assert e.value.codigo == 404


def test_cerrar_sin_reconocer_deja_responsable(g):
    uid, _ = alarma(g)
    a = g.cerrar(uid, LUIS, "inconclusa", "No se pudo llegar al sitio por la lluvia.")
    assert a["responsable"] == "luis@asada.cr" and a["resultado"] == "inconclusa"


def test_filtros_y_orden(g):
    vieja, _ = alarma(g, inicio="2026-05-01 06:00:00", nodos=("J10", "J20"))
    g.cerrar(vieja, ANA, "descartada", "Lectura mala del sensor J10.")
    aviso, _ = alarma(g, inicio="2026-05-03 06:00:00", nodos=("J1",), grupo="aviso:x", nivel="amarillo", tipo="aviso")
    roja, _ = alarma(g, inicio="2026-05-02 06:00:00", nodos=("J100",))
    assert [a["id"] for a in g.lista()] == [roja, aviso, vieja]           # pendientes y rojas primero
    assert [a["id"] for a in g.lista("pendientes")] == [roja, aviso]
    assert [a["id"] for a in g.lista("cerrada")] == [vieja]
    assert [a["id"] for a in g.lista(tipo="aviso")] == [aviso]
    assert [a["id"] for a in g.lista(nodo="J10")] == [vieja]             # J10 no confunde J1 ni J100
    assert [a["id"] for a in g.lista(nodo="J1")] == [aviso]
    assert [a["id"] for a in g.lista(nodo="J10%")] == [roja, aviso, vieja]  # comodines: se ignora el filtro
    assert [a["id"] for a in g.lista(desde="2026-05-02", hasta="2026-05-02")] == [roja]


def test_indicadores(g):
    for i, resultado in enumerate(["confirmada", "confirmada", "confirmada", "descartada", "inconclusa"]):
        uid, _ = alarma(g, inicio=f"2026-05-0{i + 1} 06:00:00", grupo=f"g{i}")
        g.cerrar(uid, ANA, resultado, "verificado en campo")
    alarma(g, grupo="nueva")
    uid, _ = alarma(g, grupo="tomada", nivel="amarillo")
    g.reconocer(uid, ANA)
    r = g.indicadores()
    assert r["pendientes"] == 2 and r["nuevas"] == 1 and r["rojas_sin_atender"] == 1 and r["en_atencion"] == 1
    assert r["cerradas"] == 5 and r["por_resultado"]["confirmada"] == 3
    assert r["confirmadas_pct"] == 75                                    # 3 de 4 verificadas (sin la inconclusa)


# ---------------------------------------------------------------------------- con el motor y las alertas
def hora(k):
    return INICIO + pd.Timedelta(hours=k)


def correr(motor, al, horas):
    lec = lecturas(horas)
    for k in range(horas):
        for x in lec[k * 4:(k + 1) * 4]:
            motor.recibir(x["fecha"], x["valores"])
        al.revisar(motor, motor.procesar())


def con_gestion(g):
    a = alertas.Alertas(canal=alertas.CanalConsola(), gestion=g)
    a.url = "https://tablero.asada.cr"
    a.avisos = []
    a.avisar = lambda texto, nivel="rojo", asunto=None, enlace=None: a.avisos.append((asunto, enlace))
    return a


def test_cada_alarma_queda_para_atenderse_y_no_se_reenvia_al_reiniciar(cfg, g):
    alto = {hora(k) for k in (5, 6, 7)}
    modelos = ModelosFalsos(p_evento=lambda h, n: 0.95 if (n == "J10" and h in alto) else 0.1)
    al = con_gestion(g)
    correr(Motor(cfg, modelos, registrar=False), al, 12)
    (a,) = g.lista()
    assert a["tipo"] == "alarma" and a["evento"] == "contaminacion" and a["nodos"] == ["J10"]
    assert a["titulo"] == "Contaminación en J10" and a["probabilidad"] == 0.95 and not a["activa"]
    assert a["parametros"].startswith("J10: cloro") and a["accion"].startswith("tomar muestras")
    abierta = next(x for x in al.avisos if x[0].startswith("Alerta roja"))
    assert abierta[1] == f"https://tablero.asada.cr/#/alertas/{a['id']}"   # el correo lleva a la alerta
    cerrada = next(x for x in al.avisos if "cerrada" in x[0])
    assert cerrada[1] == abierta[1]                                      # y el de cierre, a cerrarla
    otra = con_gestion(g)                                                # el servicio se reinicia
    correr(Motor(cfg, modelos, registrar=False), otra, 12)
    assert [x[0] for x in otra.avisos if "Alarma" in x[0]] == [] and len(g.lista()) == 1   # ni la alarma ni su cierre


def test_riesgo_en_24h_una_alerta_por_sensor_que_se_cierra_sola(cfg, g):
    modelos = ModelosFalsos(pronostico_24h={"J20": {"CL2": 0.2}, "J10": {"PH": 9.0}})
    motor = Motor(cfg, modelos, registrar=False)
    al = con_gestion(g)
    correr(motor, al, 7)
    riesgos = g.lista(tipo="riesgo")
    assert sorted(a["titulo"] for a in riesgos) == ["Riesgo en 24 h: cloro fuera de norma en J20",
                                                    "Riesgo en 24 h: pH fuera de norma en J10"]
    assert all(a["antelacion_h"] == 24 and a["nivel"] == "amarillo" for a in riesgos)
    assert [x[1] for x in al.avisos if "Riesgo" in x[0]] == ["https://tablero.asada.cr/#/alertas"]
    modelos.pronostico_24h = {}
    correr(motor, al, 7 + alertas.HORAS_FIN_RIESGO)
    assert {a["resultado"] for a in g.lista(tipo="riesgo")} == {"automatica"}


def test_aviso_anticipado_queda_y_se_cierra_cuando_baja(cfg, g):
    alto = {hora(k) for k in (5, 6)}
    al = con_gestion(g)
    correr(Motor(cfg, ModelosFalsos(p_anticipa=lambda h, k: 0.82 if h in alto else 0.1), registrar=False), al, 30)
    (a,) = g.lista(tipo="aviso")
    assert a["titulo"] == "Posible turbidez en la fuente en las próximas 24 h" and a["nodos"] == ["J280"]
    assert a["estado"] == "cerrada" and a["resultado"] == "automatica"


def test_sin_base_de_datos_se_notifica_igual(cfg, capsys):
    class Rota:
        def abrir(self, **k):
            raise RuntimeError("sin conexión")

        def terminar(self, *a):
            raise RuntimeError("sin conexión")

    al = con_gestion(Rota())
    alto = {hora(k) for k in (5, 6, 7)}
    correr(Motor(cfg, ModelosFalsos(p_evento=lambda h, n: 0.95 if (n == "J10" and h in alto) else 0.1),
                 registrar=False), al, 12)
    assert any(x[0].startswith("Alerta roja") and x[1] is None for x in al.avisos)
    assert "No se pudo guardar la alerta: sin conexión" in capsys.readouterr().out


def test_boton_del_correo_lleva_a_la_alerta():
    from monitoreo import correo
    pagina = correo.cuerpo_html("<b>Alarma</b>\nhttps://x/#/sensor/J10", "rojo", "https://x",
                                alerta="https://x/#/alertas/7")
    assert 'href="https://x/#/alertas/7"' in pagina and "Ver y atender la alerta" in pagina


# ---------------------------------------------------------------------------- por la API
CLAVE = "una-clave-larga-1"


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.delenv("TELEGRAM_TOKEN", raising=False)
    monkeypatch.delenv("SMTP_SERVIDOR", raising=False)
    monkeypatch.setattr(srv, "Motor", lambda cfg: Motor(cfg, ModelosFalsos(), registrar=False))
    monkeypatch.setattr(srv, "ClienteDatos", lambda url: type("D", (), {"lecturas_desde": lambda self, d=None: []})())
    cfg = configuracion(tmp_path, inicio_sesion=True)
    cuentas = us.Usuarios(cfg.base_usuarios)
    cuentas.crear("Ana Mora", "ana@asada.cr", "operador", CLAVE, debe_cambiar=False)
    cuentas.crear("Carmen Solís", "carmen@asada.cr", "junta", CLAVE, debe_cambiar=False)
    uid, _ = alarma(ge.GestionAlertas(cfg.base_usuarios))
    with TestClient(srv.crear_app(cfg)) as c:
        c.uid = uid
        yield c


def entrar(c, correo):
    assert c.post("/api/sesion", json={"correo": correo, "contrasena": CLAVE}).status_code == 200


def test_la_junta_ve_las_alertas_pero_no_las_atiende(api):
    assert api.get("/api/alertas").status_code == 401
    entrar(api, "carmen@asada.cr")
    assert [a["id"] for a in api.get("/api/alertas?estado=pendientes").json()] == [api.uid]
    assert api.get(f"/api/alertas/{api.uid}").json()["historial"][0]["accion"] == "creada"
    r = api.post(f"/api/alertas/{api.uid}/reconocer")
    assert r.status_code == 403 and "operador" in r.json()["detail"]["error"]
    assert api.get("/api/alertas/indicadores").json()["rojas_sin_atender"] == 1


def test_el_operador_atiende_y_cierra_por_la_api(api):
    entrar(api, "ana@asada.cr")
    r = api.post(f"/api/alertas/{api.uid}/reconocer")
    assert r.status_code == 200 and r.json()["responsable_nombre"] == "Ana Mora"
    assert api.post(f"/api/alertas/{api.uid}/notas", json={"texto": "Revisé la llave."}).status_code == 200
    r = api.post(f"/api/alertas/{api.uid}/cerrar", json={"resultado": "descartada", "observaciones": "x"})
    assert r.status_code == 400 and "obligatorias" in r.json()["detail"]["error"]
    r = api.post(f"/api/alertas/{api.uid}/cerrar",
                 json={"resultado": "descartada", "observaciones": "El sensor estaba sucio; se limpió."})
    assert r.status_code == 200 and r.json()["estado"] == "cerrada"
    assert api.post(f"/api/alertas/{api.uid}/reconocer").status_code == 409
    assert api.get("/api/alertas/999").status_code == 404
    assert api.get("/api/alertas?desde=ayer").status_code == 422
