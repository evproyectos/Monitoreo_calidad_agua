"""docker/preparar.py: descarga del release solo lo que falta, comprueba la huella y no pisa nada."""

import hashlib
import importlib.util
import json
import zipfile
from pathlib import Path

import pytest

RUTA = Path(__file__).resolve().parents[2] / "docker" / "preparar.py"


@pytest.fixture
def preparar(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location("preparar", RUTA)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    modelo = tmp_path / "Modelo_calidad_agua"
    modelo.mkdir()
    monkeypatch.setattr(mod, "MODELO", modelo)
    monkeypatch.setattr(mod, "ESPERAS_S", [0, 0, 0])
    return mod


def _release(tmp_path, modelo, archivos, obligatorio=True):
    """Arma modelos.zip en una carpeta 'release' y el artefactos.json que lo nombra."""
    release = tmp_path / "release"
    release.mkdir(exist_ok=True)
    zip_ = release / "modelos.zip"
    with zipfile.ZipFile(zip_, "w") as z:
        for nombre, datos in archivos.items():
            z.writestr(nombre, datos)
    manifiesto = {"release": "modelos-prueba", "url": release.as_uri(), "archivos": [{
        "nombre": "modelos.zip", "destino": "modelos", "obligatorio": obligatorio,
        "sha256": hashlib.sha256(zip_.read_bytes()).hexdigest(), "bytes": zip_.stat().st_size,
        "contenido": {n: hashlib.sha256(d).hexdigest() for n, d in archivos.items()}}]}
    (modelo / "artefactos.json").write_text(json.dumps(manifiesto), encoding="utf-8")
    return zip_


def _correr(mod):
    with pytest.raises(SystemExit) as fin:
        mod.main()
    return fin.value.code


def test_descarga_lo_que_falta_y_la_segunda_vez_no_hace_nada(preparar, tmp_path, capsys):
    _release(tmp_path, preparar.MODELO, {"a.joblib": b"modelo a", "b.keras": b"modelo b"})
    assert _correr(preparar) == 0
    assert (preparar.MODELO / "modelos" / "a.joblib").read_bytes() == b"modelo a"
    capsys.readouterr()
    assert _correr(preparar) == 0
    assert "ya está en la carpeta" in capsys.readouterr().out


def test_no_reemplaza_los_modelos_de_esta_maquina(preparar, tmp_path, capsys):
    _release(tmp_path, preparar.MODELO, {"a.joblib": b"modelo a", "b.keras": b"modelo b"})
    carpeta = preparar.MODELO / "modelos"
    carpeta.mkdir()
    (carpeta / "a.joblib").write_bytes(b"reentrenado aqui")
    assert _correr(preparar) == 0                       # falta b: descarga, pero a se queda
    assert (carpeta / "a.joblib").read_bytes() == b"reentrenado aqui"
    assert (carpeta / "b.keras").read_bytes() == b"modelo b"
    assert _correr(preparar) == 0
    assert "distinto del release en 1 archivo" in capsys.readouterr().out


def test_huella_distinta_no_descomprime(preparar, tmp_path, capsys):
    zip_ = _release(tmp_path, preparar.MODELO, {"a.joblib": b"modelo a"})
    zip_.write_bytes(zip_.read_bytes()[:-10])          # descarga cortada o archivo cambiado
    assert _correr(preparar) == 1
    assert "huella SHA-256 no coincide" in capsys.readouterr().out
    assert not (preparar.MODELO / "modelos" / "a.joblib").exists()


def test_sin_release_falla_si_es_obligatorio_y_avisa_si_no(preparar, tmp_path, capsys, monkeypatch):
    _release(tmp_path, preparar.MODELO, {"a.joblib": b"modelo a"})
    monkeypatch.setenv("ARTEFACTOS_URL", (tmp_path / "no_existe").as_uri())
    assert _correr(preparar) == 1
    assert "no se pudo descargar" in capsys.readouterr().out
    _release(tmp_path, preparar.MODELO, {"a.joblib": b"modelo a"}, obligatorio=False)
    assert _correr(preparar) == 0
    assert "no hace falta para el servicio" in capsys.readouterr().out


def test_rechaza_rutas_fuera_de_la_carpeta(preparar, tmp_path):
    zip_ = tmp_path / "malo.zip"
    with zipfile.ZipFile(zip_, "w") as z:
        z.writestr("../afuera.txt", b"x")
    with pytest.raises(RuntimeError, match="fuera de la carpeta"):
        preparar.descomprimir(zip_, preparar.MODELO)
    assert not (preparar.MODELO.parent / "afuera.txt").exists()


def test_sin_artefactos_json_explica(preparar):
    with pytest.raises(SystemExit, match="artefactos.json"):
        preparar.main()
