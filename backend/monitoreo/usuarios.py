"""
Usuarios, roles y sesiones del dashboard (CU-00 y CU-07).

Roles
  junta           Junta Directiva: ve el tablero (solo lectura).
  operador        Operador técnico: ve el tablero y atiende las alertas.
  administrador   Administración de la ASADA: lo anterior, más crear, editar y desactivar usuarios,
                  elegir quién recibe las notificaciones de cada nivel y ver la bitácora.

Dónde se guardan
  En la base del servicio (BASE_DE_DATOS, PostgreSQL en Docker) o, sin ella, en SQLite en
  registros/usuarios.db. Tablas: usuarios, sesiones, bitacora (accesos y cambios, RNF-004) y
  notificaciones (cada alerta enviada por correo o Telegram, con sus destinatarios, CU-04 paso 5).

Contraseñas
  Nunca se guardan: se guarda su hash con scrypt (sal aleatoria por usuario; N=2^14, r=8, p=5, una
  de las combinaciones que recomienda OWASP, con 16 MiB de memoria por cálculo). Los hashes con
  otros parámetros se rehacen solos la siguiente vez que la persona entra. Mínimo 10 caracteres.
  Un usuario creado por el administrador recibe una contraseña temporal y debe cambiarla al entrar
  por primera vez.

Sesiones
  Al iniciar sesión el navegador recibe una cookie HttpOnly y SameSite=Strict (Secure con HTTPS)
  con un código aleatorio; en la base solo queda el SHA-256 de ese código. Vence a las 12 h. Al
  cambiar la propia contraseña se cierran las demás sesiones de esa persona.

Intentos fallidos
  Se limitan por origen (la dirección IP) y no por cuenta, para que nadie pueda dejar fuera a
  otra persona equivocándose a propósito con su correo: 5 intentos fallidos en 15 minutos desde
  un mismo origen para un mismo correo, o 20 desde un mismo origen sumando todos los correos (para
  frenar a quien prueba una contraseña común contra muchas cuentas), y ese origen espera 15
  minutos. Si el correo no existe se calcula igual el hash, para que el tiempo de respuesta no
  revele qué correos tienen cuenta. Cambiar la propia contraseña tiene el mismo límite (5 intentos
  con la actual equivocada). Detrás de un proxy hay que pasarle al servicio la IP real de cada
  persona: si no, todos comparten el origen del proxy y el límite de 20 sería para todos juntos.

El primer administrador se crea desde la consola (desde backend/):
    python -m monitoreo.usuarios --crear-admin correo@asada.cr "Nombre Apellido"
En Docker:
    docker compose exec monitoreo python -m monitoreo.usuarios --crear-admin correo@asada.cr "Nombre"
"""

import argparse
import base64
import hashlib
import hmac
import re
import secrets
import threading
import time
from datetime import datetime, timedelta

from sqlalchemy import (Boolean, Column, DateTime, Integer, MetaData, String, Table, create_engine, func,
                        insert, select, update)

ROLES = {"operador": "Operador técnico", "administrador": "Administrador", "junta": "Junta Directiva"}
MINIMO_CONTRASENA = 10
DURACION_SESION = timedelta(hours=12)
INTENTOS_MAXIMOS, INTENTOS_POR_ORIGEN, BLOQUEO_S = 5, 20, 15 * 60
SCRYPT = {"n": 2 ** 14, "r": 8, "p": 5}
MAXIMO_CONTRASENA = 1024                    # más larga no la acepta la API (servicio.py)
CORREO = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

meta = MetaData()
usuarios = Table(
    "usuarios", meta,
    Column("id", Integer, primary_key=True),
    Column("nombre", String(120), nullable=False),
    Column("correo", String(254), nullable=False, unique=True),
    Column("rol", String(20), nullable=False),
    Column("hash", String(200), nullable=False),
    Column("activo", Boolean, nullable=False, default=True),
    Column("debe_cambiar", Boolean, nullable=False, default=True),
    # destinatarios de las notificaciones por nivel de riesgo (CU-07 paso 5)
    Column("notificar_rojo", Boolean, nullable=False, default=True),
    Column("notificar_amarillo", Boolean, nullable=False, default=False),
    Column("creado", DateTime, nullable=False),
    Column("ultimo_acceso", DateTime),
)
sesiones = Table(
    "sesiones", meta,
    Column("codigo", String(64), primary_key=True),            # SHA-256 del código de la cookie
    Column("usuario_id", Integer, nullable=False),
    Column("creada", DateTime, nullable=False),
    Column("vence", DateTime, nullable=False),
)
bitacora = Table(
    "bitacora", meta,
    Column("id", Integer, primary_key=True),
    Column("fecha", DateTime, nullable=False),
    Column("correo", String(254)),
    Column("accion", String(40), nullable=False),
    Column("detalle", String(500)),
    Column("origen", String(64)),
)
notificaciones = Table(
    "notificaciones", meta,
    Column("id", Integer, primary_key=True),
    Column("fecha", DateTime, nullable=False),
    Column("canal", String(20), nullable=False),               # correo o telegram
    Column("nivel", String(20), nullable=False),               # rojo, amarillo, resumen o prueba
    Column("asunto", String(300), nullable=False),
    Column("estado", String(20), nullable=False),              # enviada, fallida o sin_destinatarios
    Column("destinatarios", String(2000)),
    Column("intentos", Integer, nullable=False, default=1),
    Column("error", String(300)),
)


class ErrorUsuarios(Exception):
    """Error con un mensaje para mostrar y el código HTTP que le corresponde."""

    def __init__(self, mensaje, codigo=400):
        super().__init__(mensaje)
        self.mensaje, self.codigo = mensaje, codigo


# ---------------------------------------------------------------------------- contraseñas
def hash_contrasena(contrasena, sal=None, n=SCRYPT["n"], r=SCRYPT["r"], p=SCRYPT["p"]):
    sal = sal or secrets.token_bytes(16)
    h = hashlib.scrypt(contrasena.encode(), salt=sal, n=n, r=r, p=p, dklen=32, maxmem=256 * 1024 * 1024)
    b64 = lambda b: base64.b64encode(b).decode()               # noqa: E731
    return f"scrypt${n}${r}${p}${b64(sal)}${b64(h)}"


def verificar_contrasena(contrasena, guardado):
    try:
        _, n, r, p, sal, h = guardado.split("$")
        otro = hash_contrasena(contrasena, base64.b64decode(sal), int(n), int(r), int(p))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(otro.split("$")[-1], h)


def hash_viejo(guardado):
    """Si el hash se hizo con otros parámetros de scrypt (hay que rehacerlo al entrar)."""
    try:
        _, n, r, p, _, _ = guardado.split("$")
        return (int(n), int(r), int(p)) != (SCRYPT["n"], SCRYPT["r"], SCRYPT["p"])
    except ValueError:
        return True


_FICTICIO = []


def hash_ficticio():
    """Un hash cualquiera, para calcular scrypt también cuando el correo no existe."""
    if not _FICTICIO:
        _FICTICIO.append(hash_contrasena(secrets.token_urlsafe(16)))
    return _FICTICIO[0]


class Intentos:
    """Intentos fallidos recientes por clave (origen, o origen y correo), en memoria. Una clave
    queda bloqueada al llegar a `maximo` fallos dentro de la ventana; los fallos viejos se olvidan."""

    def __init__(self, ventana_s=BLOQUEO_S, tope=10_000):
        self.ventana_s, self.tope = ventana_s, tope
        self._fallos = {}                                        # clave -> [horas de cada fallo]
        self._candado = threading.Lock()

    def _vigentes(self, clave, ahora):
        f = [t for t in self._fallos.get(clave, []) if ahora - t < self.ventana_s]
        if f:
            self._fallos[clave] = f
        else:
            self._fallos.pop(clave, None)
        return f

    def bloqueado(self, clave, maximo):
        with self._candado:
            return len(self._vigentes(clave, time.time())) >= maximo

    def fallo(self, *claves):
        ahora = time.time()
        with self._candado:
            if len(self._fallos) >= self.tope:                   # no crecer sin límite
                for k in list(self._fallos):
                    self._vigentes(k, ahora)
                while len(self._fallos) >= self.tope:
                    self._fallos.pop(next(iter(self._fallos)))
            for clave in claves:
                self._fallos.setdefault(clave, []).append(ahora)

    def olvidar(self, clave):
        with self._candado:
            self._fallos.pop(clave, None)


def validar_contrasena(contrasena):
    if len(contrasena or "") < MINIMO_CONTRASENA:
        raise ErrorUsuarios(f"La contraseña debe tener al menos {MINIMO_CONTRASENA} caracteres.")


def _codigo(texto):
    return hashlib.sha256(texto.encode()).hexdigest()


def _publico(u):
    return {"id": u.id, "nombre": u.nombre, "correo": u.correo, "rol": u.rol, "rol_nombre": ROLES.get(u.rol, u.rol),
            "activo": u.activo, "debe_cambiar": u.debe_cambiar, "notificar_rojo": u.notificar_rojo,
            "notificar_amarillo": u.notificar_amarillo,
            "ultimo_acceso": u.ultimo_acceso.strftime("%Y-%m-%d %H:%M:%S") if u.ultimo_acceso else None}


class Usuarios:
    def __init__(self, url):
        opciones = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {}
        self.motor = create_engine(url, pool_pre_ping=True, **opciones)
        meta.create_all(self.motor)
        self.intentos = Intentos()
        hash_ficticio()                 # listo desde ya: ni el primer correo inexistente tarda distinto

    # ------------------------------------------------------------------ bitácora
    def anotar(self, accion, correo=None, detalle=None, origen=None, conexion=None):
        fila = {"fecha": datetime.now(), "correo": correo, "accion": accion,
                "detalle": (detalle or "")[:500] or None, "origen": origen}
        if conexion is not None:
            conexion.execute(insert(bitacora).values(**fila))
        else:
            with self.motor.begin() as c:
                c.execute(insert(bitacora).values(**fila))

    def ver_bitacora(self, limite=100):
        with self.motor.connect() as c:
            filas = c.execute(select(bitacora).order_by(bitacora.c.id.desc()).limit(limite)).all()
        return [{"fecha": f.fecha.strftime("%Y-%m-%d %H:%M:%S"), "correo": f.correo, "accion": f.accion,
                 "detalle": f.detalle, "origen": f.origen} for f in filas]

    # ------------------------------------------------------------------ usuarios
    def hay_usuarios(self):
        with self.motor.connect() as c:
            return c.execute(select(func.count()).select_from(usuarios)).scalar() > 0

    def lista(self):
        with self.motor.connect() as c:
            return [_publico(u) for u in c.execute(select(usuarios).order_by(usuarios.c.nombre)).all()]

    def _por_id(self, c, uid):
        u = c.execute(select(usuarios).where(usuarios.c.id == uid)).first()
        if u is None:
            raise ErrorUsuarios("No existe ese usuario.", 404)
        return u

    def crear(self, nombre, correo, rol, contrasena, por=None, origen=None, debe_cambiar=True):
        nombre, correo = (nombre or "").strip(), (correo or "").strip().lower()
        if not nombre:
            raise ErrorUsuarios("El nombre es obligatorio.")
        if not CORREO.match(correo):
            raise ErrorUsuarios("El correo no es válido.")
        if rol not in ROLES:
            raise ErrorUsuarios("El rol debe ser operador, administrador o junta.")
        validar_contrasena(contrasena)
        with self.motor.begin() as c:
            if c.execute(select(usuarios.c.id).where(usuarios.c.correo == correo)).first():
                raise ErrorUsuarios("Ya hay un usuario con ese correo.", 409)
            uid = c.execute(insert(usuarios).values(
                nombre=nombre, correo=correo, rol=rol, hash=hash_contrasena(contrasena), activo=True,
                debe_cambiar=debe_cambiar, notificar_rojo=rol != "junta", notificar_amarillo=rol == "operador",
                creado=datetime.now())).inserted_primary_key[0]
            self.anotar("usuario_creado", por, f"{correo} ({ROLES[rol]})", origen, c)
            return _publico(self._por_id(c, uid))

    def modificar(self, uid, cambios, por=None, origen=None):
        """Cambios posibles: nombre, rol, activo, notificar_rojo, notificar_amarillo, contrasena."""
        permitidos = {"nombre", "rol", "activo", "notificar_rojo", "notificar_amarillo", "contrasena"}
        cambios = {k: v for k, v in cambios.items() if k in permitidos and v is not None}
        with self.motor.begin() as c:
            u = self._por_id(c, uid)
            if por and por == u.correo and ({"rol", "activo", "contrasena"} & set(cambios)):
                raise ErrorUsuarios("No puedes cambiar tu propio rol, desactivarte ni restablecer tu contraseña "
                                    "desde aquí: pídeselo a otro administrador o usa Mi cuenta.", 409)
            valores = {}
            if "nombre" in cambios:
                if not str(cambios["nombre"]).strip():
                    raise ErrorUsuarios("El nombre es obligatorio.")
                valores["nombre"] = str(cambios["nombre"]).strip()
            if "rol" in cambios:
                if cambios["rol"] not in ROLES:
                    raise ErrorUsuarios("El rol debe ser operador, administrador o junta.")
                valores["rol"] = cambios["rol"]
            for k in ("activo", "notificar_rojo", "notificar_amarillo"):
                if k in cambios:
                    valores[k] = bool(cambios[k])
            if "contrasena" in cambios:                    # el administrador la restablece
                validar_contrasena(cambios["contrasena"])
                valores.update(hash=hash_contrasena(cambios["contrasena"]), debe_cambiar=True)
            # no dejar la plataforma sin administración (CU-07, flujo 3a)
            deja_de_ser_admin = u.rol == "administrador" and (valores.get("rol", "administrador") != "administrador"
                                                              or valores.get("activo", True) is False)
            if deja_de_ser_admin and u.activo:
                otros = c.execute(select(func.count()).select_from(usuarios).where(
                    usuarios.c.rol == "administrador", usuarios.c.activo.is_(True), usuarios.c.id != uid)).scalar()
                if not otros:
                    raise ErrorUsuarios("No se puede: es el único administrador activo. Crea o activa otro primero.",
                                        409)
            if not valores:
                return _publico(u)
            c.execute(update(usuarios).where(usuarios.c.id == uid).values(**valores))
            if valores.get("activo") is False or "hash" in valores:  # cierra sus sesiones abiertas
                c.execute(sesiones.delete().where(sesiones.c.usuario_id == uid))
            descripcion = ", ".join("contraseña restablecida" if k == "hash" else f"{k}={v}"
                                    for k, v in valores.items() if k != "debe_cambiar")
            self.anotar("usuario_modificado", por, f"{u.correo}: {descripcion}", origen, c)
            return _publico(self._por_id(c, uid))

    def cambiar_propia(self, uid, actual, nueva, origen=None, conservar=None):
        """Cambia la propia contraseña y cierra las demás sesiones de la persona (deja abierta la
        del código `conservar`, la que hizo el cambio)."""
        clave = ("cambio", origen, uid)
        if self.intentos.bloqueado(clave, INTENTOS_MAXIMOS):
            raise ErrorUsuarios("Demasiados intentos fallidos. Espera 15 minutos y vuelve a intentarlo.", 429)
        with self.motor.connect() as c:
            u = self._por_id(c, uid)
        if not verificar_contrasena(actual or "", u.hash):
            self.intentos.fallo(clave)
            raise ErrorUsuarios("La contraseña actual no es correcta.", 403)
        validar_contrasena(nueva)
        if verificar_contrasena(nueva, u.hash):
            raise ErrorUsuarios("La contraseña nueva debe ser distinta de la actual.")
        self.intentos.olvidar(clave)
        with self.motor.begin() as c:
            c.execute(update(usuarios).where(usuarios.c.id == uid).values(hash=hash_contrasena(nueva),
                                                                          debe_cambiar=False))
            otras = sesiones.delete().where(sesiones.c.usuario_id == uid)
            if conservar:
                otras = otras.where(sesiones.c.codigo != _codigo(conservar))
            cerradas = c.execute(otras).rowcount
            self.anotar("contrasena_cambiada", u.correo,
                        f"se cerraron {cerradas} sesiones abiertas en otros lugares" if cerradas else None, origen, c)
            return _publico(self._por_id(c, uid))

    # ------------------------------------------------------------------ sesiones
    def iniciar_sesion(self, correo, contrasena, origen=None):
        """Devuelve (código para la cookie, usuario). Mensaje genérico si algo no coincide (CU-00 4a)."""
        correo = (correo or "").strip().lower()
        par, del_origen = ("par", origen, correo), ("origen", origen)
        if self.intentos.bloqueado(par, INTENTOS_MAXIMOS) or self.intentos.bloqueado(del_origen, INTENTOS_POR_ORIGEN):
            self.anotar("inicio_bloqueado", correo, None, origen)
            raise ErrorUsuarios("Demasiados intentos fallidos. Espera 15 minutos y vuelve a intentarlo.", 429)
        # los rechazos se anotan en la bitácora fuera de la transacción (si no, se desharían)
        with self.motor.connect() as c:
            u = c.execute(select(usuarios).where(usuarios.c.correo == correo)).first()
        # con un correo que no existe se calcula igual scrypt: el tiempo no dice si la cuenta existe
        if not verificar_contrasena(contrasena or "", u.hash if u is not None else hash_ficticio()) or u is None:
            self.intentos.fallo(par, del_origen)
            self.anotar("inicio_fallido", correo, None, origen)
            raise ErrorUsuarios("Correo o contraseña incorrectos.", 401)
        if not u.activo:                                     # CU-00 4b
            self.anotar("inicio_cuenta_inactiva", correo, None, origen)
            raise ErrorUsuarios("Tu cuenta está desactivada. Contacta al administrador de la ASADA.", 403)
        self.intentos.olvidar(par)
        with self.motor.begin() as c:
            codigo = secrets.token_urlsafe(32)
            ahora = datetime.now()
            c.execute(sesiones.delete().where(sesiones.c.vence < ahora))
            c.execute(insert(sesiones).values(codigo=_codigo(codigo), usuario_id=u.id, creada=ahora,
                                              vence=ahora + DURACION_SESION))
            cambios = {"ultimo_acceso": ahora}
            if hash_viejo(u.hash):                           # parámetros de scrypt de antes: se rehace
                cambios["hash"] = hash_contrasena(contrasena)
            c.execute(update(usuarios).where(usuarios.c.id == u.id).values(**cambios))
            self.anotar("inicio_sesion", correo, None, origen, c)
            return codigo, _publico(self._por_id(c, u.id))

    def de_sesion(self, codigo):
        """El usuario de una sesión vigente, o None."""
        if not codigo:
            return None
        with self.motor.connect() as c:
            fila = c.execute(select(usuarios).join(sesiones, sesiones.c.usuario_id == usuarios.c.id).where(
                sesiones.c.codigo == _codigo(codigo), sesiones.c.vence > datetime.now(),
                usuarios.c.activo.is_(True))).first()
        return _publico(fila) if fila else None

    def cerrar_sesion(self, codigo, origen=None):
        u = self.de_sesion(codigo)
        with self.motor.begin() as c:
            c.execute(sesiones.delete().where(sesiones.c.codigo == _codigo(codigo or "")))
            if u:
                self.anotar("cierre_sesion", u["correo"], None, origen, c)

    def destinatarios(self, nivel):
        """Correos que reciben las notificaciones de un nivel ("rojo" o "amarillo"), para el SMTP."""
        col = usuarios.c.notificar_rojo if nivel == "rojo" else usuarios.c.notificar_amarillo
        with self.motor.connect() as c:
            filas = c.execute(select(usuarios.c.correo).where(col.is_(True), usuarios.c.activo.is_(True))
                              .order_by(usuarios.c.correo))
            return [f.correo for f in filas]

    # ------------------------------------------------------------------ notificaciones enviadas
    def anotar_notificacion(self, canal, nivel, asunto, estado, destinatarios=None, intentos=1, error=None):
        with self.motor.begin() as c:
            c.execute(insert(notificaciones).values(
                fecha=datetime.now(), canal=canal, nivel=nivel, asunto=asunto[:300], estado=estado,
                destinatarios=(destinatarios or "")[:2000] or None, intentos=intentos,
                error=(error or "")[:300] or None))

    def ver_notificaciones(self, limite=50):
        with self.motor.connect() as c:
            filas = c.execute(select(notificaciones).order_by(notificaciones.c.id.desc()).limit(limite)).all()
        return [{"fecha": f.fecha.strftime("%Y-%m-%d %H:%M:%S"), "canal": f.canal, "nivel": f.nivel,
                 "asunto": f.asunto, "estado": f.estado, "destinatarios": f.destinatarios,
                 "intentos": f.intentos, "error": f.error} for f in filas]


if __name__ == "__main__":
    import getpass
    import os
    from monitoreo.config import Config
    ap = argparse.ArgumentParser(description="Usuarios del dashboard")
    ap.add_argument("--crear-admin", nargs=2, metavar=("CORREO", "NOMBRE"), help="crear un administrador")
    ap.add_argument("--lista", action="store_true", help="listar los usuarios")
    args = ap.parse_args()
    cfg = Config()
    u = Usuarios(cfg.base_usuarios)
    if args.crear_admin:
        correo, nombre = args.crear_admin
        clave = os.environ.get("CONTRASENA_ADMIN") or getpass.getpass("Contraseña (mínimo 10 caracteres): ")
        if not os.environ.get("CONTRASENA_ADMIN") and clave != getpass.getpass("Repítela: "):
            raise SystemExit("Las contraseñas no coinciden.")
        try:
            r = u.crear(nombre, correo, "administrador", clave, por="consola", debe_cambiar=False)
        except ErrorUsuarios as e:
            raise SystemExit(e.mensaje)
        print(f"Administrador creado: {r['nombre']} <{r['correo']}>")
    elif args.lista:
        for x in u.lista():
            print(f"{x['correo']:35} {x['rol_nombre']:18} {'activo' if x['activo'] else 'inactivo'}")
    else:
        ap.print_help()
