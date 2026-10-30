import math

from genband_tools import vgm
from genband_tools.vgm import Note, VgmWriter, Write, extract_notes, frame_stream, read_vgm


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


# --- DAC ------------------------------------------------------------------------------------------


def dac_vgm(tmp_path):
    """Un VGM con un banco de 2 samples y 3 golpes: el primero dos veces a 22050 Hz (un byte cada 2
    muestras), el segundo una vez a ~8820 Hz (cada 5)."""
    import struct
    kick = bytes(128 + round(100 * math.sin(i / 4)) for i in range(200))
    snare = bytes((128 + (i * 37) % 120 - 60) & 0xFF for i in range(100))
    bank = kick + snare
    body = bytearray()
    body += bytes((0x67, 0x66, 0x00)) + struct.pack("<I", len(bank)) + bank
    body += bytes((0x52, 0x2B, 0x80))
    for offset, count, wait in ((0, 200, 2), (200, 100, 5), (0, 120, 2)):
        body += bytes((0xE0,)) + struct.pack("<I", offset)
        body += bytes((0x80 | wait,)) * count
        body += bytes((0x62,)) * 3
    body += bytes((0x66,))
    header = bytearray(0x40)
    header[0:4] = b"Vgm "
    struct.pack_into("<I", header, 0x04, 0x40 + len(body) - 4)
    struct.pack_into("<I", header, 0x08, 0x150)
    struct.pack_into("<I", header, 0x2C, vgm.YM_CLOCK)
    struct.pack_into("<I", header, 0x34, 0x40 - 0x34)
    path = tmp_path / "dac.vgm"
    path.write_bytes(bytes(header + body))
    return path, kick


def test_dac_hits_become_samples_and_stream_commands(tmp_path):
    path, kick = dac_vgm(tmp_path)
    data = read_vgm(path)
    # Dos samples: (lugar 0, 22050 Hz) con sus 200 bytes (el golpe más largo) y (lugar 200, ~8820 -> 8000 Hz)
    assert [vgm.PCM_RATES[s.rate] for s in data.dac_samples] == [22050, 8000]
    first = data.dac_samples[0].data
    assert len(first) == 200 and first[0] == (kick[0] - 128) & 0xFF       # con signo: 128 = 0
    assert abs(len(data.dac_samples[1].data) - round(100 * 8000 / 8820)) <= 1
    hits = [w for w in data.writes if w.chip == "dac"]
    assert [w.reg for w in hits] == [0, 1, 0]
    writes = vgm.unrolled_writes(data)
    stream, _, _ = frame_stream(writes)
    assert stream.count(bytes((vgm.CMD_DAC, 0))) == 2 and stream.count(bytes((vgm.CMD_DAC, 1))) == 1
    # Cada golpe es una nota del canal DAC (su "altura" es el número de sample)
    notes = extract_notes(writes)[vgm.DAC]
    assert [n.pitch for n in notes] == [0, 1, 0]
    assert all(n.duration >= 1 for n in notes)


def test_dac_sample_numbers_are_not_skipped_as_registers():
    # Un golpe del sample 0x2A no es una escritura al registro $2A (que el flujo no lleva)
    writes = [(0, Write(0, "dac", 0x2A, 1)), (0, Write(0, "ym0", 0x2A, 0x80))]
    stream, _, _ = frame_stream(writes)
    assert bytes((vgm.CMD_DAC, 0x2A)) in stream and bytes((vgm.CMD_YM0, 0x2A)) not in stream


def test_dac_drum_suggestion_uses_how_each_sample_sounds():
    from genband_tools.drums import drum_groups, suggest_assignment

    def sample(period: int, seconds: float = 0.2) -> vgm.DacSample:   # una onda cuadrada a 8000 Hz
        n = int(8000 * seconds)
        return vgm.DacSample(bytes((60 if (i // period) % 2 else 196) for i in range(n)), 5)

    # 0: grave y muy usado (bombo); 1: ruidoso y muy usado (tarola); 2: medio, poco usado (tom);
    # 3: un resto de 10 ms (no se sugiere); 4: el más grave, pero con 3 golpes (no es el bombo)
    samples = [sample(40), sample(1), sample(8), sample(1, 0.01), sample(200)]
    counts = [40, 30, 5, 40, 3]
    notes = {vgm.DAC: sorted((Note(f * 7 + i, i, 2) for i, c in enumerate(counts) for f in range(c)), key=lambda n: n.frame)}
    roles = {k: v["lane"] for k, v in suggest_assignment(drum_groups(notes, [vgm.DAC]), samples).items()}
    assert roles["dac:0"] == "kick" and roles["dac:1"] == "snare"
    assert roles["dac:2"] in ("tom1", "tom2", "tom3") and roles["dac:4"] in ("tom1", "tom2", "tom3")
    assert roles["dac:3"] is None
