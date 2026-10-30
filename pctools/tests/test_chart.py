from genband_tools.chart import (
    DIFFICULTIES,
    BeatGrid,
    assign_lanes,
    build_chart,
    estimate_beat,
    merge_attacks,
    reduce_notes,
)
from genband_tools.vgm import Note

def test_estimate_beat_doubles_subdivision():
    onsets = list(range(0, 400, 5))  # semicorcheas cada 5 cuadros
    grid = estimate_beat(onsets)
    assert grid.frames_per_beat == 20
    assert grid.first_beat == 0


def test_reduce_notes_keeps_strong_beats_and_gap():
    grid = BeatGrid(20, 0)
    notes = [Note(f, 60, 5) for f in range(0, 80, 5)]
    kept = reduce_notes(notes, DIFFICULTIES[0], grid)  # fácil: min_gap 24
    # Primero los tiempos (0 y 40; 20 y 60 quedan muy cerca), luego medios tiempos (70)
    assert [n.frame for n in kept] == [0, 40, 70]
    assert all(b.frame - a.frame >= 24 for a, b in zip(kept, kept[1:]))


def test_merge_attacks_keeps_first_frame():
    # Golpe de 1 cuadro + la misma nota sostenida = una nota desde el golpe
    notes = [Note(0, 50, 1), Note(1, 50, 111), Note(120, 50, 10), Note(121, 52, 10)]
    merged = merge_attacks(notes)
    assert [(n.frame, n.pitch, n.duration) for n in merged] == [(0, 50, 112), (120, 50, 10), (121, 52, 10)]


def test_merge_attacks_joins_pitch_sweeps():
    # Barrido de un cuadro por nota (como Double Dragon) y luego una nota normal
    sweep = [Note(10 + i, 53 - 2 * i, 1) for i in range(8)]
    notes = sweep + [Note(20, 45, 8)]
    merged = merge_attacks(notes)
    assert [(n.frame, n.pitch, n.duration) for n in merged] == [(10, 53, 8), (20, 45, 8)]


def test_assign_lanes_follows_contour():
    pitches = [60, 62, 64, 64, 62, 60]
    notes = [Note(i * 10, p, 5) for i, p in enumerate(pitches)]
    lanes = assign_lanes(notes, 5)
    assert lanes[0] < lanes[1] < lanes[2]  # sube
    assert lanes[2] == lanes[3]  # repite nota, repite carril
    assert lanes[3] > lanes[4] > lanes[5]  # baja
    assert all(0 <= lane < 5 for lane in lanes)


def test_chart_entries_use_deltas_and_spacers():
    from genband_tools.chart import ChartNote, chart_entries, chart_size

    chart = [ChartNote(128, 0x01), ChartNote(140, 0x02), ChartNote(800, 0x04)]
    entries = chart_entries(chart)
    # 128; +12; +660 = 255 + 255 + 150 (dos rellenos sin carriles); fin
    assert entries == [(128, 0x01), (12, 0x02), (255, 0), (255, 0), (150, 0x04), (0, 0xFF)]
    assert chart_size(chart) == 12


def test_chart_entries_sustain_flag_and_release():
    from genband_tools.chart import END_FLAG, SUSTAIN_FLAG, ChartNote, chart_entries

    # Una nota con cola en el carril 0 (cuadros 100-160) y otra normal en medio
    chart = [ChartNote(100, 0x01, end=160), ChartNote(130, 0x04)]
    assert chart_entries(chart) == [
        (100, 0x01 | SUSTAIN_FLAG),
        (30, 0x04),
        (30, 0x01 | END_FLAG),
        (0, 0xFF),
    ]


def test_sustain_ends_respects_duration_and_next_note_in_lane():
    from genband_tools.chart import MIN_SUSTAIN, SUSTAIN_GAP, SUSTAIN_TRIM, sustain_ends

    notes = [Note(0, 60, 100), Note(40, 64, 5), Note(200, 60, 10), Note(300, 60, 90)]
    lanes = [0, 1, 0, 0]
    ends = sustain_ends(notes, lanes)
    # la 1ª es larga pero la siguiente en su carril llega en 200: termina por su duración
    assert ends[0] == 100 - SUSTAIN_TRIM
    assert ends[1] is None  # muy corta
    assert ends[2] is None  # 10 cuadros < MIN_SUSTAIN
    assert ends[3] == 300 + 90 - SUSTAIN_TRIM
    # y si la siguiente nota del carril llega antes de que acabe, la cola la deja pasar
    cut = sustain_ends([Note(0, 60, 100), Note(50, 62, 5)], [0, 0])
    assert cut[0] == 50 - SUSTAIN_GAP - SUSTAIN_TRIM
    assert MIN_SUSTAIN <= cut[0]


def test_star_phrases_are_separated_runs():
    from genband_tools.chart import STAR_FIRST, STAR_FLAG, STAR_PHRASE_LEN, STAR_SPACING, ChartNote, chart_entries, star_notes

    stars = star_notes(100)
    runs = []
    for i, star in enumerate(stars):
        if star and (i == 0 or not stars[i - 1]):
            runs.append(i)
    assert runs == list(range(STAR_FIRST, 100 - STAR_PHRASE_LEN, STAR_SPACING))
    assert all(sum(stars[r : r + STAR_PHRASE_LEN]) == STAR_PHRASE_LEN for r in runs)
    assert star_notes(5) == [False] * 5  # canción corta: sin frases

    entries = chart_entries([ChartNote(10, 0x04, star=True), ChartNote(20, 0x01)])
    assert entries[0] == (10, 0x04 | STAR_FLAG)
    assert entries[1] == (10, 0x01)


def test_build_chart_frames_and_lanes():
    grid = BeatGrid(20, 0)
    notes = [Note(0, 60, 5), Note(10, 64, 5), Note(20, 67, 5)]
    chart = build_chart(notes, DIFFICULTIES[-1], grid, lead_in=128)
    assert [n.frame for n in chart] == [128, 138, 148]
    assert all(bin(n.mask).count("1") == 1 and n.mask < 0x20 for n in chart)  # un carril por nota


# --- Acordes y papeles de cada instrumento (#13) ---------------------------------


def _melody(pitches, spacing=40, duration=10):
    return [Note(i * spacing, p, duration) for i, p in enumerate(pitches)]


def test_arpeggio_pitch_detects_broken_chords_but_not_sweeps():
    from genband_tools.chart import arpeggio_pitch

    # Do-mi-sol-mi: un arpegio (3+ notas, varias alturas, sube y baja); el principal es el más largo
    arp = [Note(0, 60, 1), Note(1, 64, 1), Note(2, 67, 1), Note(3, 64, 5)]
    assert arpeggio_pitch(arp, arp[3]) == 60  # la altura más lejana al principal (64): 4 semitonos contra 3
    sweep = [Note(i, 60 + 2 * i, 1) for i in range(5)]  # siempre sube: es un barrido de tono
    assert arpeggio_pitch(sweep, sweep[-1]) is None
    assert arpeggio_pitch([Note(0, 50, 1), Note(1, 60, 5)], Note(1, 60, 5)) is None  # dos notas: un golpe, no un arpegio
    assert merge_attacks(arp)[0].extra is not None


def test_no_chords_on_easy_and_none_for_bass():
    from genband_tools.chart import chord_masks

    grid = BeatGrid(20, 0)
    notes = _melody([60, 62, 64, 65, 67, 69, 71, 72])  # cada 40 cuadros, todas en un tiempo (dos tiempos)
    partner = _melody([64, 66, 67, 69, 71, 73, 74, 76])  # armonía: a una tercera o más arriba, a la vez
    lanes = assign_lanes(notes, 5)
    for difficulty, role, expect in ((DIFFICULTIES[0], "lead", False), (DIFFICULTIES[3], "lead", True), (DIFFICULTIES[3], "bass", False)):
        masks = chord_masks(notes, assign_lanes(notes, difficulty.lanes), difficulty, grid, role, partner)
        assert any(bin(m).count("1") == 2 for m in masks) == expect, (difficulty.name, role)


def test_chords_have_two_adjacent_enough_lanes_and_respect_spacing():
    from genband_tools.chart import chord_masks

    grid = BeatGrid(20, 0)
    notes = _melody([60, 62, 64, 65, 67, 69, 71, 72, 74, 76], spacing=20)
    partner = [Note(n.frame, n.pitch + 4, 10) for n in notes]
    diff = DIFFICULTIES[3]
    lanes = assign_lanes(notes, diff.lanes)
    masks = chord_masks(notes, lanes, diff, grid, "lead", partner)
    chords = [(n.frame, m) for n, m in zip(notes, masks) if m & (m - 1)]
    assert chords, "debería haber acordes"
    for (a, _), (b, _) in zip(chords, chords[1:]):
        assert b - a >= diff.chord_gap
    for _, m in chords:
        assert bin(m).count("1") == 2 and m < 0x20
    # No hay acorde en las dos primeras notas ni entre notas muy pegadas (menos de 2 * min_gap)
    assert masks[0] & (masks[0] - 1) == 0 and masks[1] & (masks[1] - 1) == 0


def test_keys_follow_the_melody_contour_like_the_lead():
    """El teclado reparte sus carriles con un vecindario más amplio (KEYS_WINDOW), pero igual sube cuando
    la melodía sube y repite cuando repite (los carriles que no siguen la melodía se sienten desconectados)."""
    grid = BeatGrid(20, 0)
    rising = _melody([60, 62, 64, 65, 67, 69, 71, 72], spacing=20)
    keys = build_chart(rising, DIFFICULTIES[3], grid, 0, "keys")
    lanes = [n.mask.bit_length() - 1 for n in keys if n.mask & (n.mask - 1) == 0]
    assert lanes == sorted(lanes) and lanes[0] < lanes[-1]
    repeated = build_chart(_melody([60] * 6, spacing=20), DIFFICULTIES[3], grid, 0, "keys")
    assert len({n.mask for n in repeated}) == 1


def test_bass_prefers_the_long_notes_and_keys_the_beat_like_the_lead():
    grid = BeatGrid(20, 0)
    easy = DIFFICULTIES[0]  # solo cabe una nota cada 24 cuadros
    notes = [Note(0, 60, 5), Note(10, 64, 5)]  # un tiempo y un medio tiempo, a 10 cuadros
    assert [n.frame for n in reduce_notes(notes, easy, grid, "lead")] == [0]
    assert [n.frame for n in reduce_notes(notes, easy, grid, "keys")] == [0]
    long_vs_short = [Note(0, 40, 5), Note(0, 43, 60)]
    assert reduce_notes(long_vs_short, easy, grid, "bass")[0].duration == 60


def test_stars_skip_chords_and_keep_phrases_of_four_single_notes():
    from genband_tools.chart import STAR_FIRST, STAR_PHRASE_LEN, star_notes

    chords = [False] * 100
    chords[STAR_FIRST + 2] = True  # un acorde donde empezaría la primera frase
    stars = star_notes(100, chords)
    assert not any(s and c for s, c in zip(stars, chords))
    runs = [i for i, s in enumerate(stars) if s and (i == 0 or not stars[i - 1])]
    assert runs[0] > STAR_FIRST  # se recorrió
    assert all(sum(stars[r : r + STAR_PHRASE_LEN]) == STAR_PHRASE_LEN for r in runs)


def test_sustain_ends_for_chords_wait_for_any_shared_lane():
    from genband_tools.chart import sustain_ends

    notes = [Note(0, 60, 100), Note(40, 62, 5)]
    # el acorde ocupa los carriles 0 y 1; la siguiente nota usa el 1: la cola se corta ahí
    ends = sustain_ends(notes, [(0, 1), 1])
    assert ends[0] is not None and ends[0] < 40
    # si la siguiente usa otro carril, la cola llega hasta el final de la nota
    free = sustain_ends(notes, [(0, 1), 3])
    assert free[0] > ends[0]


def test_blocked_lane_pairs_never_play_together():
    """Izquierda + derecha (carriles 0 y 2) no se pueden apretar a la vez en un control de NES; con ESPEJO
    tampoco 2 y 4 (se vuelven 2 y 0). Ni un acorde ni una nota mientras se sostiene la otra."""
    from genband_tools.chart import BLOCKED_PAIRS, lanes_clash, second_lane, sustain_ends

    assert lanes_clash({0}, {2}) and lanes_clash({2}, {4}) and lanes_clash({2}, {2})
    assert not lanes_clash({0}, {4}) and not lanes_clash({1}, {2}) and not lanes_clash({2}, {3})
    # un acorde nunca elige una pareja bloqueada, desde ningún carril y para ninguna distancia
    for lane in range(5):
        for delta in (-12, -4, 3, 12):
            other = second_lane(lane, 5, delta)
            assert other is None or {lane, other} not in BLOCKED_PAIRS
    # el amarillo (carril 2) con una altura mucho más aguda iría al naranja (4): se queda en el azul
    assert second_lane(2, 5, 9) == 3
    # una cola en el carril 0 se corta antes de una nota en el 2 (y al revés), aunque sean carriles distintos
    notes = [Note(0, 60, 100), Note(50, 64, 5)]
    assert sustain_ends(notes, [0, 2])[0] == 50 - 3 - 4  # SUSTAIN_GAP y SUSTAIN_TRIM
    assert sustain_ends(notes, [2, 0])[0] == 50 - 3 - 4
    assert sustain_ends(notes, [0, 4])[0] == 100 - 4  # 0 y 4 sí se pueden tocar juntos


def test_check_playable_rejects_impossible_charts():
    import pytest

    from genband_tools.chart import ChartNote, check_playable

    check_playable([ChartNote(0, 0b00011), ChartNote(10, 0b10001, end=40), ChartNote(50, 0b00100)])  # sin problema
    with pytest.raises(ValueError):
        check_playable([ChartNote(0, 0b00101)])  # verde + amarillo
    with pytest.raises(ValueError):
        check_playable([ChartNote(0, 0b10100)])  # amarillo + naranja (con espejo serían verde + amarillo)
    with pytest.raises(ValueError):
        check_playable([ChartNote(0, 0b00001, end=40), ChartNote(20, 0b00100)])  # el amarillo cae sosteniendo el verde
