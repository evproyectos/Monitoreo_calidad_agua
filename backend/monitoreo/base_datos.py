"""
Resultados del servicio en una base de datos (opcional).

Con la variable de entorno BASE_DE_DATOS (una URL de SQLAlchemy, p. ej.
postgresql://usuario:clave@servidor:5432/monitoreo) el motor guarda, además de los CSV de la
sesión, cada fila que escribe en una tabla con el mismo nombre: pronosticos, deteccion, alarmas,
anticipacion y fugas. Cada fila lleva la sesión del servicio que la escribió.

En PostgreSQL con TimescaleDB, las tablas que tienen la columna `fecha` se convierten en
hipertablas (series de tiempo particionadas por fecha). Sin TimescaleDB, o con SQLite (las
pruebas), quedan como tablas normales.
"""

import pandas as pd
from sqlalchemy import create_engine, inspect, text


class BaseDatos:
    def __init__(self, url, sesion):
        self.motor = create_engine(url, pool_pre_ping=True)
        self.sesion = sesion
        self.timescale = False
        if self.motor.dialect.name == "postgresql":
            with self.motor.begin() as c:
                try:
                    c.execute(text("CREATE EXTENSION IF NOT EXISTS timescaledb"))
                    self.timescale = True
                except Exception:             # PostgreSQL sin la extensión: tablas normales
                    self.timescale = False
        self._creadas = set(inspect(self.motor).get_table_names())

    def escribir(self, tabla, filas):
        if not filas:
            return
        d = pd.DataFrame(filas)
        for c in ("fecha", "fecha_pronosticada", "inicio", "fin"):
            if c in d:
                d[c] = pd.to_datetime(d[c], errors="coerce")
        d.insert(0, "sesion", self.sesion)
        nueva = tabla not in self._creadas
        d.to_sql(tabla, self.motor, if_exists="append", index=False)
        if nueva:
            self._creadas.add(tabla)
            if self.timescale and "fecha" in d:
                with self.motor.begin() as c:
                    c.execute(text(f"SELECT create_hypertable('{tabla}', 'fecha', if_not_exists => TRUE, "
                                   "migrate_data => TRUE)"))

    def contar(self, tabla):
        with self.motor.connect() as c:
            return c.execute(text(f"SELECT COUNT(*) FROM {tabla}")).scalar()
