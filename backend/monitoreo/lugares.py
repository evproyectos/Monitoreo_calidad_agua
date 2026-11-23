"""
Nombres de los lugares de medición (vista sencilla del tablero y mensajes de alerta).

Cada sensor tiene un código de la red (J280, J101…) que no dice nada a quien vive en la comunidad.
Aquí se guarda, para cada código, el nombre del lugar ("Escuela") y una zona o referencia
("Centro"). El administrador los cambia desde el tablero (página Lugares); mientras no lo haga, se
usan los nombres de ejemplo de EJEMPLOS, y los sensores que no están ahí se muestran con su código.

Los códigos siguen guardados en las alertas: el nombre se pone al mostrarlas o al enviarlas, así un
cambio de nombre vale también para las alertas de antes.

Se guarda en la misma base que los usuarios (BASE_USUARIOS: PostgreSQL en Docker o SQLite).
"""

import html
import re
import threading
from datetime import datetime

from sqlalchemy import Column, DateTime, MetaData, String, Table, create_engine, delete, insert, select

NOMBRE_MAX, ZONA_MAX = 60, 80
# nombres de ejemplo para los sensores de la red de prueba, de la fuente al final de la red
EJEMPLOS = {
    "J280": ("Tanque de almacenamiento", "Salida de la naciente"),
    "J439": ("Entrada de La Lucha", "Primer tramo de la red"),
    "J237": ("Plaza de deportes", "Centro"),
    "J101": ("Escuela", "Centro"),
    "J1058": ("Salón comunal", "Centro"),
    "J69": ("Iglesia", "Camino a La Vega"),
    "J224": ("Calle a La Vega", "Camino a La Vega"),
    "J345": ("Barrio Los Ángeles", "Ramal norte"),
    "J284": ("Cuesta del cementerio", "Ramal norte"),
    "J144": ("El Carmen", "Final de la red"),
}

meta = MetaData()
lugares = Table(
    "lugares", meta,
    Column("codigo", String(40), primary_key=True),
    Column("nombre", String(NOMBRE_MAX), nullable=False),
    Column("zona", String(ZONA_MAX)),
    Column("actualizado", DateTime, nullable=False),
    Column("por", String(254)),
)


class ErrorLugares(Exception):
    def __init__(self, mensaje, codigo=400):
        super().__init__(mensaje)
        self.mensaje, self.codigo = mensaje, codigo


class Lugares:
    def __init__(self, url):
        opciones = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {}
        self.motor = create_engine(url, pool_pre_ping=True, **opciones)
        meta.create_all(self.motor)
        self._candado = threading.Lock()
        self._guardados = None                          # código -> (nombre, zona); None: leer la base

    def _leer(self):
        with self._candado:
            if self._guardados is None:
                with self.motor.connect() as c:
                    self._guardados = {f.codigo: (f.nombre, f.zona or "") for f in c.execute(select(lugares))}
            return dict(self._guardados)

    def lista(self, codigos):
        """Nombre y zona de cada sensor, en el orden de `codigos`. `propio` dice si lo puso el
        administrador (o si es el de ejemplo o el código)."""
        guardados = self._leer()
        out = []
        for c in codigos:
            if c in guardados:
                nombre, zona = guardados[c]
            else:
                nombre, zona = EJEMPLOS.get(c, (c, ""))
            out.append({"codigo": c, "nombre": nombre, "zona": zona, "propio": c in guardados})
        return out

    def nombres(self, codigos):
        """Código -> nombre, para los mensajes de alerta."""
        return {x["codigo"]: x["nombre"] for x in self.lista(codigos)}

    def guardar(self, cambios, codigos, por=None):
        """Guarda los nombres de los lugares. `cambios`: [{codigo, nombre, zona}]; `codigos`: los
        sensores que existen. Devuelve la lista nueva."""
        validos = set(codigos)
        filas = {}
        for x in cambios:
            codigo = str(x.get("codigo", "")).strip()
            if codigo not in validos:
                raise ErrorLugares(f"No hay ningún sensor {codigo}.")
            nombre = " ".join(str(x.get("nombre") or "").split())
            zona = " ".join(str(x.get("zona") or "").split())
            if not nombre:
                raise ErrorLugares(f"Falta el nombre del lugar del sensor {codigo}.")
            if len(nombre) > NOMBRE_MAX or len(zona) > ZONA_MAX:
                raise ErrorLugares(f"El nombre va hasta {NOMBRE_MAX} caracteres y la zona hasta {ZONA_MAX}.")
            filas[codigo] = (nombre, zona)
        actuales = {x["codigo"]: x["nombre"] for x in self.lista(codigos)}
        actuales.update({c: n for c, (n, _) in filas.items()})
        vistos = {}
        for codigo, nombre in actuales.items():
            otro = vistos.setdefault(nombre.casefold(), codigo)
            if otro != codigo:
                raise ErrorLugares(f"Dos lugares no pueden llamarse igual: «{nombre}» ({otro} y {codigo}).")
        ahora = datetime.now()
        with self._candado, self.motor.begin() as c:
            if filas:
                c.execute(delete(lugares).where(lugares.c.codigo.in_(list(filas))))
                c.execute(insert(lugares), [{"codigo": k, "nombre": n, "zona": z or None, "actualizado": ahora,
                                             "por": por} for k, (n, z) in filas.items()])
            self._guardados = None
        return self.lista(codigos)


def con_nombres(texto, nombres, escapar=True):
    """Cambia cada código de sensor del texto por «Nombre (código)». Con `escapar` el nombre va
    escapado para HTML (los mensajes de correo y Telegram son HTML)."""
    otros = {c: n for c, n in (nombres or {}).items() if n and n != c}
    if not texto or not otros:
        return texto
    patron = re.compile(r"(?<![\w-])(" + "|".join(re.escape(c) for c in sorted(otros, key=len, reverse=True))
                        + r")(?![\w-])")
    return patron.sub(lambda m: f"{html.escape(otros[m.group(1)]) if escapar else otros[m.group(1)]} ({m.group(1)})",
                      texto)
