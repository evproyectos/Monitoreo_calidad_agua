"""
Gestión de las alertas (CU-06): cada alarma, posible fuga, aviso anticipado o riesgo en 24 h que
genera el motor queda registrado como una alerta que el personal reconoce, atiende y cierra.

Estados
  nueva        la creó el sistema; nadie la ha tomado
  en_atencion  alguien la reconoció y es su responsable; se le agregan las acciones y observaciones
  cerrada      con su resultado:
                 confirmada   el evento ocurrió (verificado en campo o en el laboratorio)
                 descartada   falso positivo: no había evento
                 inconclusa   no se pudo verificar; no cuenta para evaluar el modelo
                 automatica   aviso predictivo (amarillo) que nadie tomó y cuyo riesgo bajó solo del
                              umbral (RF-003.3, criterio 3); tampoco cuenta para evaluar el modelo

Deduplicación (RF-003.3 y CU-04 paso 2): mientras una alerta del mismo grupo (la alarma de la red, la
fuga, el aviso de cada tipo de evento o el riesgo de cada sensor y parámetro) siga activa, no se crea
otra: se actualiza su probabilidad. Así, al reiniciar el servicio y volver a procesar las horas, no se
duplican alertas ni se reenvían correos.

Historial inmutable: cada cambio (creada, reconocida, nota, terminó, cerrada) es una fila nueva en
alertas_historial, con fecha, quién y qué; nunca se modifica ni se borra.

Se guarda en la misma base que los usuarios (BASE_USUARIOS: PostgreSQL en Docker o SQLite).
"""

import re
from datetime import datetime, timedelta

from sqlalchemy import (Column, DateTime, Float, Integer, MetaData, String, Table, create_engine, insert, literal,
                        select, update)

RESULTADOS = {"confirmada": "Confirmada", "descartada": "Falso positivo", "inconclusa": "Inconclusa",
              "automatica": "Se resolvió sola"}
ESTADOS = {"nueva": "Nueva", "en_atencion": "En atención", "cerrada": "Cerrada"}
TIPOS = {"alarma": "Alarma", "fuga": "Posible fuga", "aviso": "Aviso anticipado", "riesgo": "Riesgo en 24 h"}
MINIMO_OBSERVACION = 5

meta = MetaData()
alertas = Table(
    "alertas", meta,
    Column("id", Integer, primary_key=True),
    Column("clave", String(120), nullable=False, unique=True),      # grupo + hora de inicio
    Column("grupo", String(80), nullable=False),                    # para no duplicar mientras siga activa
    Column("tipo", String(20), nullable=False),                     # alarma, fuga, aviso o riesgo
    Column("evento", String(40)),                                   # contaminacion, falla_cloro, fuga, CL2...
    Column("nivel", String(10), nullable=False),                    # rojo o amarillo
    Column("titulo", String(200), nullable=False),
    Column("lugar", String(300)),                                   # sensores o tramo, en palabras
    Column("nodos", String(300)),                                   # J10,J20 (para filtrar por nodo)
    Column("probabilidad", Float),
    Column("antelacion_h", Integer, nullable=False, default=0),
    Column("parametros", String(500)),
    Column("accion", String(500)),
    Column("inicio", DateTime, nullable=False),                     # hora de los datos
    Column("fin", DateTime),                                        # cuando el sistema dejó de verlo
    Column("estado", String(20), nullable=False, default="nueva"),
    Column("responsable", String(254)),
    Column("responsable_nombre", String(120)),
    Column("resultado", String(20)),
    Column("creada", DateTime, nullable=False),
    Column("cerrada", DateTime),
)
historial = Table(
    "alertas_historial", meta,
    Column("id", Integer, primary_key=True),
    Column("alerta_id", Integer, nullable=False, index=True),
    Column("fecha", DateTime, nullable=False),
    Column("correo", String(254)),                                  # None: el sistema
    Column("nombre", String(120)),
    Column("accion", String(30), nullable=False),
    Column("texto", String(2000)),
)


class ErrorGestion(Exception):
    def __init__(self, mensaje, codigo=400):
        super().__init__(mensaje)
        self.mensaje, self.codigo = mensaje, codigo


def _f(t):
    return t.strftime("%Y-%m-%d %H:%M:%S") if t else None


def _alerta(a):
    return {"id": a.id, "tipo": a.tipo, "tipo_nombre": TIPOS.get(a.tipo, a.tipo), "evento": a.evento,
            "nivel": a.nivel, "titulo": a.titulo, "lugar": a.lugar, "nodos": a.nodos.split(",") if a.nodos else [],
            "probabilidad": a.probabilidad, "antelacion_h": a.antelacion_h, "parametros": a.parametros,
            "accion": a.accion, "inicio": _f(a.inicio), "fin": _f(a.fin), "activa": a.fin is None,
            "estado": a.estado, "estado_nombre": ESTADOS[a.estado], "responsable": a.responsable,
            "responsable_nombre": a.responsable_nombre, "resultado": a.resultado,
            "resultado_nombre": RESULTADOS.get(a.resultado), "creada": _f(a.creada), "cerrada": _f(a.cerrada)}


class GestionAlertas:
    def __init__(self, url):
        opciones = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {}
        self.motor = create_engine(url, pool_pre_ping=True, **opciones)
        meta.create_all(self.motor)

    def _anotar(self, c, alerta_id, accion, texto=None, usuario=None):
        c.execute(insert(historial).values(alerta_id=alerta_id, fecha=datetime.now(), accion=accion,
                                           texto=(texto or "")[:2000] or None,
                                           correo=usuario["correo"] if usuario else None,
                                           nombre=usuario["nombre"] if usuario else None))

    # ------------------------------------------------------------------ lo que hace el sistema
    def abrir(self, grupo, inicio, tipo, nivel, titulo, evento=None, lugar=None, nodos=(), probabilidad=None,
              antelacion_h=0, parametros=None, accion=None):
        """Crea la alerta, o actualiza la que siga activa del mismo grupo. Devuelve (id, es_nueva):
        solo una alerta nueva se notifica."""
        inicio = datetime.fromisoformat(str(inicio))
        clave = f"{grupo}:{inicio:%Y-%m-%d %H:%M}"
        with self.motor.begin() as c:
            ya = c.execute(select(alertas).where(alertas.c.clave == clave)).first() or c.execute(
                select(alertas).where(alertas.c.grupo == grupo, alertas.c.fin.is_(None),
                                      alertas.c.estado != "cerrada").order_by(alertas.c.id.desc())).first()
            if ya is not None:
                if probabilidad is not None and (ya.probabilidad is None or probabilidad > ya.probabilidad):
                    c.execute(update(alertas).where(alertas.c.id == ya.id).values(probabilidad=probabilidad))
                return ya.id, False
            uid = c.execute(insert(alertas).values(
                clave=clave, grupo=grupo, tipo=tipo, evento=evento, nivel=nivel, titulo=titulo[:200],
                lugar=(lugar or "")[:300] or None, nodos=",".join(nodos)[:300] or None, probabilidad=probabilidad,
                antelacion_h=antelacion_h, parametros=(parametros or "")[:500] or None,
                accion=(accion or "")[:500] or None, inicio=inicio, estado="nueva",
                creada=datetime.now())).inserted_primary_key[0]
            self._anotar(c, uid, "creada", "Nivel crítico (rojo)." if nivel == "rojo"
                         else "Nivel predictivo (amarillo).")
        return uid, True

    def terminar(self, grupo, hora):
        """El sistema dejó de ver el evento. Un aviso predictivo que nadie tomó se cierra solo.
        Devuelve los id de las alertas que terminaron."""
        hora = datetime.fromisoformat(str(hora))
        with self.motor.begin() as c:
            activas = c.execute(select(alertas).where(alertas.c.grupo == grupo, alertas.c.fin.is_(None))).all()
            for a in activas:
                cambios = {"fin": hora}
                if a.nivel == "amarillo" and a.estado == "nueva":
                    cambios.update(estado="cerrada", resultado="automatica", cerrada=datetime.now())
                    texto = "El riesgo bajó del umbral antes de que alguien la tomara."
                    accion = "cerrada_sola"
                else:
                    texto, accion = f"Última hora con el evento: {hora:%d/%m/%Y %H:%M}.", "termino"
                c.execute(update(alertas).where(alertas.c.id == a.id).values(**cambios))
                self._anotar(c, a.id, accion, texto)
        return [a.id for a in activas]

    # ------------------------------------------------------------------ consultas
    def lista(self, estado=None, tipo=None, nodo=None, desde=None, hasta=None, limite=200):
        q = select(alertas)
        if estado == "pendientes":
            q = q.where(alertas.c.estado != "cerrada")
        elif estado:
            q = q.where(alertas.c.estado == estado)
        if tipo:
            q = q.where(alertas.c.tipo == tipo)
        if nodo and re.fullmatch(r"[\w-]+", nodo):
            q = q.where((literal(",") + alertas.c.nodos + literal(",")).like(f"%,{nodo},%"))
        if desde:
            q = q.where(alertas.c.inicio >= datetime.fromisoformat(str(desde)))
        if hasta:
            q = q.where(alertas.c.inicio < datetime.fromisoformat(str(hasta)) + timedelta(days=1))
        # primero lo que falta atender, las rojas antes que las amarillas, y lo más reciente
        orden = [(alertas.c.estado == "cerrada").asc(), (alertas.c.nivel == "rojo").desc(), alertas.c.inicio.desc()]
        with self.motor.connect() as c:
            return [_alerta(a) for a in c.execute(q.order_by(*orden).limit(limite)).all()]

    def detalle(self, uid):
        with self.motor.connect() as c:
            a = c.execute(select(alertas).where(alertas.c.id == uid)).first()
            if a is None:
                raise ErrorGestion("No existe esa alerta.", 404)
            h = c.execute(select(historial).where(historial.c.alerta_id == uid).order_by(historial.c.id)).all()
        return {**_alerta(a), "historial": [{"fecha": _f(x.fecha), "correo": x.correo, "nombre": x.nombre,
                                             "accion": x.accion, "texto": x.texto} for x in h]}

    def indicadores(self, dias=30):
        """Para el encabezado de la página: lo pendiente y cómo resultaron las cerradas."""
        desde = datetime.now() - timedelta(days=dias)
        with self.motor.connect() as c:
            filas = c.execute(select(alertas.c.estado, alertas.c.nivel, alertas.c.resultado, alertas.c.cerrada)).all()
        pend = [f for f in filas if f.estado != "cerrada"]
        cerradas = [f for f in filas if f.estado == "cerrada" and f.cerrada and f.cerrada >= desde]
        por = {r: sum(1 for f in cerradas if f.resultado == r) for r in RESULTADOS}
        evaluables = por["confirmada"] + por["descartada"]
        return {"nuevas": sum(1 for f in pend if f.estado == "nueva"),
                "rojas_sin_atender": sum(1 for f in pend if f.estado == "nueva" and f.nivel == "rojo"),
                "en_atencion": sum(1 for f in pend if f.estado == "en_atencion"),
                "pendientes": len(pend), "dias": dias, "cerradas": len(cerradas), "por_resultado": por,
                # de las verificadas en campo, cuántas eran eventos reales (insumo para validar el modelo)
                "confirmadas_pct": round(100 * por["confirmada"] / evaluables) if evaluables else None}

    # ------------------------------------------------------------------ lo que hace el personal
    def _vigente(self, c, uid):
        a = c.execute(select(alertas).where(alertas.c.id == uid).with_for_update()).first()
        if a is None:
            raise ErrorGestion("No existe esa alerta.", 404)
        if a.estado == "cerrada":
            raise ErrorGestion("Esta alerta ya está cerrada.", 409)
        return a

    def reconocer(self, uid, usuario):
        with self.motor.begin() as c:
            a = self._vigente(c, uid)
            if a.estado == "en_atencion":
                if a.responsable == usuario["correo"]:
                    return self.detalle(uid)
                raise ErrorGestion(f"Ya la atiende {a.responsable_nombre}. Puedes agregarle observaciones.", 409)
            c.execute(update(alertas).where(alertas.c.id == uid).values(
                estado="en_atencion", responsable=usuario["correo"], responsable_nombre=usuario["nombre"]))
            self._anotar(c, uid, "reconocida", None, usuario)
        return self.detalle(uid)

    def nota(self, uid, usuario, texto):
        texto = (texto or "").strip()
        if len(texto) < MINIMO_OBSERVACION:
            raise ErrorGestion("Escribe qué se hizo o qué se encontró.")
        with self.motor.begin() as c:
            self._vigente(c, uid)
            self._anotar(c, uid, "nota", texto, usuario)
        return self.detalle(uid)

    def cerrar(self, uid, usuario, resultado, observaciones):
        observaciones = (observaciones or "").strip()
        if resultado not in ("confirmada", "descartada", "inconclusa"):
            raise ErrorGestion("Indica el resultado: confirmada, falso positivo o inconclusa.")
        if len(observaciones) < MINIMO_OBSERVACION:
            raise ErrorGestion("Las observaciones son obligatorias: qué se revisó y qué se encontró.")
        with self.motor.begin() as c:
            a = self._vigente(c, uid)
            cambios = {"estado": "cerrada", "resultado": resultado, "cerrada": datetime.now()}
            if a.responsable is None:
                cambios.update(responsable=usuario["correo"], responsable_nombre=usuario["nombre"])
            c.execute(update(alertas).where(alertas.c.id == uid).values(**cambios))
            self._anotar(c, uid, "cerrada", f"{RESULTADOS[resultado]}. {observaciones}", usuario)
        return self.detalle(uid)
