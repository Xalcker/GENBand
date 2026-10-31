"""Editor visual de charts: una página HTML local (Canvas, sin dependencias) servida por `genband edit-chart`.

Es el editor de NESBand con los canales de la Genesis. La página muestra las notas de cada canal de la
canción (FM 1-6, los tonos del PSG, el ruido y el DAC) y el chart de un instrumento y dificultad. Los datos salen
de la misma tubería que `import-song` (cli.py: load_song, auto_charts); encima se aplican las ediciones de
edits.json (chartedit.py). Guardar escribe edits.json (y drums.json); Exportar además vuelve a importar la
canción, que es lo que regenera su song.c con las ediciones.

Aún no hay "Escuchar": tocar la canción en el navegador necesita un emulador del YM2612 y del PSG en
JavaScript (pendiente).
"""

from __future__ import annotations

import base64
import contextlib
import io
import json
import re
from http.server import ThreadingHTTPServer  # noqa: F401  (las pruebas arman el servidor con él)
from pathlib import Path

from bandcore import editor as bandeditor
from bandcore.editor import server as bandserver

from . import cli, vgm
from .chart import DIFFICULTIES, ChartNote, chart_size
from .chartedit import (
    EDITS_FILE,
    chart_problems,
    diff_charts,
    save_edits,
    validate_chart,
)
from .drums import ROLE_LABELS, ROLE_LANE, ROLES, check_assignment, drum_groups, load_drums, save_drums

# Las páginas (editor.html, home.html y el menú Archivo) son las de bandcore, compartidas con NESBand, GBBand y
# NGBand; aquí van el perfil de la Genesis y su reproductor
HTML_PATH = bandeditor.EDITOR_HTML
HOME_PATH = bandeditor.HOME_HTML  # la página sin canción abierta
GENPLAYER_PATH = Path(__file__).with_name("genplayer.js")  # el YM2612 y el PSG que tocan la canción

PROFILE = {
    "game": "GENBand",
    "cli": "genband",
    "pads": ["←/X", "↓/Y", "→/Z", "B", "C"],
    "channels": [
        {"id": "fm1", "label": "FM 1", "color": "#58d0ff", "discrete": False},
        {"id": "fm2", "label": "FM 2", "color": "#b58cff", "discrete": False},
        {"id": "fm3", "label": "FM 3", "color": "#6be88a", "discrete": False},
        {"id": "fm4", "label": "FM 4", "color": "#4fb8e8", "discrete": False},
        {"id": "fm5", "label": "FM 5", "color": "#c9a0ff", "discrete": False},
        {"id": "fm6", "label": "FM 6", "color": "#ff7a9c", "discrete": False},
        {"id": "psg1", "label": "PSG 1", "color": "#e8e070", "discrete": False},
        {"id": "psg2", "label": "PSG 2", "color": "#d0c860", "discrete": False},
        {"id": "psg3", "label": "PSG 3", "color": "#b8b050", "discrete": False},
        {"id": "ruido", "label": "Ruido", "color": "#ffb45e", "discrete": True, "pitchLabel": "tipo"},
        {"id": "dac", "label": "DAC", "color": "#ff6b5e", "discrete": True, "pitchLabel": "sample"},
    ],
    "drumInstrument": True,
    "exportLabel": "Exportar song.c",
    "exportTitle": "Guarda y vuelve a importar la canción: su song.c sale con los charts editados",
    "playerTitle": "Toca la canción con el YM2612 y el PSG emulados",
    "import": {
        "label": "VGM a importar (de songs_src/ o audio/)",
        "placeholder": "songs_src/juego/cancion.vgz",
        "hint": "Importar genera la música, los charts y la ficha en <code>src/songs/&lt;identificador&gt;/</code> "
                "(como <code>genband import-song</code>). Los canales de cada instrumento salen de la sugerencia "
                "automática: para elegirlos, usa la línea de comandos.",
        "status": "Importando…",
        "tracks": False,
        "durationLabel": "Segundos a grabar (si tiene bucle)",
        "durationPlaceholder": "120",
    },
}
# genplayer.js toca el flujo por cuadro de la canción (en base64) con los samples del DAC
_PLAYER_ADAPTER = """
window.BandPlayer = {
  FPS: GenPlayer.FPS,
  render(player, data, opts) {
    const bytes = (b64) => Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
    const dac = player.dac.map((d) => ({ data: bytes(d.data), rate: d.rate }));
    return GenPlayer.render(bytes(player.stream), player.frames, { ...opts, dac });
  },
};
"""

SOURCE_SUFFIXES = (".vgm", ".vgz")


def load_song_source(name: str) -> cli.SongData:
    options_file = cli.SONGS_DIR / name / "import.json"
    if not options_file.exists():
        raise ValueError(f"{name} no tiene import.json: impórtala con import-song (o elige una de src/songs/)")
    return cli.load_song(json.loads(options_file.read_text(encoding="utf-8")))


def chart_json(chart: list[ChartNote]) -> list[dict]:
    return [{"frame": n.frame, "mask": n.mask, "end": n.end, "star": n.star, "cymbal": n.cymbal} for n in chart]


def lanes_for(key: str) -> int:
    """Carriles de la dificultad de un chart ("guitarra/facil" -> 3)."""
    difficulty = key.split("/")[1]
    return next(d.lanes for d in DIFFICULTIES if d.name == difficulty)


def problems_for(key: str, chart: list[ChartNote]) -> list[dict]:
    # (en la batería todos los pads valen en todas las dificultades: los carriles por dificultad son de los
    # otros instrumentos; NESBand avisaba de más aquí)
    drums = key.startswith(cli.DRUMS + "/")
    return chart_problems(chart, 5 if drums else lanes_for(key), drums)


def build_payload(sd: cli.SongData) -> dict:
    """Todo lo que la página necesita, como JSON."""
    lead_in = cli.LEAD_IN
    assignment, suggested = cli.drum_assignment(sd)
    auto = cli.auto_charts(sd, assignment)
    charts, warnings = cli.edited_charts(sd, auto)
    channels = {name: [] for name in vgm.CHANNEL_NAMES}
    for ch, ns in sd.notes.items():
        channels[vgm.CHANNEL_NAMES[ch]] = [[lead_in + n.frame, n.pitch, n.duration] for n in ns]
    instruments = []
    for name, _ in cli.INSTRUMENTS:
        if any(k.startswith(name + "/") for k in charts):
            instruments.append({"name": name, "channel": ", ".join(vgm.CHANNEL_NAMES[c] for c in sd.assign[name])})
    if any(k.startswith(cli.DRUMS + "/") for k in charts):
        instruments.append({"name": cli.DRUMS, "channel": ", ".join(vgm.CHANNEL_NAMES[c] for c in sd.drums)})
    return {
        "drums": {
            "groups": [{"key": g.key, "channel": g.channel, "tone": g.tone, "instrument": g.instrument,
                        "count": g.count, "avgDuration": round(g.avg_duration, 1)}
                       for g in (drum_groups(sd.notes, sd.drums) if sd.drums else [])],
            "assignment": assignment or {},
            "suggested": suggested,
            "roles": [{"id": role, "label": ROLE_LABELS[role], "lane": ROLE_LANE[role]} for role in ROLES],
        },
        "name": sd.name,
        "title": sd.title,
        "game": sd.game,
        "leadIn": lead_in,
        "endFrame": lead_in + sd.stream_frames,
        "framesPerBeat": sd.grid.frames_per_beat,
        "firstBeat": lead_in + sd.grid.first_beat,
        # [cuadro, altura, duración] por canal; los cuadros ya cuentan la entrada de la autopista
        "channels": channels,
        "instruments": instruments,
        "difficulties": [{"name": d.name, "lanes": d.lanes} for d in DIFFICULTIES],
        "charts": {key: chart_json(chart) for key, chart in charts.items()},
        "auto": {key: chart_json(chart) for key, chart in auto.items()},
        "problems": {key: problems_for(key, chart) for key, chart in charts.items()},
        "warnings": warnings,
        "chartBytes": sum(chart_size(chart) for chart in charts.values()),
        "editable": False,
    }


def save_edits_from_page(sd: cli.SongData, charts: dict[str, list[ChartNote]],
                         assignment: dict | None = None) -> dict[str, list[dict]]:
    """Guarda en edits.json lo que difiere de los charts automáticos (y en drums.json la asignación de la
    batería, si la manda la página). Falla si algún chart no se puede tocar."""
    if assignment is not None:
        check_assignment(assignment)
    auto = cli.auto_charts(sd, assignment)
    if set(charts) != set(auto):
        raise ValueError(f"faltan o sobran charts: se esperaban {sorted(auto)}")
    edits = {}
    for key, chart in charts.items():
        validate_chart(key, chart)
        edits[key] = diff_charts(auto[key], chart)
    if assignment is None and load_drums(sd.folder) is None and any(
            ops for key, ops in edits.items() if key.startswith(cli.DRUMS + "/")):
        assignment = cli.drum_assignment(sd)[0]   # las ediciones de la batería van atadas a su asignación
    if assignment is not None:
        save_drums(sd.folder, assignment)
    save_edits(sd.folder, edits)
    return edits


def export_song(sd: cli.SongData, charts: dict[str, list[ChartNote]], assignment: dict | None = None) -> str:
    """Guarda las ediciones y vuelve a importar la canción: su song.c sale con los charts editados."""
    save_edits_from_page(sd, charts, assignment)
    log = io.StringIO()
    with contextlib.redirect_stdout(log):
        cli.import_song(sd.opts)
    return f"song.c escrito ({sum(chart_size(c) for c in charts.values())} bytes de charts)\n{log.getvalue()}"


def render_page(payload: dict, template: Path = HTML_PATH) -> str:
    """La página del editor de bandcore con el perfil de la Genesis."""
    player = GENPLAYER_PATH.read_text(encoding="utf-8") + _PLAYER_ADAPTER
    return bandeditor.render_page(payload, PROFILE, player, template)


def player_payload(sd: cli.SongData) -> dict:
    """El flujo de la música (el mismo que va en song.c) y los samples del DAC, para que la página lo toque
    con genplayer.js."""
    return {
        "stream": base64.b64encode(sd.stream).decode("ascii"),
        "frames": sd.stream_frames,
        "dac": [{"data": base64.b64encode(s.data).decode("ascii"), "rate": vgm.PCM_RATES[s.rate]} for s in sd.dac_samples],
    }


# --- Menú Archivo: canciones disponibles, fuentes para importar y la canción abierta -----------


def list_songs() -> list[dict]:
    songs = []
    for options in sorted(cli.SONGS_DIR.glob("*/import.json")):
        song_c = options.parent / "song.c"
        title = re.search(r"// TITULO: (.*)", song_c.read_text(encoding="utf-8")) if song_c.exists() else None
        game = re.search(r'\.game = "([^"]*)"', song_c.read_text(encoding="utf-8")) if song_c.exists() else None
        songs.append({
            "name": options.parent.name,
            "title": title.group(1) if title else options.parent.name,
            "game": game.group(1) if game else "",
            "edited": (options.parent / EDITS_FILE).exists(),
        })
    return songs


def list_sources() -> list[dict]:
    """Archivos que se pueden importar como canción nueva: los VGM de songs_src/ y de audio/."""
    found = []
    for folder in (cli.ROOT / "songs_src", cli.ROOT / "audio"):
        for path in sorted(folder.rglob("*")) if folder.is_dir() else []:
            if path.suffix.lower() in SOURCE_SUFFIXES:
                found.append({"path": path.relative_to(cli.ROOT).as_posix(), "name": path.stem})
    return found


def resolve_source(text: str) -> Path:
    path = Path(text.strip().strip('"'))
    path = path if path.is_absolute() else cli.ROOT / path
    if path.suffix.lower() not in SOURCE_SUFFIXES or not path.is_file():
        raise ValueError(f"no encontré un archivo .vgm o .vgz en {path}")
    return path


def load_named_song(name: str) -> cli.SongData:
    if not re.fullmatch(r"[a-z][a-z0-9_]*", name) or not (cli.SONGS_DIR / name / "import.json").exists():
        raise ValueError(f"no existe la canción {name}")
    try:
        return load_song_source(name)
    except SystemExit as error:
        raise ValueError(str(error.code)) from None


def import_source(body: dict) -> tuple[cli.SongData, str]:
    """Importa una canción nueva (como `genband import-song`): la canción ya cargada y lo que imprimió el importador."""
    name = str(body.get("name", "")).strip()
    if not re.fullmatch(r"[a-z][a-z0-9_]*", name):
        raise ValueError("el identificador son minúsculas, números y _ (empezando con letra)")
    if (cli.SONGS_DIR / name).exists():
        raise ValueError(f"ya existe la canción {name}: ábrela, o elige otro identificador")
    source = resolve_source(str(body.get("source", "")))
    try:
        rel = source.relative_to(cli.ROOT).as_posix()
    except ValueError:
        rel = str(source)
    opts = {"name": name, "source": rel}
    for key in ("title", "game", "duration", "beat_frames", "guitarra", "teclado", "bajo", cli.DRUMS):
        if body.get(key):
            opts[key] = body[key]
    log = io.StringIO()
    try:
        with contextlib.redirect_stdout(log):
            cli.import_song(opts)
    except SystemExit as error:
        raise ValueError(str(error.code)) from None
    except (RuntimeError, FileNotFoundError) as error:
        raise ValueError(str(error)) from None
    return load_named_song(name), log.getvalue()


# --- Servidor: el de bandcore, con lo propio de la Genesis -------------------------------------------------

class Game(bandserver.EditorGame):
    profile = PROFILE

    def player_js(self) -> str:
        return GENPLAYER_PATH.read_text(encoding="utf-8") + _PLAYER_ADAPTER

    def open(self, name: str) -> cli.SongData:
        return load_named_song(name)

    def payload(self, sd: cli.SongData) -> dict:
        return build_payload(sd)

    def player(self, sd: cli.SongData) -> dict:
        return player_payload(sd)

    def problems(self, key: str, chart: list[ChartNote]) -> list[dict]:
        return problems_for(key, chart)

    def drums(self, sd: cli.SongData, assignment: dict) -> dict:
        # Otra asignación: los charts de batería se rehacen (con las ediciones ya guardadas encima)
        check_assignment(assignment)
        auto = cli.auto_charts(sd, assignment)
        charts, warnings = cli.edited_charts(sd, auto)
        drums = lambda d: {k: v for k, v in d.items() if k.startswith(cli.DRUMS + "/")}  # noqa: E731
        return {
            "charts": {k: chart_json(c) for k, c in drums(charts).items()},
            "auto": {k: chart_json(c) for k, c in drums(auto).items()},
            "problems": {k: problems_for(k, c) for k, c in drums(charts).items()},
            "warnings": warnings,
        }

    def save(self, sd: cli.SongData, charts: dict, assignment: dict | None) -> dict:
        return save_edits_from_page(sd, charts, assignment)

    def export(self, sd: cli.SongData, charts: dict, assignment: dict | None) -> tuple[str, cli.SongData]:
        return export_song(sd, charts, assignment), sd

    def songs(self) -> list[dict]:
        return list_songs()

    def sources(self) -> list[dict]:
        return list_sources()

    def import_song(self, body: dict) -> tuple[cli.SongData, str]:
        return import_source(body)


GAME = Game()
Handler = bandserver.Handler


class App(bandserver.App):
    """La canción abierta (o ninguna) del servidor; `sd` es la canción (`song` en bandcore)."""

    def __init__(self, sd: cli.SongData | None = None):
        super().__init__(GAME, sd)

    @property
    def sd(self) -> cli.SongData | None:
        return self.song

    @sd.setter
    def sd(self, value: cli.SongData | None) -> None:
        self.song = value


def open_song(app: App, name: str) -> None:
    app.song = GAME.open(name)


def import_new_song(app: App, body: dict) -> str:
    """Importa una canción nueva (como `genband import-song`), la abre y devuelve lo que imprimió el importador."""
    app.song, log = GAME.import_song(body)
    return log


def write_html(name: str, path: Path) -> None:
    """Una página de solo lectura (sin servidor) con la canción `name`."""
    path.write_text(render_page(build_payload(load_song_source(name))), encoding="utf-8", newline="\n")
    print(f"{path}: página de solo lectura de {name}")


def serve(name: str | None, port: int, open_browser: bool) -> None:
    bandserver.serve(App(load_song_source(name) if name else None), port, open_browser)
