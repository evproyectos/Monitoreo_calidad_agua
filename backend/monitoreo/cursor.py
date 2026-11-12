"""
Cursor persistente del procesamiento (RNF-002): la última hora que el servicio procesó, guardada en
la base de datos (la misma de los usuarios y las alertas).

Junto con la API de datos, que guarda las lecturas que mandan los sensores, forma una cola de trabajo
persistente: las lecturas esperan en la API hasta que el servicio las procesa, y el cursor dice hasta
dónde llegó. Si la API de datos o el servicio se caen (2 h o más), al volver se procesan en orden
todas las horas que quedaron pendientes, sin saltarse ninguna; si el servicio se reinicia, sigue con
la hora siguiente al cursor en vez de procesar otra vez toda la historia.
"""

from datetime import datetime

import pandas as pd
from sqlalchemy import Column, DateTime, MetaData, String, Table, delete, insert, select

meta = MetaData()
estado = Table(
    "estado_servicio", meta,
    Column("clave", String(60), primary_key=True),
    Column("valor", String(200), nullable=False),
    Column("actualizado", DateTime, nullable=False),
)


class Cursor:
    def __init__(self, motor_bd, clave="ultima_hora_procesada"):
        self.motor, self.clave = motor_bd, clave
        meta.create_all(self.motor)

    def leer(self):
        with self.motor.connect() as c:
            v = c.execute(select(estado.c.valor).where(estado.c.clave == self.clave)).scalar()
        return None if v is None else pd.Timestamp(v)

    def guardar(self, hora):
        with self.motor.begin() as c:
            c.execute(delete(estado).where(estado.c.clave == self.clave))
            c.execute(insert(estado).values(clave=self.clave, valor=pd.Timestamp(hora).isoformat(),
                                            actualizado=datetime.now()))
