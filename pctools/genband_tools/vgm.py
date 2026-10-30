"""VGM: el formato en que se guarda la música de Genesis (escrituras a los registros del YM2612 y del PSG).

Aquí está todo lo que GENBand hace con un VGM:

  - leerlo (`read_vgm`): la lista de escrituras con el instante (en muestras de 44.1 kHz) en que pasan;
  - escribirlo (`VgmWriter`): lo usa audio/compose.py para las canciones originales;
  - convertirlo al flujo por cuadro que toca el juego (`frame_stream`, ver src/music.c);
  - sacar las notas de cada canal (`extract_notes`), de donde salen los charts.

El juego corre a 60 cuadros por segundo y su reproductor aplica una vez por cuadro las escrituras que
tocan: un VGM pide esperas en muestras (735 por cuadro), así que cada escritura se redondea al cuadro
más cercano. A esa resolución no se nota.

Lo que no se usa: el DAC (los samples de batería de muchos juegos, registro $2A y los comandos $8n y
$9x de streaming). El reproductor de la ROM corre en el 68000 una vez por cuadro y no puede alimentar
un sample a miles de muestras por segundo; eso necesita un driver en el Z80 (pendiente).
"""

from __future__ import annotations

import gzip
import math
import struct
from dataclasses import dataclass
from pathlib import Path

YM_CLOCK = 7670453  # NTSC
PSG_CLOCK = 3579545
SAMPLE_RATE = 44100
SAMPLES_PER_FRAME = 735  # 44100 / 60

# Canales: índices que usan el juego (máscara de silencio) y las herramientas
FM_CHANNELS = 6
PSG_TONES = 3
CHANNEL_NAMES = ["fm1", "fm2", "fm3", "fm4", "fm5", "fm6", "psg1", "psg2", "psg3", "ruido"]
NOISE = 9


@dataclass(frozen=True)
class Write:
    sample: int  # instante (muestras de 44.1 kHz desde el inicio)
    chip: str  # "ym0", "ym1" (los dos puertos del YM2612) o "psg"
    reg: int  # registro del YM (en el PSG, 0)
    value: int


@dataclass
class Vgm:
    writes: list[Write]
    total_samples: int
    loop_sample: int | None  # dónde empieza el bucle (None = no tiene)
    loop_samples: int
    tags: dict[str, str]


# Comandos del formato VGM que no usamos, con cuántos bytes ocupan (incluido el comando)
def _command_length(cmd: int, data: bytes, pos: int) -> int:
    if cmd in (0x4F, 0x50) or 0x30 <= cmd <= 0x3F:
        return 2
    if 0x40 <= cmd <= 0x4E or 0x51 <= cmd <= 0x5F or 0xA0 <= cmd <= 0xBF:
        return 3
    if 0xC0 <= cmd <= 0xDF:
        return 4
    if 0xE0 <= cmd <= 0xFF:
        return 5
    if cmd == 0x68:
        return 12
    if cmd in (0x90, 0x91, 0x95):
        return 5
    if cmd == 0x92:
        return 6
    if cmd == 0x93:
        return 11
    if cmd == 0x94:
        return 2
    raise ValueError(f"comando VGM desconocido ${cmd:02X} en el byte {pos:#x}")


def _gd3(data: bytes, offset: int) -> dict[str, str]:
    if not offset or data[offset : offset + 4] != b"Gd3 ":
        return {}
    length = struct.unpack_from("<I", data, offset + 8)[0]
    text = data[offset + 12 : offset + 12 + length].decode("utf-16-le", errors="replace")
    fields = text.split("\0")
    names = ["title", "title_jp", "game", "game_jp", "system", "system_jp", "author", "author_jp", "date", "ripper", "notes"]
    return {name: value for name, value in zip(names, fields) if value}


def read_vgm(path: Path) -> Vgm:
    """Lee un .vgm o .vgz (el mismo formato comprimido con gzip)."""
    raw = Path(path).read_bytes()
    data = gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw
    if data[:4] != b"Vgm ":
        raise ValueError(f"{path}: no es un archivo VGM")
    version = struct.unpack_from("<I", data, 0x08)[0]
    gd3_offset = struct.unpack_from("<I", data, 0x14)[0]
    total = struct.unpack_from("<I", data, 0x18)[0]
    loop_offset = struct.unpack_from("<I", data, 0x1C)[0]
    loop_samples = struct.unpack_from("<I", data, 0x20)[0]
    ym_clock = struct.unpack_from("<I", data, 0x2C)[0] if version >= 0x110 else struct.unpack_from("<I", data, 0x10)[0]
    if not ym_clock and not struct.unpack_from("<I", data, 0x0C)[0]:
        raise ValueError(f"{path}: no usa el YM2612 ni el PSG (no es música de Genesis)")
    start = 0x40
    if version >= 0x150:
        rel = struct.unpack_from("<I", data, 0x34)[0]
        if rel:
            start = 0x34 + rel
    loop_pos = 0x1C + loop_offset if loop_offset else None

    writes: list[Write] = []
    sample = 0
    loop_sample = None
    pos = start
    while pos < len(data):
        if loop_pos is not None and pos == loop_pos:
            loop_sample = sample
        cmd = data[pos]
        if cmd == 0x66:
            break
        if cmd == 0x50:
            writes.append(Write(sample, "psg", 0, data[pos + 1]))
            pos += 2
        elif cmd in (0x52, 0x53):
            writes.append(Write(sample, "ym0" if cmd == 0x52 else "ym1", data[pos + 1], data[pos + 2]))
            pos += 3
        elif cmd == 0x61:
            sample += struct.unpack_from("<H", data, pos + 1)[0]
            pos += 3
        elif cmd == 0x62:
            sample += 735
            pos += 1
        elif cmd == 0x63:
            sample += 882
            pos += 1
        elif 0x70 <= cmd <= 0x7F:
            sample += (cmd & 0x0F) + 1
            pos += 1
        elif 0x80 <= cmd <= 0x8F:  # una muestra del DAC (no se usa) y esperar n
            sample += cmd & 0x0F
            pos += 1
        elif cmd == 0x67:  # bloque de datos (samples del DAC)
            size = struct.unpack_from("<I", data, pos + 3)[0] & 0x7FFFFFFF
            pos += 7 + size
        else:
            pos += _command_length(cmd, data, pos)
    tags = _gd3(data, 0x14 + gd3_offset if gd3_offset else 0)
    return Vgm(writes, total or sample, loop_sample, loop_samples, tags)


def frame_of(sample: int) -> int:
    return (sample + SAMPLES_PER_FRAME // 2) // SAMPLES_PER_FRAME


def unrolled_writes(vgm: Vgm, frames: int | None = None) -> list[tuple[int, Write]]:
    """Las escrituras con su cuadro, repitiendo el bucle hasta llenar `frames` cuadros (si se pide).

    Sin `frames` se toca una sola vez, hasta el final del archivo."""
    out = [(frame_of(w.sample), w) for w in vgm.writes]
    if frames is None:
        return out
    if vgm.loop_sample is not None and vgm.loop_samples:
        loop = [w for w in vgm.writes if w.sample >= vgm.loop_sample]
        offset = vgm.total_samples
        while loop and frame_of(offset) < frames:
            out += [(frame_of(w.sample - vgm.loop_sample + offset), w) for w in loop]
            offset += vgm.total_samples - vgm.loop_sample
    return [(f, w) for f, w in out if f < frames]


# --- Flujo por cuadro (lo que toca src/music.c) -----------------------------------------------------
#
#   $50 v        escribir v en el PSG
#   $52 r v      escribir v en el registro r del YM2612, puerto 0 (canales 1-3 y globales)
#   $53 r v      lo mismo en el puerto 1 (canales 4-6)
#   $62          fin del cuadro: lo que sigue va en el siguiente
#   $7n          fin del cuadro y n cuadros más sin escrituras (n = 1..15)
#   $61 lo hi    fin del cuadro y N cuadros más sin escrituras (N de 16 bits)
#   $66          fin de la música (o vuelta al bucle, si la canción tiene uno)
#
# Los códigos son los mismos que los del VGM, para que sea fácil leerlo, pero las esperas cuentan cuadros.

CMD_PSG, CMD_YM0, CMD_YM1, CMD_FRAME, CMD_WAIT, CMD_END = 0x50, 0x52, 0x53, 0x62, 0x61, 0x66

# Registros del YM que el flujo no lleva: los timers (el juego no los usa) y el DAC ($2A, ver arriba)
_SKIP = {0x24, 0x25, 0x26, 0x2A}
# Registros que nunca se omiten aunque se repita el valor: el key-on, el modo del canal 3 (también
# reinicia los timers) y las frecuencias ($A0-$AF: la parte alta se guarda en un latch que comparten
# los tres canales del puerto, así que repetirla puede ser necesario)
_ALWAYS = {0x27, 0x28}


def _keep_always(reg: int) -> bool:
    return reg in _ALWAYS or 0xA0 <= reg <= 0xAF


def silence_writes() -> list[tuple[str, int, int]]:
    """Escrituras que callan todo: key-off de los 6 canales FM y volumen mínimo en el PSG."""
    out = [("ym0", 0x28, code) for code in (0, 1, 2, 4, 5, 6)]
    out += [("psg", 0, 0x9F | (ch << 5)) for ch in range(4)]
    return out


def frame_stream(
    writes: list[tuple[int, Write]], end_frame: int | None = None, loop_frame: int | None = None
) -> tuple[bytes, int, int | None]:
    """Convierte las escrituras a bytes del flujo por cuadro. Devuelve (bytes, cuadros que dura, bucle).

    Se omiten las escrituras que repiten el valor que ya tiene el registro (salvo las de _ALWAYS y las
    frecuencias). Sin bucle, al final se callan todos los canales; con `loop_frame`, el flujo termina en
    $66 sin callar nada y `bucle` es el byte donde empieza ese cuadro (adonde vuelve el reproductor)."""
    by_frame: dict[int, list[Write]] = {}
    for frame, w in writes:
        if w.chip != "psg" and w.reg in _SKIP:
            continue
        by_frame.setdefault(frame, []).append(w)
    last = max(by_frame) if by_frame else 0
    end = max(end_frame if end_frame is not None else last + 1, last + 1)

    shadow: dict[tuple[str, int], int] = {}
    out = bytearray()
    current = 0
    loop_offset = None
    if loop_frame == 0:
        loop_offset = 0
    for frame in sorted(by_frame):
        if loop_frame and loop_offset is None and frame >= loop_frame:
            _wait(out, loop_frame - current)
            current = loop_frame
            loop_offset = len(out)
            shadow.clear()  # al volver al bucle los registros no tienen lo que tenían aquí
        cmds = bytearray()
        for w in by_frame[frame]:
            if w.chip == "psg":
                cmds += bytes((CMD_PSG, w.value))
                continue
            key = (w.chip, w.reg)
            if not _keep_always(w.reg) and shadow.get(key) == w.value:
                continue
            shadow[key] = w.value
            cmds += bytes((CMD_YM0 if w.chip == "ym0" else CMD_YM1, w.reg, w.value))
        if not cmds:
            continue
        _wait(out, frame - current)
        out += cmds
        current = frame
    _wait(out, end - current)
    if loop_frame is None:
        for chip, reg, value in silence_writes():
            out += bytes((CMD_PSG, value)) if chip == "psg" else bytes((CMD_YM0, reg, value))
    out.append(CMD_END)
    return bytes(out), end, loop_offset


def _wait(out: bytearray, frames: int) -> None:
    """Pasa `frames` cuadros (cierra el actual y salta frames-1). 0 = seguir en el mismo cuadro."""
    while frames > 0x10000:  # $61 FFFF: fin del cuadro + 65535 cuadros
        out += bytes((CMD_WAIT, 0xFF, 0xFF))
        frames -= 0x10000
    if frames <= 0:
        return
    extra = frames - 1
    if extra == 0:
        out.append(CMD_FRAME)
    elif extra <= 15:
        out.append(0x70 | extra)
    else:
        out += bytes((CMD_WAIT, extra & 0xFF, extra >> 8))


# --- Notas de cada canal ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Note:
    frame: int  # cuadro desde que empieza la canción
    pitch: int  # número MIDI (solo importa para comparar alturas)
    duration: int
    extra: int | None = None  # otra altura del mismo gesto (un arpegio fusionado: un acorde "roto"); ver merge_attacks
    instrument: str | None = None  # qué sonido es (en el ruido, el tipo de ruido: parte de lo que identifica un golpe)


def fm_pitch(block: int, fnum: int) -> float | None:
    """Altura MIDI (con decimales) de una frecuencia del YM2612 (bloque 0-7, F-number de 11 bits)."""
    if fnum == 0:
        return None
    freq = fnum * YM_CLOCK / 144 / (1 << (21 - block))
    return 69 + 12 * math.log2(freq / 440)


def psg_pitch(period: int) -> float | None:
    if period == 0:
        return None
    return 69 + 12 * math.log2(PSG_CLOCK / (32 * period) / 440)


_PITCH_SLACK = 0.75  # semitonos que puede moverse la altura (vibrato, portamento) sin que cuente como otra nota
_PSG_REATTACK = 4  # un golpe de volumen de 4 pasos o más (de 15) en una nota que suena es un ataque nuevo


class _Tracker:
    """Sigue un canal y anota sus notas (inicio, altura, duración)."""

    def __init__(self) -> None:
        self.notes: list[Note] = []
        self.start: int | None = None
        self.pitch: float | None = None
        self.instrument: str | None = None

    def on(self, frame: int, pitch: float | None, instrument: str | None = None) -> None:
        self.off(frame)
        if pitch is None:
            return
        self.start, self.pitch, self.instrument = frame, pitch, instrument

    def off(self, frame: int) -> None:
        if self.start is not None and self.pitch is not None:
            self.notes.append(Note(self.start, round(self.pitch), max(1, frame - self.start), instrument=self.instrument))
        self.start = None

    def bend(self, frame: int, pitch: float | None) -> None:
        """La altura cambió sin un ataque nuevo: si se movió lo bastante, es otra nota (legato)."""
        if self.start is None or pitch is None or self.pitch is None:
            return
        if abs(pitch - self.pitch) >= _PITCH_SLACK and frame > self.start:
            self.on(frame, pitch, self.instrument)


def extract_notes(writes: list[tuple[int, Write]], end_frame: int | None = None) -> dict[int, list[Note]]:
    """Las notas de cada canal (0-5 FM, 6-8 tonos del PSG, 9 ruido), a partir de las escrituras."""
    trackers = [_Tracker() for _ in CHANNEL_NAMES]
    latch = [0, 0]  # parte alta de la frecuencia ($A4-$A6) que espera a la parte baja, por puerto
    freq = [(0, 0)] * FM_CHANNELS  # (bloque, F-number) de cada canal FM
    keyed = [False] * FM_CHANNELS
    dac = False
    psg_period = [0] * 3
    psg_volume = [15] * 4  # atenuación: 15 = apagado
    noise_mode = 0
    psg_latch = (0, 0)  # (canal, tipo): el último registro del PSG que se eligió
    last_frame = 0

    def fm_current(ch: int) -> float | None:
        return fm_pitch(*freq[ch])

    for frame, w in writes:
        last_frame = frame
        if w.chip == "psg":
            v = w.value
            if v & 0x80:
                ch, kind = (v >> 5) & 3, (v >> 4) & 1
                psg_latch = (ch, kind)
                data = v & 0x0F
                if kind == 0 and ch < 3:
                    psg_period[ch] = (psg_period[ch] & 0x3F0) | data
                elif kind == 0:
                    noise_mode = data & 7
            else:
                ch, kind = psg_latch
                data = v & 0x3F
                if kind == 0 and ch < 3:
                    psg_period[ch] = (psg_period[ch] & 0x00F) | (data << 4)
            if kind == 1:
                old = psg_volume[ch]
                new = v & 0x0F
                psg_volume[ch] = new
                t = trackers[6 + ch]
                pitch = psg_pitch(psg_period[ch]) if ch < 3 else float(noise_mode)
                inst = None if ch < 3 else f"ruido{noise_mode}"
                if new == 15:
                    t.off(frame)
                elif old == 15 or old - new >= _PSG_REATTACK:
                    t.on(frame, pitch, inst)
            elif ch < 3 and psg_volume[ch] != 15:
                trackers[6 + ch].bend(frame, psg_pitch(psg_period[ch]))
            continue

        port = 0 if w.chip == "ym0" else 1
        reg, v = w.reg, w.value
        if port == 0 and reg == 0x2B:
            dac = bool(v & 0x80)
            if dac:
                trackers[5].off(frame)
        elif port == 0 and reg == 0x28:
            code = v & 7
            if code in (3, 7):
                continue
            ch = code if code < 3 else code - 1
            on = bool(v & 0xF0)
            if ch == 5 and dac:
                continue
            if on and not keyed[ch]:
                trackers[ch].on(frame, fm_current(ch), f"fm{ch + 1}")
            elif not on and keyed[ch]:
                trackers[ch].off(frame)
            keyed[ch] = on
        elif 0xA4 <= reg <= 0xA6:
            latch[port] = v
        elif 0xA0 <= reg <= 0xA2:
            ch = port * 3 + (reg - 0xA0)
            freq[ch] = ((latch[port] >> 3) & 7, ((latch[port] & 7) << 8) | v)
            if keyed[ch]:
                trackers[ch].bend(frame, fm_current(ch))

    stop = end_frame if end_frame is not None else last_frame + 1
    for t in trackers:
        t.off(stop)
    return {i: t.notes for i, t in enumerate(trackers) if t.notes}


# --- Escribir un VGM (para las canciones originales) -----------------------------------------------


class VgmWriter:
    """Arma un VGM 1.50 escritura por escritura. El tiempo avanza por cuadros (`wait_frames`)."""

    def __init__(self) -> None:
        self.data = bytearray()
        self.samples = 0
        self.loop_at: tuple[int, int] | None = None  # (posición en los datos, muestra)

    def ym(self, port: int, reg: int, value: int) -> None:
        self.data += bytes((0x52 + port, reg & 0xFF, value & 0xFF))

    def psg(self, value: int) -> None:
        self.data += bytes((0x50, value & 0xFF))

    def wait_frames(self, frames: int) -> None:
        for _ in range(frames):
            self.data.append(0x62)
        self.samples += frames * SAMPLES_PER_FRAME

    def mark_loop(self) -> None:
        self.loop_at = (len(self.data), self.samples)

    def to_bytes(self, title: str = "", game: str = "", author: str = "") -> bytes:
        body = bytes(self.data) + b"\x66"
        header = bytearray(0x40)
        header[0:4] = b"Vgm "
        struct.pack_into("<I", header, 0x08, 0x150)
        struct.pack_into("<I", header, 0x0C, PSG_CLOCK)
        struct.pack_into("<I", header, 0x18, self.samples)
        if self.loop_at:
            struct.pack_into("<I", header, 0x1C, 0x40 + self.loop_at[0] - 0x1C)
            struct.pack_into("<I", header, 0x20, self.samples - self.loop_at[1])
        struct.pack_into("<I", header, 0x24, 60)
        struct.pack_into("<HB", header, 0x28, 0x0009, 16)
        struct.pack_into("<I", header, 0x2C, YM_CLOCK)
        struct.pack_into("<I", header, 0x34, 0x40 - 0x34)
        fields = [title, "", game, "", "Sega Mega Drive / Genesis", "", author, "", "", "GENBand", ""]
        text = "".join(f + "\0" for f in fields).encode("utf-16-le")
        gd3 = b"Gd3 " + struct.pack("<II", 0x100, len(text)) + text
        struct.pack_into("<I", header, 0x14, 0x40 + len(body) - 0x14)
        out = header + body + gd3
        struct.pack_into("<I", out, 0x04, len(out) - 4)
        return bytes(out)
