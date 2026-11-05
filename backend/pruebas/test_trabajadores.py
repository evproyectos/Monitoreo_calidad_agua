"""Predicciones a pedido en procesos aparte (trabajadores.py): mismas respuestas que en el proceso."""

import pytest

from conftest import ModelosFalsos, configuracion
from monitoreo import prediccion, trabajadores
from monitoreo.prediccion import ErrorEntrada
from test_prediccion import HISTORIA_H, solicitud


def fabrica(carpeta, modo):
    """Se llama dentro de cada trabajador (debe poder importarse desde otro proceso)."""
    m = ModelosFalsos()
    m.firma = ("archivos", carpeta)
    return m


@pytest.fixture(scope="module")
def grupo(tmp_path_factory):
    t = trabajadores.Trabajadores(tmp_path_factory.mktemp("modelos"), "combinado", 2, fabrica=fabrica)
    yield t
    t.cerrar()


def test_misma_respuesta_que_en_el_proceso(grupo):
    aqui = prediccion.predecir(solicitud(7), fabrica(None, None), HISTORIA_H, 0.5)
    alla = grupo.atender("contaminacion", solicitud(7), None, HISTORIA_H, 0.5)
    for r in (aqui, alla):
        r.pop("duracion_ms")
    assert alla == aqui


def test_error_de_entrada_llega_intacto(grupo):
    with pytest.raises(ErrorEntrada) as e:
        grupo.atender("contaminacion", solicitud(3), None, HISTORIA_H, 0.5)      # poca historia
    assert "Sin datos suficientes" in e.value.error and e.value.detalles


def test_por_defecto_entre_uno_y_tres():
    assert 1 <= trabajadores.cuantos_por_defecto() <= 3


def test_servicio_predice_en_su_proceso_si_el_trabajador_falla(tmp_path, monkeypatch):
    import monitoreo.servicio as srv
    from monitoreo.motor import Motor
    modelos = ModelosFalsos()
    monkeypatch.setattr(srv, "Motor", lambda cfg: Motor(cfg, modelos, registrar=False))
    s = srv.Servicio(configuracion(tmp_path, historia_h=HISTORIA_H))

    class Roto:
        def atender(self, *a, **k):
            raise RuntimeError("se cayó")

    s.trabajadores = Roto()
    r = s.predecir("contaminacion", solicitud(7))
    assert r["sensores"] and "se cayó" in s.error_trabajadores
