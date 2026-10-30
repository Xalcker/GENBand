"""genband: línea de comandos de las herramientas de PC.

    uv run genband import-song audio/tormenta.vgm --name tormenta --guitarra fm1 --teclado fm2 --bajo fm3
    uv run genband import-song "songs_src/Sonic 2/04 Emerald Hill Zone.vgz" --name ehz --duration 90
    uv run genband channels cancion.vgz          (qué notas tiene cada canal, para elegir instrumentos)
    uv run genband list-songs
    uv run genband reimport                      (todas, con las mismas opciones, tras mejorar el generador)
    uv run genband build-audio                   (música del título, de audio/titulo.py)
    uv run genband edit-chart [tormenta]         (el editor de charts en el navegador)

import-song genera src/songs/<nombre>/song.c: el flujo de la música (ver vgm.frame_stream), un chart
por instrumento y dificultad y la ficha de la canción que lee el juego (título, tempo, fin, canales).
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import subprocess
import sys
import unicodedata
import zlib
from dataclasses import dataclass
from pathlib import Path

from . import vgm
from .chart import (
    BLOCKED_PAIRS,
    DIFFICULTIES,
    DRUM_BLOCKED_PAIRS,
    BeatGrid,
    ChartNote,
    build_chart,
    chart_buttons,
    chart_to_c,
    check_playable,
    estimate_beat,
    merge_attacks,
)
from .chartedit import apply_edits, load_edits
from .drums import DRUMS_FILE, build_drum_chart, drum_groups, drum_hits, load_drums, save_drums, suggest_assignment

ROOT = Path(__file__).resolve().parents[2]
SONGS_DIR = ROOT / "src" / "songs"
WORK_DIR = ROOT / "build" / "songs"

LEAD_IN = 128  # cuadros de autopista antes de que arranque la música (SONG_LEAD_IN en src/genband.h)
TEXT_MAX = 26  # caracteres que caben en el menú
DEFAULT_DURATION = 120  # segundos, si el VGM tiene bucle y no se dice cuánto grabar
MAX_FRAMES = 65000  # el juego cuenta los cuadros en 16 bits

# Instrumentos en el orden que usa el juego, con su papel en el generador de charts (ver chart.ROLES); la
# batería tiene su propio generador (drums.py)
INSTRUMENTS = [("guitarra", "lead"), ("teclado", "keys"), ("bajo", "bass")]
DRUMS = "bateria"
# De qué otro instrumento sale la armonía de los acordes
PARTNER = {"guitarra": "teclado", "teclado": "guitarra"}


def clean_text(text: str) -> str:
    """Mayúsculas sin acentos ni símbolos que la fuente no tiene."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^A-Za-z0-9 .,:!?'&()/+-]", " ", text.upper())
    return re.sub(r" +", " ", text).strip()[:TEXT_MAX]


def channel_index(name: str) -> int:
    name = name.strip().lower()
    if name not in vgm.CHANNEL_NAMES:
        raise SystemExit(f"canal desconocido: {name} (los canales son {', '.join(vgm.CHANNEL_NAMES)})")
    return vgm.CHANNEL_NAMES.index(name)


def parse_channels(text: str | None) -> list[int] | None:
    if not text:
        return None
    return [channel_index(c) for c in text.split(",")]


def summarize(notes: dict[int, list[vgm.Note]]) -> dict[int, tuple[int, float, int]]:
    """(notas tras juntar los adornos, altura mediana, alturas distintas) de cada canal, sin el ruido ni el DAC."""
    out = {}
    for ch, ns in notes.items():
        if ch in vgm.PERCUSSION:
            continue
        merged = merge_attacks(ns)
        out[ch] = (len(merged), statistics.median(n.pitch for n in merged), len({n.pitch for n in merged}))
    return out


def auto_assign(notes: dict[int, list[vgm.Note]]) -> dict[str, list[int]]:
    """Elige un canal por instrumento si no se dijo cuál.

    Solo cuentan los canales con notas suficientes y al menos 5 alturas distintas (un canal que repite
    casi siempre la misma nota es percusión, como un bombo FM). El bajo es el más grave (mediana por
    debajo de Mi 3); la guitarra, el que más notas tiene contando más las agudas (la melodía); el
    teclado, el siguiente. Casi nunca es perfecto: `genband channels` muestra los canales para elegir."""
    stats = {ch: s[:2] for ch, s in summarize(notes).items() if s[0] >= 20 and s[2] >= 5}
    out: dict[str, list[int]] = {}
    low = [ch for ch, (count, median) in stats.items() if median < 52]
    if low:
        bass = min(low, key=lambda ch: stats[ch][1])
        out["bajo"] = [bass]
        stats.pop(bass)
    for name in ("guitarra", "teclado"):
        if stats:
            ch = max(stats, key=lambda c: stats[c][0] * max(0.25, 1 + (stats[c][1] - 60) / 24))
            out[name] = [ch]
            stats.pop(ch)
    return out


def drum_channels(notes: dict[int, list[vgm.Note]], melodic: set[int]) -> list[int]:
    """Los canales de batería si no se dijeron: el ruido, el DAC, y los que casi no cambian de tono (como el
    bombo FM de las canciones de GENBand) y no son de otro instrumento."""
    out = [ch for ch in vgm.PERCUSSION if notes.get(ch)]
    for ch, (count, _, distinct) in summarize(notes).items():
        if ch not in melodic and count >= 20 and distinct < 5:
            out.append(ch)
    return sorted(out)


def song_hash(title: str, game: str) -> int:
    """Identifica la canción para los récords (no cambia si cambia su lugar en el menú)."""
    return zlib.crc32(f"{title}\n{game}".encode()) & 0xFFFF


def c_bytes(name: str, data: bytes) -> str:
    lines = [f"static const u8 {name}[] = {{"]
    for i in range(0, len(data), 24):
        lines.append("    " + ",".join(f"0x{b:02X}" for b in data[i : i + 24]) + ",")
    lines.append("};")
    return "\n".join(lines) + "\n"


def dac_to_c(samples: list[vgm.DacSample]) -> list[str]:
    """Los samples del DAC y su tabla. El driver PCM de SGDK los pide alineados a 256 bytes y de un largo
    múltiplo de 256 (se completan con silencio)."""
    if not samples:
        return []
    out = []
    for i, sample in enumerate(samples):
        data = sample.data + bytes(-len(sample.data) % 256)
        body = c_bytes(f"dac{i}", data).replace(f"static const u8 dac{i}[] =", f"static const u8 dac{i}[] __attribute__((aligned(256))) =")
        out.append(body)
    rows = ",\n".join(f"    {{ dac{i}, {len(s.data) + (-len(s.data) % 256)}, {s.rate} }}" for i, s in enumerate(samples))
    out.append(f"static const DacSample dac_samples[] = {{\n{rows}\n}};\n")
    return out


def c_string(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


@dataclass
class SongData:
    """Lo que sale de leer el VGM de una canción con sus opciones (lo usan import-song y el editor)."""

    opts: dict
    name: str
    title: str
    game: str
    stream: bytes
    stream_frames: int
    notes: dict[int, list[vgm.Note]]   # por canal (ver vgm.CHANNEL_NAMES)
    assign: dict[str, list[int]]       # instrumento -> canales
    drums: list[int]                   # canales de la batería
    grid: BeatGrid
    dac_samples: list[vgm.DacSample]   # los samples del DAC (el flujo los toca por número)

    @property
    def folder(self) -> Path:
        return SONGS_DIR / self.name

    def channel_notes(self, chs: list[int]) -> list[vgm.Note]:
        return sorted((n for ch in chs for n in self.notes.get(ch, [])), key=lambda n: n.frame)


def load_song(opts: dict) -> SongData:
    name = opts["name"]
    if not re.fullmatch(r"[a-z][a-z0-9_]*", name):
        raise SystemExit(f"nombre inválido: {name} (minúsculas, números y _; empieza con letra)")
    source = Path(opts["source"])
    path = source if source.is_absolute() else ROOT / source
    data = vgm.read_vgm(path)
    title = clean_text(opts.get("title") or data.tags.get("title") or name)
    game = clean_text(opts.get("game") or data.tags.get("game") or "")

    duration = opts.get("duration")
    if duration is None and data.loop_sample is not None:
        duration = DEFAULT_DURATION
    frames = None if duration is None else int(duration * 60)
    writes = vgm.unrolled_writes(data, frames)
    music_frames = frames if frames is not None else vgm.frame_of(data.total_samples)
    music_frames = min(music_frames, MAX_FRAMES - LEAD_IN - 60)
    writes = [(f, w) for f, w in writes if f < music_frames]

    stream, stream_frames, _ = vgm.frame_stream(writes, music_frames)
    notes = vgm.extract_notes(writes, music_frames)

    assign = auto_assign(notes)
    for inst, _ in INSTRUMENTS:
        chosen = parse_channels(opts.get(inst))
        if chosen is not None:
            assign[inst] = chosen
    used = {ch for chs in assign.values() for ch in chs}
    drums = parse_channels(opts.get(DRUMS)) or drum_channels(notes, used)
    onsets = [n.frame for ch, ns in notes.items() if ch in used or ch in vgm.PERCUSSION for n in ns]
    grid = estimate_beat(onsets, opts.get("beat_frames"))
    return SongData(opts, name, title, game, stream, stream_frames, notes, assign, drums, grid, data.dac_samples)


def drum_assignment(sd: SongData, override: dict | None = None) -> tuple[dict | None, bool]:
    """La asignación de papeles de la batería: la que se pide, la de drums.json o, si no hay, la sugerida.
    Devuelve (asignación, ¿es solo una sugerencia sin guardar?)."""
    if not sd.drums:
        return None, False
    if override is not None:
        return override, False
    saved = load_drums(sd.folder)
    if saved is not None:
        return saved, False
    return suggest_assignment(drum_groups(sd.notes, sd.drums), sd.dac_samples), True


def auto_charts(sd: SongData, assignment: dict | None = None) -> dict[str, list[ChartNote]]:
    """Los charts que genera el importador, sin ediciones, por clave "instrumento/dificultad"."""
    charts: dict[str, list[ChartNote]] = {}
    for inst, role in INSTRUMENTS:
        chs = sd.assign.get(inst)
        if not chs:
            continue
        partner_chs = sd.assign.get(PARTNER.get(inst, ""), [])
        mine = sd.channel_notes(chs)
        partner = sd.channel_notes(partner_chs) if partner_chs else []
        for diff in DIFFICULTIES:
            charts[f"{inst}/{diff.name}"] = build_chart(mine, diff, sd.grid, LEAD_IN, role, partner)
    if assignment is None:
        assignment = drum_assignment(sd)[0]
    hits = drum_hits(sd.notes, sd.drums, assignment) if assignment else []
    if hits:
        for diff in DIFFICULTIES:
            charts[f"{DRUMS}/{diff.name}"] = build_drum_chart(hits, diff.name, sd.grid, LEAD_IN)
    return charts


def edited_charts(sd: SongData, auto: dict[str, list[ChartNote]], edits: dict | None = None) -> tuple[dict, list[str]]:
    """Los charts automáticos con las ediciones de edits.json encima, y los avisos de lo que no se pudo aplicar."""
    edits = load_edits(sd.folder) if edits is None else edits
    warnings: list[str] = []
    result = {}
    for key, chart in auto.items():
        warn = lambda text, key=key: warnings.append(f"{key}: {text}")  # noqa: E731
        result[key] = apply_edits(chart, edits[key], warn) if edits.get(key) else chart
    return result, warnings


def write_song(sd: SongData, charts: dict[str, list[ChartNote]]) -> list[str]:
    """Escribe src/songs/<nombre>/song.c con los charts (ya con ediciones). Devuelve el reporte por instrumento."""
    out = [
        "// Generado por genband import-song: no editar a mano (las opciones están en import.json)",
        f"// TITULO: {sd.title}",
        '#include "song.h"',
        "",
        c_bytes("stream", sd.stream),
    ]
    out += dac_to_c(sd.dac_samples)
    charts_c, buttons_c, mask_c, report = [], [], [], []
    for inst in [i for i, _ in INSTRUMENTS] + [DRUMS]:
        keys = [f"{inst}/{d.name}" for d in DIFFICULTIES]
        if not all(k in charts for k in keys):
            charts_c.append("{ " + ", ".join(["NULL"] * len(DIFFICULTIES)) + " }")
            buttons_c.append("{ " + ", ".join(["0"] * len(DIFFICULTIES)) + " }")
            mask_c.append("0")
            continue
        labels, counts = [], []
        for key in keys:
            chart = charts[key]
            check_playable(chart, DRUM_BLOCKED_PAIRS if inst == DRUMS else BLOCKED_PAIRS)
            label = key.replace("/", "_")
            out.append(chart_to_c(label, chart))
            labels.append(label)
            counts.append(str(chart_buttons(chart)))
        chs = sd.drums if inst == DRUMS else sd.assign[inst]
        charts_c.append("{ " + ", ".join(labels) + " }")
        buttons_c.append("{ " + ", ".join(counts) + " }")
        mask_c.append(f"0x{sum(1 << ch for ch in chs):04X}")
        report.append(f"  {inst}: {', '.join(vgm.CHANNEL_NAMES[c] for c in chs)} ({', '.join(counts)} notas)")
    out.append(
        f"""const Song song_{sd.name} = {{
    .title = {c_string(sd.title)},
    .game = {c_string(sd.game)},
    .stream = stream,
    .end_frame = {LEAD_IN + sd.stream_frames},
    .beat_frames = {sd.grid.frames_per_beat},
    .first_beat = {LEAD_IN + sd.grid.first_beat},
    .hash = 0x{song_hash(sd.title, sd.game):04X},
    .channels = {{ {", ".join(mask_c)} }},
    .charts = {{
        {(","+chr(10)+"        ").join(charts_c)}
    }},
    .notes = {{
        {(","+chr(10)+"        ").join(buttons_c)}
    }},
    .dac = {"dac_samples" if sd.dac_samples else "NULL"},
}};
"""
    )
    sd.folder.mkdir(parents=True, exist_ok=True)
    (sd.folder / "song.c").write_text("\n".join(out), encoding="utf-8", newline="\n")
    (sd.folder / "import.json").write_text(json.dumps(sd.opts, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report


def import_song(opts: dict) -> None:
    """Importa una canción con las opciones de import.json (ver main): genera sus charts, les aplica las
    ediciones de edits.json (las del editor) y escribe song.c."""
    sd = load_song(opts)
    sd.folder.mkdir(parents=True, exist_ok=True)
    assignment, suggested = drum_assignment(sd)
    if suggested:
        save_drums(sd.folder, assignment)       # la sugerencia queda guardada, para corregirla a mano
    charts, warnings = edited_charts(sd, auto_charts(sd, assignment))
    report = write_song(sd, charts)

    work = WORK_DIR / sd.name
    work.mkdir(parents=True, exist_ok=True)
    (work / "notes.json").write_text(
        json.dumps({vgm.CHANNEL_NAMES[ch]: [[n.frame, n.pitch, n.duration] for n in ns] for ch, ns in sd.notes.items()}),
        encoding="utf-8",
    )
    bpm = 3600 / sd.grid.frames_per_beat
    print(f"{sd.folder / 'song.c'}: {sd.title} / {sd.game}")
    print(f"  {sd.stream_frames / 60:.0f} s, {len(sd.stream)} bytes de música, tempo {bpm:.0f} BPM ({sd.grid.frames_per_beat} cuadros)")
    print("\n".join(report) if report else "  (ningún instrumento: revisa los canales con `genband channels`)")
    for warning in warnings:
        print(f"  aviso: {warning}")


def cmd_import(args: argparse.Namespace) -> None:
    source = Path(args.source).resolve()
    try:
        rel = source.relative_to(ROOT)
    except ValueError:
        rel = source
    opts = {"name": args.name, "source": str(rel)}
    for key in ("title", "game", "duration", "beat_frames", "guitarra", "teclado", "bajo", DRUMS):
        value = getattr(args, key)
        if value is not None:
            opts[key] = value
    import_song(opts)


def cmd_reimport(args: argparse.Namespace) -> None:
    folders = [SONGS_DIR / n for n in args.names] if args.names else sorted(p.parent for p in SONGS_DIR.glob("*/import.json"))
    for folder in folders:
        opts = json.loads((folder / "import.json").read_text(encoding="utf-8"))
        import_song(opts)


def cmd_channels(args: argparse.Namespace) -> None:
    data = vgm.read_vgm(Path(args.source))
    frames = int(args.duration * 60) if args.duration else None
    writes = vgm.unrolled_writes(data, frames)
    notes = vgm.extract_notes(writes)
    stats = summarize(notes)
    for ch in sorted(notes):
        if ch in stats:
            count, median, distinct = stats[ch]
            print(f"  {vgm.CHANNEL_NAMES[ch]:6} {count:5d} notas, altura mediana {median:.0f}, {distinct} alturas")
        else:
            print(f"  {vgm.CHANNEL_NAMES[ch]:6} {len(notes[ch]):5d} golpes")
    guess = auto_assign(notes)
    print("sugerencia: " + " ".join(f"--{k} {','.join(vgm.CHANNEL_NAMES[c] for c in v)}" for k, v in guess.items()))


def cmd_list(args: argparse.Namespace) -> None:
    for song in sorted(SONGS_DIR.glob("*/song.c")):
        text = song.read_text(encoding="utf-8")
        title = re.search(r"// TITULO: (.*)", text)
        print(f"  {song.parent.name:20} {title.group(1) if title else '?'}")


def cmd_build_audio(args: argparse.Namespace) -> None:
    """La música del título: audio/titulo.py escribe audio/titulo.vgm y aquí se convierte a src/titulo_music.c."""
    subprocess.run([sys.executable, str(ROOT / "audio" / "titulo.py")], check=True)
    data = vgm.read_vgm(ROOT / "audio" / "titulo.vgm")
    writes = [(vgm.frame_of(w.sample), w) for w in data.writes]
    loop = vgm.frame_of(data.loop_sample) if data.loop_sample is not None else 0
    stream, _, offset = vgm.frame_stream(writes, vgm.frame_of(data.total_samples), loop)
    out = [
        "// Generado por genband build-audio desde audio/titulo.py: no editar a mano",
        '#include "genband.h"',
        "",
        c_bytes("stream", stream),
        f"const u8 *const titulo_music = stream;\nconst u16 titulo_loop = {offset};\n",
    ]
    (ROOT / "src" / "titulo_music.c").write_text("\n".join(out), encoding="utf-8", newline="\n")
    print(f"src/titulo_music.c: {len(stream)} bytes, bucle en el byte {offset}")
    build_sfx()


SFX_CHANNEL = 2  # los efectos suenan en el tercer tono del PSG (ver music.c)


def build_sfx() -> None:
    """Los efectos de sonido, de audio/nesband/efectos.txt (los de NESBand), a src/sfx_data.c y src/sfx.h.

    Cada "canción" del proyecto es un efecto: sus notas, con la envolvente de volumen de su instrumento, se
    tocan en el tercer tono del PSG. En NESBand los efectos de fallo van dos veces (una por pulso, para no
    sonar en el canal de quien falló); aquí todos van en el mismo canal, así que se toma solo la primera."""
    path = ROOT / "audio" / "nesband" / "efectos.txt"
    attrs = lambda line: dict(re.findall(r'(\w+)="([^"]*)"', line))  # noqa: E731
    volumes: dict[str, list[int]] = {}
    effects: list[tuple[str, list[tuple[int, int, str, str]]]] = []
    instrument = None
    for line in path.read_text(encoding="utf-8").splitlines():
        a = attrs(line)
        kind = line.strip().split(" ", 1)[0]
        if kind == "Instrument":
            instrument = a["Name"]
        elif kind == "Envelope" and a.get("Type") == "Volume" and instrument:
            volumes[instrument] = [int(v) for v in a["Values"].split(",")]
        elif kind == "Song":
            effects.append((a["Name"], []))
        elif kind == "Note" and "Value" in a and effects:
            effects[-1][1].append((int(a["Time"]), int(a["Duration"]), a["Value"], a["Instrument"]))
    names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
    midi = lambda n: 12 * (int(n[-1]) + 1) + names.index(n[:-1])  # noqa: E731

    out = ["// Generado por genband build-audio desde audio/nesband/efectos.txt: no editar a mano", '#include "genband.h"', ""]
    header = ["// Generado por genband build-audio: los efectos de sonido (ver music.c, sfx_play)", "#ifndef SFX_H", "#define SFX_H", ""]
    labels = []
    for name, notes in effects:
        if name[-1] == "2":
            continue
        name = name.rstrip("1").upper()
        by_frame: dict[int, list[int]] = {}
        end = 0
        for time, duration, note, inst in notes:
            period = max(1, min(1023, round(vgm.PSG_CLOCK / (32 * 440 * 2 ** ((midi(note) - 69) / 12)))))
            writes = by_frame.setdefault(time, [])
            writes += [0x80 | (SFX_CHANNEL << 5) | (period & 0x0F), period >> 4]
            env = volumes.get(inst, [12])
            for k in range(duration):
                by_frame.setdefault(time + k, []).append(0x90 | (SFX_CHANNEL << 5) | (15 - env[min(k, len(env) - 1)]))
            end = max(end, time + duration)
        by_frame.setdefault(end, []).append(0x9F | (SFX_CHANNEL << 5))
        data = bytearray()
        for frame in range(end + 1):
            for value in by_frame.get(frame, []):
                data += bytes((vgm.CMD_PSG, value))
            data.append(vgm.CMD_FRAME)
        data.append(vgm.CMD_END)
        out.append(c_bytes(f"sfx_{name.lower()}", bytes(data)))
        header.append(f"#define SFX_{name} {len(labels)}")
        labels.append(f"sfx_{name.lower()}")
    out.append("const u8 *const sfx_streams[] = { " + ", ".join(labels) + " };\n")
    header += ["", "extern const u8 *const sfx_streams[];", "", "#endif", ""]
    (ROOT / "src" / "sfx_data.c").write_text("\n".join(out), encoding="utf-8", newline="\n")
    (ROOT / "src" / "sfx.h").write_text("\n".join(header), encoding="utf-8", newline="\n")
    print(f"src/sfx_data.c: {len(labels)} efectos")


FONT_COLOR = 15  # el índice de color del texto en todas las paletas (ver gfx.c)


def cmd_build_font(args: argparse.Namespace) -> None:
    """La fuente de las letras, de los tiles de NESBand (Bongo-8 Mono, de dominio público, CC0 1.0).

    Lee el src/font.s de NESBand (un tile por carácter, en texto: "." vacío y "1" la letra) y escribe
    src/font_data.c: un tile de 4 bits por carácter, con la letra en el color FONT_COLOR. Los tiles que
    en NESBand son dibujos del juego y no letras (la barra del bombo, en $22 y $23) se omiten; los
    caracteres que la fuente no trae se quedan con los de SGDK."""
    source = Path(args.source)
    text = source.read_text(encoding="utf-8")
    glyphs: dict[int, list[str]] = {}
    for code, rows in re.findall(r"TILE_AT \$([0-9A-Fa-f]{2})[^\n]*\nTILE ((?:\"[^\"]{8}\",?\s*){8})", text):
        rows = re.findall(r'"([^"]{8})"', rows)
        if any(c not in ".1" for row in rows for c in row):
            continue  # un dibujo del juego en otros colores
        glyphs[int(code, 16)] = rows
    out = [
        "// Generado por genband build-font desde el src/font.s de NESBand: no editar a mano.",
        "// Bongo-8 Mono, de Caffinate (Nathan Scott), de dominio público (CC0 1.0).",
        '#include "genband.h"',
        "",
        f"const u16 font_count = {len(glyphs)};",
        "const u8 font_codes[] = { " + ", ".join(f"0x{c:02X}" for c in sorted(glyphs)) + " };",
        "const u32 font_tiles[] = {",
    ]
    for code in sorted(glyphs):
        words = ["0x" + "".join("F" if c == "1" else "0" for c in row) for row in glyphs[code]]
        label = chr(code) if 32 < code < 127 else " "
        out.append(f"    {', '.join(words)},  // {label}")
    out.append("};\n")
    (ROOT / "src" / "font_data.c").write_text("\n".join(out), encoding="utf-8", newline="\n")
    print(f"src/font_data.c: {len(glyphs)} caracteres")


def cmd_edit_chart(args: argparse.Namespace) -> None:
    from . import editor  # (solo cuando se pide: editor importa este módulo)

    if args.html:
        if not args.name:
            raise SystemExit("--html necesita el nombre de la canción")
        editor.write_html(args.name, Path(args.html))
    else:
        editor.serve(args.name, args.port, not args.no_open)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="genband", description="Herramientas de PC para GENBand")
    sub = parser.add_subparsers(required=True)

    p = sub.add_parser("import-song", help="importa un VGM/VGZ y genera sus charts")
    p.add_argument("source")
    p.add_argument("--name", required=True, help="nombre de la carpeta en src/songs/ (minúsculas)")
    p.add_argument("--title")
    p.add_argument("--game")
    p.add_argument("--duration", type=float, help="segundos que se graban (si el VGM tiene bucle)")
    p.add_argument("--beat-frames", type=int, help="cuadros por tiempo, si el tempo detectado sale mal")
    for inst, _ in INSTRUMENTS:
        p.add_argument(f"--{inst}", help=f"canal(es) del {inst}: fm1..fm6, psg1..psg3 (separados por comas)")
    p.add_argument(f"--{DRUMS}", help="canales de la batería: ruido, fm6... (si no, el ruido y los que casi no cambian de tono)")
    p.set_defaults(func=cmd_import)

    p = sub.add_parser("reimport", help="vuelve a importar las canciones con sus mismas opciones")
    p.add_argument("names", nargs="*")
    p.set_defaults(func=cmd_reimport)

    p = sub.add_parser("channels", help="muestra las notas de cada canal de un VGM")
    p.add_argument("source")
    p.add_argument("--duration", type=float)
    p.set_defaults(func=cmd_channels)

    p = sub.add_parser("list-songs", help="lista las canciones de src/songs/")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("edit-chart", help="abre el editor de charts en el navegador")
    p.add_argument("name", nargs="?", help="la canción de src/songs/ (si no, se elige desde el menú Archivo)")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--no-open", action="store_true", help="no abrir el navegador")
    p.add_argument("--html", help="escribir una página de solo lectura en esta ruta, en vez de servir")
    p.set_defaults(func=cmd_edit_chart)

    p = sub.add_parser("build-font", help="convierte la fuente de NESBand (Bongo-8 Mono) a src/font_data.c")
    p.add_argument("source", nargs="?", default=str(ROOT.parent / "NESBand" / "src" / "font.s"))
    p.set_defaults(func=cmd_build_font)

    p = sub.add_parser("build-audio", help="convierte la música del título (audio/titulo.py)")
    p.set_defaults(func=cmd_build_audio)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
