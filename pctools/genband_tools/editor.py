"""Editor visual de charts: una página HTML local (Canvas, sin dependencias) servida por `genband edit-chart`.

Es el editor de NESBand con los canales de la Genesis. La página muestra las notas de cada canal de la
canción (FM 1-6, los tonos del PSG y el ruido) y el chart de un instrumento y dificultad. Los datos salen
de la misma tubería que `import-song` (cli.py: load_song, auto_charts); encima se aplican las ediciones de
edits.json (chartedit.py). Guardar escribe edits.json (y drums.json); Exportar además vuelve a importar la
canción, que es lo que regenera su song.c con las ediciones.

Aún no hay "Escuchar": tocar la canción en el navegador necesita un emulador del YM2612 y del PSG en
JavaScript (pendiente).
"""

from __future__ import annotations

import contextlib
import io
import json
import re
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from . import cli, vgm
from .chart import DIFFICULTIES, ChartNote, chart_size
from .chartedit import (
    EDITS_FILE,
    chart_from_json,
    chart_problems,
    diff_charts,
    save_edits,
    validate_chart,
)
from .drums import ROLE_LABELS, ROLE_LANE, ROLES, check_assignment, drum_groups, load_drums, save_drums

HTML_PATH = Path(__file__).with_name("editor.html")
HOME_PATH = Path(__file__).with_name("home.html")  # la página sin canción abierta
MENU_PATH = Path(__file__).with_name("menu.html")  # el menú Archivo, compartido por las dos

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
    data = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).replace("</", "<\\/")
    menu = MENU_PATH.read_text(encoding="utf-8")
    return template.read_text(encoding="utf-8").replace("__MENU__", menu, 1).replace("__DATA__", data, 1)


# --- Menú Archivo: canciones disponibles, fuentes para importar y la canción abierta -----------


class App:
    """La canción abierta (o ninguna) del servidor. Un candado evita que dos acciones se pisen."""

    def __init__(self, sd: cli.SongData | None = None):
        self.sd = sd
        self.lock = threading.RLock()


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


def open_song(app: App, name: str) -> None:
    if not re.fullmatch(r"[a-z][a-z0-9_]*", name) or not (cli.SONGS_DIR / name / "import.json").exists():
        raise ValueError(f"no existe la canción {name}")
    try:
        app.sd = load_song_source(name)
    except SystemExit as error:
        raise ValueError(str(error.code)) from None


def import_new_song(app: App, body: dict) -> str:
    """Importa una canción nueva (como `genband import-song`), la abre y devuelve lo que imprimió el importador."""
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
    open_song(app, name)
    return log.getvalue()


class Handler(BaseHTTPRequestHandler):
    app: App  # lo fija serve()

    def log_message(self, format, *args):  # sin ruido en la terminal
        pass

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, data: dict) -> None:
        self._send(status, json.dumps(data).encode("utf-8"), "application/json")

    def do_GET(self) -> None:
        url = urlparse(self.path)
        try:
            with self.app.lock:
                if url.path == "/":
                    if self.app.sd is None:
                        page = render_page({"home": True}, HOME_PATH)
                    else:
                        page = render_page({**build_payload(self.app.sd), "editable": True})
                    self._send(200, page.encode("utf-8"), "text/html; charset=utf-8")
                elif url.path == "/api/songs":
                    self._json(200, {"songs": list_songs()})
                elif url.path == "/api/sources":
                    self._json(200, {"sources": list_sources()})
                else:
                    self._send(404, b"no encontrado", "text/plain; charset=utf-8")
        except (ValueError, KeyError) as error:
            self._json(400, {"error": str(error)})

    def do_POST(self) -> None:
        # Solo la propia página: otro origen (una web cualquiera) no puede escribir en el proyecto
        if self.headers.get("Origin") not in (None, f"http://{self.headers.get('Host')}"):
            self._json(403, {"error": "origen no permitido"})
            return
        app = self.app
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            with app.lock:
                if self.path == "/api/open":
                    open_song(app, str(body.get("name", "")))
                    self._json(200, {"message": f"abierta {app.sd.name}"})
                elif self.path == "/api/close":
                    app.sd = None
                    self._json(200, {"message": "cerrada"})
                elif self.path == "/api/import":
                    self._json(200, {"message": import_new_song(app, body)})
                elif self.path in ("/api/validate", "/api/save", "/api/export", "/api/drums"):
                    sd = app.sd
                    if sd is None or body.get("song") != sd.name:
                        raise ValueError("la canción de esta página ya no es la abierta: recarga la página")
                    if self.path == "/api/validate":
                        self._json(200, {"problems": problems_for(body["key"], chart_from_json(body["chart"]))})
                    elif self.path == "/api/drums":
                        # Otra asignación: los charts de batería se rehacen (con las ediciones ya guardadas encima)
                        check_assignment(body["assignment"])
                        auto = cli.auto_charts(sd, body["assignment"])
                        charts, warnings = cli.edited_charts(sd, auto)
                        drums = lambda d: {k: v for k, v in d.items() if k.startswith(cli.DRUMS + "/")}  # noqa: E731
                        self._json(200, {
                            "charts": {k: chart_json(c) for k, c in drums(charts).items()},
                            "auto": {k: chart_json(c) for k, c in drums(auto).items()},
                            "problems": {k: problems_for(k, c) for k, c in drums(charts).items()},
                            "warnings": warnings,
                        })
                    else:
                        charts = {key: chart_from_json(items) for key, items in body["charts"].items()}
                        assignment = body.get("drums")
                        if self.path == "/api/save":
                            edits = save_edits_from_page(sd, charts, assignment)
                            count = sum(len(ops) for ops in edits.values())
                            self._json(200, {"message": f"guardado ({count} ediciones)"})
                        else:
                            self._json(200, {"message": export_song(sd, charts, assignment)})
                else:
                    self._json(404, {"error": "no encontrado"})
        except (ValueError, KeyError, TypeError) as error:
            self._json(400, {"error": str(error)})


def write_html(name: str, path: Path) -> None:
    """Una página de solo lectura (sin servidor) con la canción `name`."""
    path.write_text(render_page(build_payload(load_song_source(name))), encoding="utf-8")
    print(f"{path}: página de solo lectura de {name}")


def serve(name: str | None, port: int, open_browser: bool) -> None:
    app = App(load_song_source(name) if name else None)
    Bound = type("Bound", (Handler,), {"app": app})
    server = ThreadingHTTPServer(("127.0.0.1", port), Bound)
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    print(f"Editor de charts{f' de {name!r}' if name else ''}: {url}  (Ctrl+C para cerrar)")
    if open_browser:
        threading.Timer(0.3, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()
    finally:
        server.server_close()
