"""Inicio de sesión, roles y gestión de usuarios (usuarios.py y /api/sesion, /api/usuarios)."""

import pytest
from fastapi.testclient import TestClient

from conftest import ModelosFalsos, configuracion
from monitoreo import servicio as srv
from monitoreo import usuarios as us
from monitoreo.motor import Motor

CLAVE = "una-clave-larga-1"


@pytest.fixture
def cuentas(tmp_path):
    return us.Usuarios(f"sqlite:///{tmp_path / 'usuarios.db'}")


def test_la_contrasena_se_guarda_con_hash(cuentas):
    u = cuentas.crear("Ana Mora", "Ana@ASADA.cr", "operador", CLAVE)
    assert u["correo"] == "ana@asada.cr" and u["debe_cambiar"] is True
    with cuentas.motor.connect() as c:
        guardado = c.execute(us.usuarios.select()).first().hash
    assert CLAVE not in guardado and guardado.startswith("scrypt$")
    assert us.verificar_contrasena(CLAVE, guardado) and not us.verificar_contrasena("otra-clave-1", guardado)


def test_validaciones_al_crear(cuentas):
    cuentas.crear("Ana", "ana@asada.cr", "operador", CLAVE)
    for args, mensaje in [(("", "b@asada.cr", "operador", CLAVE), "nombre"),
                          (("B", "no-es-correo", "operador", CLAVE), "correo"),
                          (("B", "b@asada.cr", "jefe", CLAVE), "rol"),
                          (("B", "b@asada.cr", "operador", "corta"), "10 caracteres"),
                          (("B", "ANA@asada.cr", "operador", CLAVE), "Ya hay")]:
        with pytest.raises(us.ErrorUsuarios, match=mensaje):
            cuentas.crear(*args)


def test_inicio_de_sesion_mensaje_generico_y_bloqueo(cuentas):
    cuentas.crear("Ana", "ana@asada.cr", "operador", CLAVE)
    for correo in ("ana@asada.cr", "nadie@asada.cr"):          # mismo mensaje: no revela cuál falló
        with pytest.raises(us.ErrorUsuarios, match="Correo o contraseña incorrectos") as e:
            cuentas.iniciar_sesion(correo, "equivocada-123")
        assert e.value.codigo == 401
    for _ in range(us.INTENTOS_MAXIMOS - 1):
        with pytest.raises(us.ErrorUsuarios):
            cuentas.iniciar_sesion("ana@asada.cr", "equivocada-123")
    with pytest.raises(us.ErrorUsuarios, match="Demasiados intentos") as e:  # aunque ahora sea la correcta
        cuentas.iniciar_sesion("ana@asada.cr", CLAVE)
    assert e.value.codigo == 429
    acciones = [f["accion"] for f in cuentas.ver_bitacora()]
    assert "inicio_bloqueado" in acciones and acciones.count("inicio_fallido") == us.INTENTOS_MAXIMOS + 1


def test_el_bloqueo_es_por_origen_y_no_deja_fuera_al_dueno_de_la_cuenta(cuentas):
    """Equivocarse a propósito con el correo de otro solo bloquea a quien lo hace (su origen)."""
    cuentas.crear("Ana", "ana@asada.cr", "operador", CLAVE)
    for _ in range(us.INTENTOS_MAXIMOS):
        with pytest.raises(us.ErrorUsuarios):
            cuentas.iniciar_sesion("ana@asada.cr", "equivocada-123", origen="10.0.0.66")
    with pytest.raises(us.ErrorUsuarios) as e:
        cuentas.iniciar_sesion("ana@asada.cr", CLAVE, origen="10.0.0.66")
    assert e.value.codigo == 429
    codigo, u = cuentas.iniciar_sesion("ana@asada.cr", CLAVE, origen="10.0.0.5")    # Ana, desde su casa
    assert u["correo"] == "ana@asada.cr" and codigo


def test_muchos_correos_desde_un_origen_tambien_se_frenan(cuentas):
    """Probar una contraseña común contra muchas cuentas: a los 20 fallos el origen espera."""
    for i in range(us.INTENTOS_POR_ORIGEN):
        with pytest.raises(us.ErrorUsuarios) as e:
            cuentas.iniciar_sesion(f"u{i}@asada.cr", "Verano2026!", origen="10.0.0.66")
        assert e.value.codigo == 401
    with pytest.raises(us.ErrorUsuarios) as e:
        cuentas.iniciar_sesion("otro@asada.cr", "Verano2026!", origen="10.0.0.66")
    assert e.value.codigo == 429


def test_los_intentos_viejos_se_olvidan_y_la_memoria_tiene_tope():
    i = us.Intentos(ventana_s=0.05, tope=3)
    i.fallo("a"), i.fallo("a")
    assert i.bloqueado("a", 2)
    import time
    time.sleep(0.06)
    assert not i.bloqueado("a", 2)
    for k in "bcdef":
        i.fallo(k)
    assert len(i._fallos) <= 3


def test_correo_inexistente_tambien_calcula_el_hash(cuentas, monkeypatch):
    """Si no se calculara scrypt para un correo que no existe, el tiempo de respuesta lo delataría."""
    calculados = []
    original = us.verificar_contrasena
    monkeypatch.setattr(us, "verificar_contrasena", lambda c, g: calculados.append(g) or original(c, g))
    with pytest.raises(us.ErrorUsuarios):
        cuentas.iniciar_sesion("nadie@asada.cr", "equivocada-123")
    assert calculados == [us.hash_ficticio()]


def test_hash_con_parametros_viejos_se_rehace_al_entrar(cuentas):
    u = cuentas.crear("Ana", "ana@asada.cr", "operador", CLAVE, debe_cambiar=False)
    viejo = us.hash_contrasena(CLAVE, n=2 ** 14, r=8, p=1)                # los parámetros de antes
    with cuentas.motor.begin() as c:
        c.execute(us.usuarios.update().where(us.usuarios.c.id == u["id"]).values(hash=viejo))
    assert us.hash_viejo(viejo) and not us.hash_viejo(us.hash_contrasena(CLAVE))
    cuentas.iniciar_sesion("ana@asada.cr", CLAVE)
    with cuentas.motor.connect() as c:
        nuevo = c.execute(us.usuarios.select()).first().hash
    assert nuevo != viejo and not us.hash_viejo(nuevo) and us.verificar_contrasena(CLAVE, nuevo)


def test_cambiar_la_contrasena_cierra_las_demas_sesiones(cuentas):
    ana = cuentas.crear("Ana", "ana@asada.cr", "operador", CLAVE, debe_cambiar=False)
    aqui, _ = cuentas.iniciar_sesion("ana@asada.cr", CLAVE)
    otra, _ = cuentas.iniciar_sesion("ana@asada.cr", CLAVE)                # p. ej. alguien con la clave robada
    cuentas.cambiar_propia(ana["id"], CLAVE, "otra-clave-larga-2", conservar=aqui)
    assert cuentas.de_sesion(aqui)["id"] == ana["id"] and cuentas.de_sesion(otra) is None
    assert "se cerraron 1 sesiones" in cuentas.ver_bitacora()[0]["detalle"]


def test_cambiar_la_contrasena_tambien_limita_los_intentos(cuentas):
    ana = cuentas.crear("Ana", "ana@asada.cr", "operador", CLAVE, debe_cambiar=False)
    for _ in range(us.INTENTOS_MAXIMOS):
        with pytest.raises(us.ErrorUsuarios) as e:
            cuentas.cambiar_propia(ana["id"], "no-es-esta-1", "otra-clave-larga-2", origen="10.0.0.66")
        assert e.value.codigo == 403
    with pytest.raises(us.ErrorUsuarios) as e:
        cuentas.cambiar_propia(ana["id"], CLAVE, "otra-clave-larga-2", origen="10.0.0.66")
    assert e.value.codigo == 429


def test_cuenta_inactiva_y_sesion_cerrada_al_desactivar(cuentas):
    admin = cuentas.crear("Admin", "admin@asada.cr", "administrador", CLAVE, debe_cambiar=False)
    ana = cuentas.crear("Ana", "ana@asada.cr", "operador", CLAVE)
    codigo, _ = cuentas.iniciar_sesion("ana@asada.cr", CLAVE)
    assert cuentas.de_sesion(codigo)["id"] == ana["id"]
    cuentas.modificar(ana["id"], {"activo": False}, por=admin["correo"])
    assert cuentas.de_sesion(codigo) is None
    with pytest.raises(us.ErrorUsuarios, match="desactivada") as e:
        cuentas.iniciar_sesion("ana@asada.cr", CLAVE)
    assert e.value.codigo == 403


def test_no_se_queda_sin_administrador(cuentas):
    admin = cuentas.crear("Admin", "admin@asada.cr", "administrador", CLAVE)
    for cambio in ({"activo": False}, {"rol": "operador"}):
        with pytest.raises(us.ErrorUsuarios, match="único administrador") as e:
            cuentas.modificar(admin["id"], cambio)
        assert e.value.codigo == 409
    otro = cuentas.crear("Otro", "otro@asada.cr", "administrador", CLAVE)
    assert cuentas.modificar(admin["id"], {"rol": "junta"})["rol"] == "junta"
    with pytest.raises(us.ErrorUsuarios, match="único administrador"):
        cuentas.modificar(otro["id"], {"activo": False})


def test_el_administrador_no_se_quita_el_acceso_a_si_mismo(cuentas):
    a = cuentas.crear("Admin", "admin@asada.cr", "administrador", CLAVE)
    cuentas.crear("Otro", "otro@asada.cr", "administrador", CLAVE)
    for cambio in ({"activo": False}, {"rol": "junta"}, {"contrasena": "otra-clave-larga"}):
        with pytest.raises(us.ErrorUsuarios, match="tu propio rol"):
            cuentas.modificar(a["id"], cambio, por="admin@asada.cr")
    assert cuentas.modificar(a["id"], {"notificar_amarillo": True}, por="admin@asada.cr")["notificar_amarillo"]
    assert cuentas.modificar(a["id"], {"activo": False}, por="otro@asada.cr")["activo"] is False


def test_destinatarios_por_nivel(cuentas):
    cuentas.crear("Ana", "ana@asada.cr", "operador", CLAVE)
    cuentas.crear("Beto", "beto@asada.cr", "junta", CLAVE)
    b = cuentas.crear("Carla", "carla@asada.cr", "administrador", CLAVE)
    assert sorted(cuentas.destinatarios("rojo")) == ["ana@asada.cr", "carla@asada.cr"]
    assert cuentas.destinatarios("amarillo") == ["ana@asada.cr"]
    cuentas.modificar(b["id"], {"notificar_amarillo": True})
    assert sorted(cuentas.destinatarios("amarillo")) == ["ana@asada.cr", "carla@asada.cr"]


# ---------------------------------------------------------------------------- por la API
@pytest.fixture
def api(tmp_path, monkeypatch):
    yield from _cliente(tmp_path, monkeypatch)


def _cliente(tmp_path, monkeypatch, smtp=False):
    monkeypatch.delenv("TELEGRAM_TOKEN", raising=False)
    if not smtp:
        monkeypatch.delenv("SMTP_SERVIDOR", raising=False)
    monkeypatch.setattr(srv, "Motor", lambda cfg: Motor(cfg, ModelosFalsos(), registrar=False))
    monkeypatch.setattr(srv, "ClienteDatos", lambda url: type("D", (), {"lecturas_desde": lambda self, d=None: []})())
    cfg = configuracion(tmp_path, inicio_sesion=True)
    cuentas = us.Usuarios(cfg.base_usuarios)
    cuentas.crear("Admin", "admin@asada.cr", "administrador", CLAVE, debe_cambiar=False)
    cuentas.crear("Beto", "beto@asada.cr", "junta", CLAVE, debe_cambiar=False)
    with TestClient(srv.crear_app(cfg)) as c:
        yield c


def entrar(c, correo, clave=CLAVE):
    return c.post("/api/sesion", json={"correo": correo, "contrasena": clave})


def test_sin_sesion_la_api_del_dashboard_responde_401(api):
    for ruta in ("/api/estado", "/api/sensores", "/api/usuarios", "/api/sesion"):
        r = api.get(ruta)
        assert r.status_code == 401 and r.json()["detail"]["error"] == "Inicia sesión para continuar."
    assert api.get("/health").status_code in (200, 503)               # /health sigue abierto


def test_entrar_salir_y_cookie_segura(api):
    r = entrar(api, "admin@asada.cr")
    assert r.status_code == 200 and r.json()["usuario"]["rol"] == "administrador"
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    assert api.get("/api/estado").status_code == 200
    assert api.get("/api/sesion").json()["permisos"] == {"gestionar_usuarios": True, "atender_alertas": True}
    api.delete("/api/sesion")
    assert api.get("/api/estado").status_code == 401


def test_junta_ve_el_tablero_pero_no_administra(api):
    entrar(api, "beto@asada.cr")
    assert api.get("/api/estado").status_code == 200
    assert api.get("/api/usuarios").status_code == 403
    assert api.post("/api/usuarios", json={"nombre": "X", "correo": "x@asada.cr", "rol": "operador",
                                           "contrasena": CLAVE}).status_code == 403


def test_administrador_crea_usuario_que_debe_cambiar_su_contrasena(api):
    entrar(api, "admin@asada.cr")
    r = api.post("/api/usuarios", json={"nombre": "Ana", "correo": "ana@asada.cr", "rol": "operador",
                                        "contrasena": "temporal-123"})
    assert r.status_code == 201 and r.json()["debe_cambiar"] is True
    assert api.post("/api/usuarios", json={"nombre": "Ana", "correo": "ana@asada.cr", "rol": "operador",
                                           "contrasena": "temporal-123"}).status_code == 409
    bitacora = api.get("/api/bitacora").json()
    assert bitacora[0]["accion"] == "usuario_creado" and bitacora[0]["correo"] == "admin@asada.cr"
    api.delete("/api/sesion")

    entrar(api, "ana@asada.cr", "temporal-123")
    r = api.get("/api/estado")
    assert r.status_code == 403 and r.json()["detail"]["debe_cambiar"] is True
    assert api.post("/api/sesion/contrasena", json={"actual": "mala", "nueva": "nueva-clave-99"}).status_code == 403
    r = api.post("/api/sesion/contrasena", json={"actual": "temporal-123", "nueva": "nueva-clave-99"})
    assert r.status_code == 200 and r.json()["usuario"]["debe_cambiar"] is False
    assert api.get("/api/estado").status_code == 200
    assert api.get("/api/usuarios").status_code == 403                # operador: no administra


def test_credenciales_incorrectas_por_la_api(api):
    r = entrar(api, "admin@asada.cr", "equivocada-1")
    assert r.status_code == 401 and r.json()["detail"]["error"] == "Correo o contraseña incorrectos."
    assert "set-cookie" not in r.headers


def test_notificaciones_solo_para_el_administrador(api):
    entrar(api, "beto@asada.cr")
    assert api.get("/api/notificaciones").status_code == 403
    assert api.post("/api/notificaciones/prueba").status_code == 403
    api.delete("/api/sesion")
    entrar(api, "admin@asada.cr")
    r = api.get("/api/notificaciones").json()
    assert r["correo"] == {"configurado": False} and r["destinatarios"] == {"rojo": 1, "amarillo": 0}
    r = api.post("/api/notificaciones/prueba")
    assert r.status_code == 409 and "SMTP_SERVIDOR" in r.json()["detail"]["error"]


class ServidorCorreo:
    """Hace de smtplib.SMTP y guarda lo que se manda."""
    enviados = []

    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self, context=None):
        pass

    def login(self, usuario, contrasena):
        pass

    def send_message(self, m):
        ServidorCorreo.enviados.append(m)


@pytest.fixture
def api_correo(tmp_path, monkeypatch):
    from monitoreo import correo
    ServidorCorreo.enviados = []
    monkeypatch.setattr(correo.smtplib, "SMTP", ServidorCorreo)
    monkeypatch.setenv("SMTP_SERVIDOR", "smtp.ejemplo.com")
    monkeypatch.setenv("SMTP_USUARIO", "alertas@asada.cr")
    monkeypatch.setenv("SMTP_CONTRASENA", "clave-de-aplicacion")
    yield from _cliente(tmp_path, monkeypatch, smtp=True)


def test_correo_de_prueba_por_la_api(api_correo):
    entrar(api_correo, "admin@asada.cr")
    r = api_correo.post("/api/notificaciones/prueba")
    assert r.status_code == 200 and r.json() == {"enviado_a": "admin@asada.cr"}
    assert [m["To"] for m in ServidorCorreo.enviados] == ["admin@asada.cr"]
    datos = api_correo.get("/api/notificaciones").json()
    assert datos["correo"] == {"configurado": True, "servidor": "smtp.ejemplo.com:587", "seguridad": "starttls",
                               "remitente": "alertas@asada.cr"}
    assert datos["ultimas"][0]["estado"] == "enviada" and datos["ultimas"][0]["nivel"] == "prueba"
    assert datos["ultimas"][0]["destinatarios"] == "admin@asada.cr"


def test_cambiar_la_contrasena_por_la_api_deja_abierta_esta_sesion(api, tmp_path):
    entrar(api, "beto@asada.cr")
    cuentas = us.Usuarios(configuracion(tmp_path, inicio_sesion=True).base_usuarios)
    otra, _ = cuentas.iniciar_sesion("beto@asada.cr", CLAVE)
    r = api.post("/api/sesion/contrasena", json={"actual": CLAVE, "nueva": "otra-clave-larga-2"})
    assert r.status_code == 200
    assert api.get("/api/estado").status_code == 200                      # la sesión que hizo el cambio sigue
    api.cookies.clear()
    api.cookies.set(srv.COOKIE, otra)                                     # la que se abrió en otro lado
    assert api.get("/api/estado").status_code == 401


def test_textos_mas_largos_que_la_base_dan_422_y_no_500(api):
    entrar(api, "admin@asada.cr")
    r = api.post("/api/alertas/1/notas", json={"texto": "x" * (srv.NOTA_MAX + 1)})
    assert r.status_code == 422 and "texto: es demasiado largo" in r.json()["detail"]["detalles"]
    r = api.post("/api/alertas/1/cerrar", json={"resultado": "confirmada", "observaciones": "x" * (srv.CIERRE_MAX + 1)})
    assert r.status_code == 422
    r = api.patch("/api/usuarios/2", json={"nombre": "N" * (srv.NOMBRE_MAX + 1)})
    assert r.status_code == 422
    assert api.post("/api/sesion", json={"correo": "a@b.cr", "contrasena": "x" * 2000}).status_code == 422
