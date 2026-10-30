import re

from genband_tools import cli, escenario, graficos

SRC = cli.ROOT / "src"


def test_generated_files_are_up_to_date(tmp_path):
    """src/gfx_data.c, stage_gfx.c y trap_gfx.c son lo que generan graficos.py y escenario.py (si cambias
    un dibujo, corre `genband build-gfx`)."""
    graficos.write_c(graficos.build(), tmp_path / "gfx_data.c")
    escenario.write_c(escenario.build(), tmp_path / "stage_gfx.c")
    graficos.write_trap_c(tmp_path / "trap_gfx.c")
    for name in ("gfx_data.c", "stage_gfx.c", "trap_gfx.c"):
        assert (tmp_path / name).read_text() == (SRC / name).read_text(), f"{name} no está al día: genband build-gfx"


def test_everything_fits_in_vram():
    # De TILE_USER_INDEX (16) a la fuente (1440): los gráficos, el escenario y el trapecio más grande
    fixed = sum(len(t) for t in graficos.build().values())
    stage = escenario.build()
    stage_tiles = len(stage["tiles"]) + len(stage["crowd"][0])
    trap = max(len(graficos.trapezoid(hw)[0]) for hw in graficos.LAYOUTS)
    assert 16 + fixed + stage_tiles + trap <= 1440
    assert len(stage["tiles"]) < 0x7FF        # (el número de tile va en 11 bits del mapa)


def test_crowd_size_matches_the_c_side():
    header = (SRC / "genband.h").read_text()
    w = int(re.search(r"#define STAGE_CROWD_W\s+(\d+)", header).group(1))
    h = int(re.search(r"#define STAGE_CROWD_H\s+(\d+)", header).group(1))
    assert (w, h) == (escenario.CROWD_W, escenario.CROWD_H)


def test_gfx_groups_match_the_c_declarations():
    header = (SRC / "genband.h").read_text()
    for name, tiles in graficos.build().items():
        assert re.search(rf"gfx_{name}\[{len(tiles)} \* 8\]", header), f"gfx_{name}: {len(tiles)} tiles"


def test_trapezoid_edges_follow_the_perspective():
    # 1 jugador: en la línea de los aros (184) la autopista mide 160 px (5 carriles de 32), centrada
    line = graficos.trap_line(184, ((160, 5, 32),))
    inside = [x for x, p in enumerate(line) if p != graficos.TRAP_OUT]
    assert inside[0] == 80 and inside[-1] == 240
    # y arriba (línea 24) el 40% del ancho
    line = graficos.trap_line(24, ((160, 5, 32),))
    inside = [x for x, p in enumerate(line) if p != graficos.TRAP_OUT]
    assert abs((inside[-1] - inside[0]) - 64) <= 2
