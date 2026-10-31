"""VGM: el formato en que se guarda la música de Genesis (escrituras a los registros del YM2612 y del PSG).

Aquí está todo lo que GENBand hace con un VGM:

  - leerlo (`read_vgm`, encima del lector genérico de bandcore): la lista de escrituras con el instante (en
    muestras de 44.1 kHz) en que pasan;
  - escribirlo (`VgmWriter`): lo usa audio/compose.py para las canciones originales;
  - convertirlo al flujo por cuadro que toca el juego (`frame_stream`, ver src/music.c);
  - sacar las notas de cada canal (`extract_notes`), de donde salen los charts.

El juego corre a 60 cuadros por segundo y su reproductor aplica una vez por cuadro las escrituras que
tocan: un VGM pide esperas en muestras (735 por cuadro), así que cada escritura se redondea al cuadro
más cercano. A esa resolución no se nota.

El DAC (los samples de batería de muchos juegos): el VGM trae los samples en un bloque de datos ($67) y
los toca byte por byte ($8n), saltando al inicio de cada golpe ($E0). El reproductor de la ROM no puede
alimentar el DAC a miles de muestras por segundo desde el 68000, así que cada golpe se vuelve un evento
"toca el sample n" y lo toca el driver PCM de SGDK en el Z80 (ver `_dac_samples` y src/music.c). Los
streams de DAC ($9x) aún no se leen.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from pathlib import Path

from bandcore import vgm as core
from bandcore.chart import Note  # noqa: F401  (la misma en los cuatro juegos)
from bandcore.vgm import frame_of, unrolled_writes  # noqa: F401  (las usan cli.py y las pruebas como vgm.frame_of)

YM_CLOCK = 7670453  # NTSC
PSG_CLOCK = 3579545
SAMPLE_RATE = 44100
SAMPLES_PER_FRAME = 735  # 44100 / 60

# Canales: índices que usan el juego (máscara de silencio) y las herramientas
FM_CHANNELS = 6
PSG_TONES = 3
CHANNEL_NAMES = ["fm1", "fm2", "fm3", "fm4", "fm5", "fm6", "psg1", "psg2", "psg3", "ruido", "dac"]
NOISE = 9
DAC = 10
PERCUSSION = (NOISE, DAC)  # canales sin altura (cada golpe es un tipo de ruido o un sample)

# Frecuencias del driver PCM de SGDK (en el orden de su parámetro de velocidad, SOUND_PCM_RATE_...)
PCM_RATES = (32000, 22050, 16000, 13400, 11025, 8000)


@dataclass(frozen=True)
class Write:
    sample: int  # instante (muestras de 44.1 kHz desde el inicio)
    chip: str  # "ym0", "ym1" (los dos puertos del YM2612), "psg" o "dac" (un golpe: reg = el sample)
    reg: int  # registro del YM (en el PSG, 0)
    value: int  # (en el DAC: cuántos cuadros dura el sample)


@dataclass(frozen=True)
class DacSample:
    data: bytes  # con signo (8 bits, 0 = silencio), ya a la frecuencia del driver
    rate: int  # índice en PCM_RATES


@dataclass
class Vgm:
    writes: list[Write]
    total_samples: int
    loop_sample: int | None  # dónde empieza el bucle (None = no tiene)
    loop_samples: int
    tags: dict[str, str]
    dac_samples: list[DacSample]


def read_vgm(path: Path) -> Vgm:
    """Lee un .vgm o .vgz (el mismo formato comprimido con gzip) con el lector de bandcore."""
    raw = core.read_vgm(path)
    ym_clock = raw.clocks.get("ym2612") or (raw.version < 0x110 and raw.clocks.get("ym2413"))
    if not ym_clock and not raw.clocks.get("sn76489"):
        raise ValueError(f"{path}: no usa el YM2612 ni el PSG (no es música de Genesis)")
    writes: list[Write] = []
    for w in raw.writes:
        if w.index:
            continue
        if w.chip == "sn76489" and w.port == 0:
            writes.append(Write(w.sample, "psg", 0, w.value))
        elif w.chip == "ym2612":
            writes.append(Write(w.sample, "ym0" if w.port == 0 else "ym1", w.reg, w.value))
    bank = b"".join(b.data for b in raw.blocks if b.type == 0x00)  # los samples del DAC
    runs: list[_DacRun] = []  # cada golpe del DAC: desde dónde del banco, cuántos bytes y en cuánto tiempo
    dac_pos = 0
    for event in raw.dac:
        if event.kind == "seek":  # saltar a un lugar del banco: empieza un golpe
            dac_pos = event.offset
            runs.append(_DacRun(event.sample, dac_pos))
        else:  # un byte del banco al DAC
            if not runs:
                runs.append(_DacRun(event.sample, dac_pos))
            runs[-1].played(event.sample)
            dac_pos += 1
    samples, hits = _dac_samples(bank, runs)
    if hits:  # los golpes van entre las escrituras, en su instante (después de las de ese mismo instante)
        writes = sorted(writes + hits, key=lambda w: w.sample)
    return Vgm(writes, raw.total_samples, raw.loop_sample, raw.loop_samples, raw.tags, samples)


# --- DAC: de los bytes que el VGM manda uno por uno, a samples que toca el driver ---------------------


class _DacRun:
    """Un golpe del DAC: desde dónde del banco, y en qué instantes salieron sus bytes."""

    def __init__(self, sample: int, offset: int) -> None:
        self.sample, self.offset = sample, offset
        self.count, self.first, self.last = 0, sample, sample

    def played(self, sample: int) -> None:
        if not self.count:
            self.first = sample
        self.count += 1
        self.last = sample

    @property
    def rate(self) -> float | None:
        """Bytes por segundo (con los bytes que salieron; un golpe muy corto no lo dice bien)."""
        if self.count < _DAC_RELIABLE:
            return None
        return SAMPLE_RATE * (self.count - 1) / max(1, self.last - self.first)


_DAC_MIN_BYTES = 8  # golpes más cortos no se oyen (son restos al cortar uno con otro)
_DAC_RELIABLE = 48  # bytes para confiar en la frecuencia medida de un golpe
_DAC_SAME_RATE = 1.06  # frecuencias dentro de este factor son la misma (el driver del juego no es exacto)


def _dac_samples(bank: bytes, runs: list[_DacRun]) -> tuple[list[DacSample], list[Write]]:
    """Los samples del DAC y los golpes (escrituras "dac").

    Cada golpe empieza en un lugar del banco y suena a una frecuencia (los juegos tocan el mismo sample a
    varias, como los timbales de Sonic). Un sample es un par (lugar, frecuencia): sus bytes son los más que
    se oyeron en uno de sus golpes (los demás los cortó el golpe siguiente, y el driver los corta igual).
    Se pasa a la frecuencia del driver más cercana y a 8 bits con signo."""
    runs = [r for r in runs if r.count >= _DAC_MIN_BYTES and r.offset < len(bank)]
    if not runs:
        return [], []
    measured = [r.rate for r in runs if r.rate]
    fallback = sorted(measured)[len(measured) // 2] if measured else 8000.0
    # Las frecuencias de cada lugar, en grupos
    groups: dict[int, list[float]] = {}
    for offset in sorted({r.offset for r in runs}):
        rates = sorted(r.rate for r in runs if r.offset == offset and r.rate)
        clusters: list[list[float]] = []
        for rate in rates:
            if clusters and rate <= clusters[-1][0] * _DAC_SAME_RATE:
                clusters[-1].append(rate)
            else:
                clusters.append([rate])
        groups[offset] = [c[len(c) // 2] for c in clusters] or [fallback]

    ids: dict[tuple[int, float], int] = {}
    lengths: dict[tuple[int, float], int] = {}
    keyed = []
    for r in runs:
        options = groups[r.offset]
        rate = min(options, key=lambda g: abs(math.log(g / r.rate))) if r.rate else options[0]
        key = (r.offset, rate)
        ids.setdefault(key, len(ids))
        lengths[key] = max(lengths.get(key, 0), r.count)
        keyed.append((r, key))

    samples = []
    for (offset, rate), _ in sorted(ids.items(), key=lambda item: item[1]):
        raw = bank[offset : offset + lengths[(offset, rate)]]
        index = min(range(len(PCM_RATES)), key=lambda i: abs(math.log(PCM_RATES[i] / rate)))
        samples.append(DacSample(_resample(raw, rate, PCM_RATES[index]), index))
    if len(samples) > 255:
        raise ValueError(f"el DAC usa {len(samples)} samples distintos (el flujo admite 255)")
    hits = []
    for r, key in keyed:
        seconds = lengths[key] / key[1]
        hits.append(Write(r.sample, "dac", ids[key], max(1, round(seconds * 60))))
    return samples, hits


def _resample(raw: bytes, source: float, target: int) -> bytes:
    """De bytes sin signo (128 = silencio) a `source` Hz, a bytes con signo a `target` Hz (interpolación lineal)."""
    n = max(1, round(len(raw) * target / source))
    step = source / target
    out = bytearray(n)
    for i in range(n):
        x = i * step
        j = int(x)
        a = raw[min(j, len(raw) - 1)]
        b = raw[min(j + 1, len(raw) - 1)]
        out[i] = (round(a + (b - a) * (x - j)) - 128) & 0xFF
    return bytes(out)


# --- Flujo por cuadro (lo que toca src/music.c) -----------------------------------------------------
#
#   $50 v        escribir v en el PSG
#   $52 r v      escribir v en el registro r del YM2612, puerto 0 (canales 1-3 y globales)
#   $53 r v      lo mismo en el puerto 1 (canales 4-6)
#   $62          fin del cuadro: lo que sigue va en el siguiente
#   $7n          fin del cuadro y n cuadros más sin escrituras (n = 1..15)
#   $61 lo hi    fin del cuadro y N cuadros más sin escrituras (N de 16 bits)
#   $54 n        tocar el sample n del DAC (src/music.c lo pasa al driver PCM del Z80)
#   $66          fin de la música (o vuelta al bucle, si la canción tiene uno)
#
# Los códigos son los mismos que los del VGM, para que sea fácil leerlo, pero las esperas cuentan cuadros.

CMD_PSG, CMD_YM0, CMD_YM1, CMD_DAC, CMD_FRAME, CMD_WAIT, CMD_END = 0x50, 0x52, 0x53, 0x54, 0x62, 0x61, 0x66

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
        if w.chip in ("ym0", "ym1") and w.reg in _SKIP:
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
            if w.chip == "dac":
                cmds += bytes((CMD_DAC, w.reg))
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
    """Las notas de cada canal (0-5 FM, 6-8 tonos del PSG, 9 ruido, 10 DAC), a partir de las escrituras.

    En el DAC cada golpe es una nota cuya "altura" es el número de sample, y dura lo que el sample o
    hasta el golpe siguiente."""
    trackers = [_Tracker() for _ in CHANNEL_NAMES]
    latch = [0, 0]  # parte alta de la frecuencia ($A4-$A6) que espera a la parte baja, por puerto
    freq = [(0, 0)] * FM_CHANNELS  # (bloque, F-number) de cada canal FM
    keyed = [False] * FM_CHANNELS
    dac = False
    psg_period = [0] * 3
    psg_volume = [15] * 4  # atenuación: 15 = apagado
    noise_mode = 0
    psg_latch = (0, 0)  # (canal, tipo): el último registro del PSG que se eligió
    dac_end = 0  # cuadro en que termina el sample del DAC que suena
    last_frame = 0

    def fm_current(ch: int) -> float | None:
        return fm_pitch(*freq[ch])

    for frame, w in writes:
        last_frame = frame
        if w.chip == "dac":
            t = trackers[DAC]
            t.off(min(frame, dac_end))
            t.on(frame, float(w.reg), f"dac{w.reg}")
            dac_end = frame + w.value
            continue
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
    trackers[DAC].off(min(stop, dac_end))
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
