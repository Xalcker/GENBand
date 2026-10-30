import math

from genband_tools import vgm
from genband_tools.vgm import VgmWriter, Write, extract_notes, frame_stream, read_vgm


def fm_note_writes(frame, ch, block, fnum, frames):
    """Escrituras de una nota FM: altura, key-on y key-off `frames` cuadros después."""
    port = "ym0" if ch < 3 else "ym1"
    c = ch % 3
    code = ch if ch < 3 else ch + 1
    return [
        (frame, Write(0, port, 0xA4 + c, (block << 3) | (fnum >> 8))),
        (frame, Write(0, port, 0xA0 + c, fnum & 0xFF)),
        (frame, Write(0, "ym0", 0x28, 0xF0 | code)),
        (frame + frames, Write(0, "ym0", 0x28, code)),
    ]


def test_writer_and_reader_round_trip(tmp_path):
    w = VgmWriter()
    w.ym(0, 0x28, 0x00)
    w.wait_frames(2)
    w.psg(0x9F)
    w.ym(1, 0xA0, 0x12)
    w.wait_frames(1)
    path = tmp_path / "x.vgm"
    path.write_bytes(w.to_bytes("Titulo", "Juego", "Autor"))
    data = read_vgm(path)
    assert [(vgm.frame_of(x.sample), x.chip, x.reg, x.value) for x in data.writes] == [
        (0, "ym0", 0x28, 0x00),
        (2, "psg", 0, 0x9F),
        (2, "ym1", 0xA0, 0x12),
    ]
    assert data.total_samples == 3 * 735
    assert data.tags["title"] == "Titulo" and data.tags["game"] == "Juego"


def test_frame_stream_waits_and_skips_repeated_registers():
    writes = [
        (0, Write(0, "ym0", 0x40, 5)),
        (0, Write(0, "ym0", 0x40, 5)),  # repetido: se omite
        (1, Write(0, "ym0", 0x28, 0xF0)),
        (1, Write(0, "ym0", 0x28, 0xF0)),  # el key-on nunca se omite
        (20, Write(0, "psg", 0, 0x90)),
        (20, Write(0, "ym0", 0x2A, 0x80)),  # el DAC no va
    ]
    stream, frames, loop = frame_stream(writes, 30)
    assert frames == 30 and loop is None
    body = stream[: stream.index(bytes((0x52, 0x28, 0x00)) + bytes((0x52, 0x28, 0x01)))]
    assert body == bytes(
        [0x52, 0x40, 5, 0x62, 0x52, 0x28, 0xF0, 0x52, 0x28, 0xF0, 0x61, 18, 0, 0x50, 0x90, 0x7A - 0x01]
    )
    assert stream[-1] == 0x66


def test_frame_stream_loop_offset_points_at_the_loop_frame():
    writes = [(0, Write(0, "psg", 0, 0x90)), (10, Write(0, "psg", 0, 0x91))]
    stream, _, loop = frame_stream(writes, 20, loop_frame=10)
    assert stream[loop : loop + 2] == bytes((0x50, 0x91))
    assert stream[-1] == 0x66 and bytes((0x50, 0x9F)) not in stream  # con bucle no se calla al final


def test_extract_fm_notes_pitch_and_duration():
    # La 440: F-number 1084 en el bloque 4 (con el reloj NTSC)
    writes = fm_note_writes(10, 0, 4, 1084, 20) + fm_note_writes(40, 4, 4, 1084 * 2 // 2, 5)
    notes = extract_notes(sorted(writes, key=lambda x: x[0]))
    assert [(n.frame, n.pitch, n.duration) for n in notes[0]] == [(10, 69, 20)]
    assert [(n.frame, n.pitch, n.duration) for n in notes[4]] == [(40, 69, 5)]


def test_extract_fm_legato_pitch_change_is_a_new_note():
    writes = fm_note_writes(0, 1, 4, 1084, 30)
    # Sin soltar la tecla, sube una quinta (x1.5) en el cuadro 10; un vibrato pequeño no cuenta
    writes += [(5, Write(0, "ym0", 0xA5, 4 << 3 | (1090 >> 8))), (5, Write(0, "ym0", 0xA1, 1090 & 0xFF))]
    writes += [(10, Write(0, "ym0", 0xA5, 4 << 3 | (1626 >> 8))), (10, Write(0, "ym0", 0xA1, 1626 & 0xFF))]
    notes = extract_notes(sorted(writes, key=lambda x: x[0]))[1]
    assert [(n.frame, n.pitch) for n in notes] == [(0, 69), (10, 76)]


def test_extract_psg_notes_from_volume_and_period():
    period = round(vgm.PSG_CLOCK / (32 * 440))
    writes = [
        (5, Write(0, "psg", 0, 0x80 | (period & 0xF))),
        (5, Write(0, "psg", 0, period >> 4)),
        (5, Write(0, "psg", 0, 0x90)),  # volumen al máximo: empieza la nota
        (8, Write(0, "psg", 0, 0x92)),  # baja un poco: es la envolvente, no otra nota
        (15, Write(0, "psg", 0, 0x9F)),  # apagado
    ]
    notes = extract_notes(writes)[6]
    assert [(n.frame, n.pitch, n.duration) for n in notes] == [(5, 69, 10)]


def test_fm_pitch_matches_midi():
    assert math.isclose(vgm.fm_pitch(4, 1084), 69, abs_tol=0.05)
