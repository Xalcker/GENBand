"""Charts de GENBand: el generador común está en bandcore (`bandcore.chart`, ahí se explica cómo se arma un chart).

Aquí queda lo propio de la Genesis: escribir cada chart en C para song.c (`chart_to_c`) y contar sus botones.
"""

from __future__ import annotations

# El generador de charts, la nota y las reglas de lo que se puede tocar son los mismos en los cuatro juegos:
# viven en bandcore (aquí se vuelven a exportar para el resto del juego)
from bandcore.chart import (  # noqa: F401
    BLOCKED_PAIRS,
    CHART_END,
    DIFFICULTIES,
    DRUM_BLOCKED_PAIRS,
    END_FLAG,
    KEYS_WINDOW,
    MAX_DELTA,
    MIN_SUSTAIN,
    ROLES,
    STAR_FIRST,
    STAR_FLAG,
    STAR_PHRASE_LEN,
    STAR_SPACING,
    SUSTAIN_FLAG,
    SUSTAIN_GAP,
    SUSTAIN_TRIM,
    BeatGrid,
    ChartNote,
    Difficulty,
    arpeggio_pitch,
    assign_lanes,
    build_chart,
    chart_entries,
    chart_size,
    check_playable,
    chord_masks,
    estimate_beat,
    lanes_clash,
    merge_attacks,
    reduce_notes,
    second_lane,
    star_notes,
    sustain_ends,
)


def chart_to_c(label: str, chart: list[ChartNote]) -> str:
    lines = [f"static const u8 {label}[] = {{"]
    entries = chart_entries(chart)
    for i in range(0, len(entries), 8):
        lines.append("    " + " ".join(f"{d:3d},0x{m:02X}," for d, m in entries[i : i + 8]))
    lines.append("};")
    return "\n".join(lines) + "\n"


def chart_buttons(chart: list[ChartNote]) -> int:
    """Notas del chart como las cuenta el juego: cada botón de un acorde es una nota."""
    return sum(bin(n.mask & 0x1F).count("1") for n in chart)
