import base64
import json
import re
import shutil
import subprocess
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from genband_tools import cli, editor, vgm
from genband_tools.chart import ChartNote
from genband_tools.chartedit import (
    apply_edits,
    chart_from_json,
    chart_problems,
    diff_charts,
    dump_edits,
    load_edits,
    save_edits,
    validate_chart,
)

CHART = [
    ChartNote(128, 0b00100),
    ChartNote(168, 0b00001, star=True),
    ChartNote(208, 0b00011, end=260),  # acorde con cola
    ChartNote(300, 0b01000, end=330, star=True),
    ChartNote(700, 0b10000),  # a más de 255 cuadros: lleva entradas de relleno
]


def test_apply_edits_add_delete_set():
    ops = [
        {"op": "delete", "frame": 128},
        {"op": "set", "frame": 168, "mask": 0b00010, "star": False},
        {"op": "set", "frame": 208, "end": None},
        {"op": "add", "frame": 150, "mask": 0b01000, "end": None, "star": False},
    ]
    result = apply_edits(CHART, ops)
    assert [n.frame for n in result] == [150, 168, 208, 300, 700]
    assert result[1] == ChartNote(168, 0b00010)
    assert result[2] == ChartNote(208, 0b00011)
    assert result[0] == ChartNote(150, 0b01000)


def test_apply_edits_warns_about_missing_notes():
    warnings = []
    result = apply_edits(CHART, [{"op": "delete", "frame": 999}, {"op": "set", "frame": 998, "mask": 1}], warnings.append)
    assert result == CHART
    assert len(warnings) == 2


def test_diff_is_inverse_of_apply():
    edited = [
        ChartNote(128, 0b00010),  # carril movido
        ChartNote(208, 0b00011),  # cola quitada
        ChartNote(250, 0b00100, star=True),  # agregada
        ChartNote(300, 0b01000, end=340, star=True),  # cola alargada
        ChartNote(700, 0b10000),
    ]
    ops = diff_charts(CHART, edited)
    assert {op["op"] for op in ops} == {"add", "delete", "set"}
    assert apply_edits(CHART, ops) == edited
    assert diff_charts(CHART, CHART) == []


def test_edits_file_round_trip(tmp_path):
    ops = diff_charts(CHART, [ChartNote(128, 0b00010)] + CHART[1:])
    save_edits(tmp_path, {"guitarra/facil": ops, "bajo/facil": []})
    text = (tmp_path / "edits.json").read_text(encoding="utf-8")
    assert json.loads(text)["charts"] == {"guitarra/facil": ops}  # los vacíos no se guardan
    assert "\r" not in text
    assert load_edits(tmp_path) == {"guitarra/facil": ops}
    assert dump_edits({}) == ""
    save_edits(tmp_path, {})
    assert not (tmp_path / "edits.json").exists()


def test_problems_blocked_pairs_and_sustain():
    assert not [p for p in chart_problems(CHART) if p["kind"] == "error"]
    chord = [ChartNote(10, 0b00101)]  # verde + amarillo: izquierda + derecha
    assert chart_problems(chord)[0]["kind"] == "error"
    clash = [ChartNote(10, 0b00001, end=100), ChartNote(50, 0b00001)]
    assert [p["frame"] for p in chart_problems(clash)] == [50]
    with pytest.raises(ValueError, match="guitarra/facil"):
        validate_chart("guitarra/facil", chord)
    validate_chart("guitarra/facil", CHART)


def test_problems_star_rules():
    chord_star = [ChartNote(10, 0b00011, star=True)]
    kinds = {p["text"] for p in chart_problems(chord_star)}
    assert any("acorde" in t for t in kinds)
    short_run = [ChartNote(f, 0b00001, star=True) for f in (10, 20)]
    assert any("frase estelar de 2" in p["text"] for p in chart_problems(short_run))
    run = [ChartNote(f, 0b00001, star=True) for f in (10, 20, 30, 40)]
    assert not chart_problems(run)


def test_chart_from_json_checks_input():
    notes = chart_from_json([{"frame": 20, "mask": 2}, {"frame": 10, "mask": 1, "end": 30, "star": True}])
    assert notes == [ChartNote(10, 1, 30, True), ChartNote(20, 2)]
    for bad in ({"frame": -1, "mask": 1}, {"frame": 1, "mask": 64}, {"frame": 1.5, "mask": 1}):
        with pytest.raises(ValueError):
            chart_from_json([bad])
    with pytest.raises(ValueError):
        chart_from_json([{"frame": 5, "mask": 1}, {"frame": 5, "mask": 2}])


def test_lanes_allowed_warning():
    assert any("fuera de los 3" in p["text"] for p in chart_problems([ChartNote(10, 0b01000)], 3))
    assert not chart_problems([ChartNote(10, 0b00100)], 3)


def make_source(tmp_path):
    notes = [Note(i * 10, 60 + (i % 5), 8) for i in range(60)]
    song = Song("Prueba", {"BeatLength": "4", "NoteLength": "5"}, [300, 300], {"Square1": notes, "Square2": notes[::2]})
    return editor.SongSource("prueba", tmp_path, {}, song, BeatGrid(20, 0), False)


# --- El editor de GENBand -----------------------------------------------------------------------


@pytest.fixture
def song_copy(tmp_path, monkeypatch):
    """Una copia de tormenta en una carpeta de canciones temporal (para no tocar src/songs/)."""
    songs = tmp_path / "songs"
    shutil.copytree(cli.SONGS_DIR / "tormenta", songs / "tormenta")
    (songs / "tormenta" / "edits.json").unlink(missing_ok=True)
    monkeypatch.setattr(cli, "SONGS_DIR", songs)
    monkeypatch.setattr(cli, "WORK_DIR", tmp_path / "work")
    return songs / "tormenta"


def test_payload_and_page(song_copy):
    sd = editor.load_song_source("tormenta")
    payload = editor.build_payload(sd)
    assert payload["title"] == "TORMENTA DE NEON"
    assert [i["name"] for i in payload["instruments"]] == ["guitarra", "teclado", "bajo", "bateria"]
    assert set(payload["channels"]) == {"fm1", "fm2", "fm3", "fm4", "fm5", "fm6", "psg1", "psg2", "psg3", "ruido"}
    assert payload["charts"] == payload["auto"]      # sin edits.json, el chart es el automático
    assert all(not p for p in payload["problems"].values())
    page = editor.render_page({**payload, "editable": True})
    assert "__DATA__" not in page and "__MENU__" not in page and "TORMENTA DE NEON" in page
    assert "__GENPLAYER__" not in page and "const GenPlayer" in page   # el reproductor va dentro de la página


def test_save_and_export_through_the_server(song_copy):
    sd = editor.load_song_source("tormenta")
    app = editor.App(sd)
    server = editor.ThreadingHTTPServer(("127.0.0.1", 0), type("H", (editor.Handler,), {"app": app}))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"

    def post(path, body):
        req = urllib.request.Request(base + path, json.dumps(body).encode(), {"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as res:
            return json.loads(res.read())

    try:
        payload = editor.build_payload(sd)
        charts = payload["charts"]
        # Una edición: la primera nota de guitarra/facil se va
        removed = charts["guitarra/facil"][0]["frame"]
        charts["guitarra/facil"] = charts["guitarra/facil"][1:]
        assert "guardado (1 ediciones)" in post("/api/save", {"song": "tormenta", "charts": charts})["message"]
        assert load_edits(song_copy)["guitarra/facil"] == [{"op": "delete", "frame": removed}]
        assert "song.c escrito" in post("/api/export", {"song": "tormenta", "charts": charts})["message"]
        # El song.c ya tiene una nota menos en guitarra/facil (el primer número de .notes)
        def first_count(text):
            return int(re.search(r"\.notes = \{\s*\{ (\d+)", text).group(1))
        original = (cli.ROOT / "src" / "songs" / "tormenta" / "song.c").read_text()
        assert first_count((song_copy / "song.c").read_text()) == first_count(original) - 1
        with pytest.raises(urllib.error.HTTPError):
            post("/api/save", {"song": "otra", "charts": charts})
        with urllib.request.urlopen(base + "/api/player") as res:
            player = json.loads(res.read())
        assert base64.b64decode(player["stream"]) == sd.stream and player["frames"] == sd.stream_frames
    finally:
        server.shutdown()


def test_song_and_source_lists():
    names = [s["name"] for s in editor.list_songs()]
    assert "tormenta" in names and "luna" in names
    assert any(s["path"] == "audio/tormenta.vgm" for s in editor.list_sources())


def test_import_rejects_bad_requests():
    app = editor.App()
    with pytest.raises(ValueError):
        editor.import_new_song(app, {"name": "Mala Cancion", "source": "audio/tormenta.vgm"})
    with pytest.raises(ValueError):
        editor.import_new_song(app, {"name": "tormenta", "source": "audio/tormenta.vgm"})
    with pytest.raises(ValueError):
        editor.import_new_song(app, {"name": "nueva_cancion", "source": "README.md"})


@pytest.mark.skipif(shutil.which("node") is None, reason="hace falta node para correr genplayer.js")
def test_genplayer_plays_tormenta(tmp_path):
    """genplayer.js (lo que usa Escuchar) toca la canción: suena, dura lo que dura el flujo, y la mezcla es
    la suma de los canales (así silencia el editor)."""
    sd = editor.load_song_source("tormenta")
    frames = 600   # los primeros 10 s bastan
    stream = tmp_path / "flujo.bin"
    stream.write_bytes(sd.stream)
    out = subprocess.run(["node", str(Path(__file__).with_name("genplayer_run.js")), str(stream), str(frames)],
                         capture_output=True, text=True, check=True)
    result = json.loads(out.stdout)
    assert result["samples"] == pytest.approx(frames / 59.9227 * 44100, abs=50)
    assert result["rms"] > 0.02
    assert result["mixError"] < 1e-3
    # Cada canal con notas en esos 10 s suena
    playing = {name for name, rms in zip(vgm.CHANNEL_NAMES, result["channels"]) if rms > 1e-3}
    with_notes = {vgm.CHANNEL_NAMES[ch] for ch, ns in sd.notes.items() if any(n.frame < frames for n in ns)}
    assert with_notes and with_notes <= playing
