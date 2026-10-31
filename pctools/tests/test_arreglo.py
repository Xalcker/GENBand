"""Pruebas de audio/arreglo_fm.py: notas de otra consola a un VGM con sonidos FM."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "audio"))

import arreglo_fm  # noqa: E402

from genband_tools.vgm import read_vgm  # noqa: E402

NOTAS = {
    "title": "Prueba", "game": "Juego", "frames": 240,
    "channels": {
        "Square1": [[0, 30, 72, 13], [30, 30, 76, 6]],
        "Square2": [[0, 60, 64, 10]],
        "Triangle": [[0, 1, 40, 15], [60, 30, 43, 0]],  # una nota de 1 cuadro y una muda
    },
    "drums": [[0, "kick", False], [30, "snare", False], [30, "tom1", True], [60, "tom2", False]],
}


@pytest.mark.parametrize("timbre", list(arreglo_fm.TIMBRES))
def test_arreglo_toca_cada_canal_y_la_bateria(tmp_path, timbre):
    ruta = tmp_path / "x.vgm"
    arreglo_fm.arreglar(NOTAS, timbre, ruta)
    vgm = read_vgm(ruta)
    # Key-on (registro $28 con los 4 operadores) de FM 1, 2 y 3 y del bombo en el FM 6 (código 6)
    key_on = {w.value & 0x07 for w in vgm.writes if w.chip == "ym0" and w.reg == 0x28 and w.value & 0xF0}
    assert key_on == {0, 1, 2, 6}
    # La nota muda del triángulo no suena: un solo ataque en el FM 3
    assert sum(1 for w in vgm.writes if w.chip == "ym0" and w.reg == 0x28 and w.value == 0xF2) == 1
    assert any(w.chip == "psg" for w in vgm.writes)  # tarola y platillo en el ruido
    assert vgm.tags["title"] == "Prueba" and vgm.tags["author"] == "arreglo de Juego"


def test_volumen_bajo_atenua_los_portadores():
    sonido = arreglo_fm.sonidos.GUITARRA
    bajo = arreglo_fm.atenuado(sonido, 10)
    for i, (op, op2) in enumerate(zip(sonido.ops, bajo.ops)):
        portador = i in arreglo_fm.PORTADORES[sonido.alg]
        assert op2.tl == min(127, op.tl + 10) if portador else op2.tl == op.tl
