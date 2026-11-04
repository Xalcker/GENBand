"""Pruebas de GENBand en MAME: los casos y el revisor de lo que deja el bot (tests/autoplay.lua).

Se corren con ``uv run genband test`` (ver ``bandcore.testrun``). Cada caso arranca MAME en ventana con las
variables GENBAND_* que lee el bot; el bot juega y escribe ``resultado.txt``, ``bot.log`` y capturas en
``build/test-<caso>/``, y aquí se comprueba lo que debe cumplir.
"""
from __future__ import annotations

import re
from pathlib import Path

from bandcore import testrun
from bandcore.testrun import Case, Result

ROOT = Path(__file__).resolve().parents[2]

# nombre, canción, instrumento, dificultad, modo [, opciones] -- los dos últimos campos de TWO son del 2º jugador
# TWO = (jugadores, instrumento2, dificultad2, modo2)
_SINGLE = [
    ("tormenta-guitarra-experto", "tormenta", 0, 3, "perfecto"),
    ("tormenta-bajo-dificil", "tormenta", 2, 2, "perfecto"),
    ("tormenta-teclado-facil", "tormenta", 1, 0, "perfecto"),
    ("tormenta-nada", "tormenta", 0, 1, "nada"),
    ("tormenta-sinfallo", "tormenta", 0, 0, "sinfallo"),
    ("tormenta-mitad", "tormenta", 0, 3, "mitad"),
    ("tormenta-aire", "tormenta", 0, 2, "aire"),
    ("carrera-guitarra-experto", "carrera", 0, 3, "perfecto"),
    ("cumbia-bajo-experto", "cumbia", 2, 3, "perfecto"),
    ("luna-teclado-dificil", "luna", 1, 2, "perfecto"),
    ("demo-guitarra-medio", "demo", 0, 1, "perfecto"),
]
# Batería: el bot toca los pads y el bombo (carril naranja, C)
_DRUMS = [
    ("tormenta-bateria-experto", "tormenta", 3, 3, "perfecto"),
    ("cumbia-bateria-facil", "cumbia", 3, 0, "perfecto"),
]
# Opciones: espejo, velocidad (75% y 125%) y práctica (de 1/2 a 3/4: debe repetirse)
_OPTIONS = [
    ("tormenta-espejo", "tormenta", 0, 3, "perfecto", "espejo=1"),
    ("tormenta-lenta", "tormenta", 0, 3, "perfecto", "velocidad=1"),
    ("tormenta-rapida", "tormenta", 0, 3, "perfecto", "velocidad=3 caida=4"),
    ("marcha-practica", "marcha", 0, 2, "practica", "practica=3 inicio=2"),
    ("marcha-marcas", "marcha", 0, 2, "marcas", "practica=4 inicio=1"),
]
# Dos jugadores: VS con el mismo chart (empate), VS donde J2 pierde (la partida se corta y gana J1),
# Co-Op perfecto (guitarra y bajo) y Co-Op con J2 caído (la banda sigue)
_TWO = [
    ("vs-empate", "tormenta", 0, 3, "perfecto", (1, 0, 3, "perfecto")),
    ("vs-j2-pierde", "tormenta", 0, 3, "perfecto", (1, 0, 3, "nada")),
    ("coop-perfecto", "tormenta", 0, 3, "perfecto", (2, 2, 2, "perfecto")),
    ("coop-j2-cae", "carrera", 0, 2, "perfecto", (2, 3, 1, "nada")),
]
RAPIDA = {"tormenta-guitarra-experto", "tormenta-nada", "tormenta-sinfallo", "demo-record", "demo-record-persiste",
          "tormenta-bateria-experto", "vs-empate", "coop-perfecto", "tormenta-espejo", "marcha-practica"}


def song_index(root: Path, song: str) -> int | None:
    """El lugar de una canción en el menú: el orden de build/song_list.c (cambia con las canciones importadas)."""
    lst = root / "build" / "song_list.c"
    if not lst.exists():
        return None
    names = [m.group(1) for ln in lst.read_text(encoding="utf-8").splitlines()
             if (m := re.match(r"^    &song_(\w+?),?$", ln))]
    return names.index(song) if song in names else None


def build_cases(args, root: Path = ROOT) -> list[Case]:
    sym = root / "build" / "genband.sym"
    cases: list[Case] = []

    def add(name, song, instr, diff, mode, opts="", two=None, nvram=None, fresh=False, skip_missing=False):
        idx = song_index(root, song)
        c = Case(name, check=check_case, serial=nvram is not None, nvram=nvram, fresh_nvram=fresh)
        if idx is None:
            c.skip = f"la canción {song} no está en build/song_list.c"
        else:
            players, instr2, diff2, mode2 = two or (0, 0, 0, "perfecto")
            c.env = {"GENBAND_SYM": str(sym), "GENBAND_OUT": str(root / "build" / f"test-{name}"),
                     "GENBAND_SONG": str(idx), "GENBAND_INSTR": str(instr), "GENBAND_DIFF": str(diff),
                     "GENBAND_MODE": mode, "GENBAND_OPTS": opts, "GENBAND_PLAYERS": str(players),
                     "GENBAND_INSTR2": str(instr2), "GENBAND_DIFF2": str(diff2), "GENBAND_MODE2": mode2}
        c.extra = {"mode": mode, "players": (two or (0,))[0], "mode2": (two or (0, 0, 0, "perfecto"))[3], "opts": opts}
        cases.append(c)

    nv_rec, nv_vs = root / "build" / "test-nvram-records", root / "build" / "test-nvram-vs"
    for n, s, i, d, m in _SINGLE:
        add(n, s, i, d, m)
    # Récords: con la SRAM vacía, el juego perfecto es récord y se escriben las iniciales; al volver a encender
    # (la misma carpeta de nvram, que es donde MAME guarda la SRAM), el récord sigue ahí
    add("demo-record", "demo", 0, 1, "record", nvram=nv_rec, fresh=True)
    add("demo-record-persiste", "demo", 0, 1, "leer_record", nvram=nv_rec)
    for n, s, i, d, m in _DRUMS:
        add(n, s, i, d, m)
    for n, s, i, d, m, two in _TWO:
        add(n, s, i, d, m, two=two)
    add("vs-record", "demo", 0, 1, "record", two=(1, 1, 1, "perfecto"), nvram=nv_vs, fresh=True)
    for n, s, i, d, m, o in _OPTIONS:
        add(n, s, i, d, m, opts=o)
    # La batería sampleada (DAC): solo si están las canciones de Sonic importadas (ver el README; no van en git)
    if (root / "src" / "songs" / "ghz" / "song.c").exists():
        add("ghz-bateria-experto", "ghz", 3, 3, "perfecto")
        add("ghz-vs-guitarra-bateria", "ghz", 0, 3, "perfecto", two=(1, 3, 3, "perfecto"))
    if getattr(args, "rapida", False):
        cases = [c for c in cases if c.name in RAPIDA]
    return cases


def emulator(root: Path = ROOT, window: bool = True) -> testrun.Mame:
    rom = root / "build" / "genband.bin"
    return testrun.Mame(lambda case: ["genesis", "-cart", str(rom)], root / "tests" / "autoplay.lua", window=window,
                        resolution="640x448")


def check_case(case: Case, d: Path, code: int) -> Result:
    mode, players = case.extra["mode"], case.extra["players"]
    mode2, opts = case.extra["mode2"], case.extra["opts"]
    r, n = testrun.read_result(d)
    problems: list[str] = []
    if mode == "perfecto":
        # (con 2 jugadores el combo y las estrellas de J1 dependen del otro: en Co-Op son de la banda y en VS la
        # partida se corta si el otro pierde; eso se revisa abajo)
        solo_or_clean = not players or (players == 1 and mode2 == "perfecto")
        if n["notas"] != n["total"] and not (players == 1 and mode2 == "nada"):
            problems.append(f"acertó {n['notas']} de {n['total']}")
        if solo_or_clean and n["combo_max"] != n["total"]:
            problems.append(f"combo máximo {n['combo_max']} (debe ser {n['total']})")
        if solo_or_clean and n["estrellas"] != 5:
            problems.append(f"{n['estrellas']} estrellas")
        if n["fallo"]:
            problems.append("perdió")
    elif mode == "nada":
        if not n["fallo"]:
            problems.append("no perdió sin tocar nada")
    elif mode == "sinfallo":
        if n["fallo"]:
            problems.append("perdió con SIN FALLO")
        if n["notas"]:
            problems.append("acertó notas sin tocar")
    elif mode == "aire":
        if n["notas"] != n["total"]:
            problems.append(f"acertó {n['notas']} de {n['total']}")
        if n["combo_max"] >= n["total"]:
            problems.append("los golpes al aire no rompieron el combo")
        if n["fallo"]:
            problems.append("perdió")
    elif mode == "record":
        if n["notas"] != n["total"]:
            problems.append(f"acertó {n['notas']} de {n['total']}")
        if not n["nuevo_record"]:
            problems.append("no dijo NUEVO RECORD (con la SRAM vacía)")
        if n["record"] != n["puntaje"] or r.get("iniciales") != "BOT":
            problems.append(f"el récord guardado es {n['record']} {r.get('iniciales')} (debía ser {n['puntaje']} BOT)")
    elif mode == "leer_record":
        if not n["record"] or r.get("iniciales") != "BOT":
            problems.append(f"al volver a encender, el récord es {n['record']} {r.get('iniciales')}")
    elif mode == "practica":
        if int(r.get("vueltas", 0)) < 2:
            problems.append(f"la práctica no se repitió (vueltas: {r.get('vueltas')})")
    elif mode == "marcas":
        if int(r.get("vueltas", 0)) < 3:
            problems.append(f"la práctica no se repitió (vueltas: {r.get('vueltas')})")
        if abs(int(r["fin_bucle"]) - int(r["marca"])) > 5:
            problems.append(f"el bucle terminó en {r['fin_bucle']} y la marca de fin estaba en {r['marca']}")
    elif mode == "mitad":
        if n["notas"] == 0:                                   # (fallar la mitad puede costar la canción)
            problems.append("no acertó ninguna")
    if players:
        # Dos jugadores: lo del jugador 2, la banda (Co-Op) y quién ganó (VS)
        if mode2 == "perfecto" and n["j2_notas"] != n["j2_total"]:
            problems.append(f"J2 acertó {n['j2_notas']} de {n['j2_total']}")
        if players == 1:
            if mode == mode2 == "perfecto" and n["ganador"] != (
                    0 if n["puntaje"] == n["j2_puntaje"] else (1 if n["puntaje"] > n["j2_puntaje"] else 2)):
                problems.append(f"ganador {n['ganador']} con {n['puntaje']} contra {n['j2_puntaje']}")
            if mode2 == "nada" and (not n["j2_fallo"] or n["ganador"] != 1):
                problems.append(f"J2 no perdió o no ganó J1 (ganador {n['ganador']})")
        if players == 2:
            if mode == mode2 == "perfecto" and (n["banda_notas"] != n["banda_total"] or n["banda_estrellas"] != 5):
                problems.append(f"la banda: {n['banda_notas']}/{n['banda_total']}, {n['banda_estrellas']} estrellas")
            if mode2 == "nada" and (not n["j2_fallo"] or n["banda_fallo"]):
                problems.append(f"en Co-Op, con J2 caído la banda debe seguir (J2 cayó {n['j2_fallo']}, "
                                f"banda perdió {n['banda_fallo']})")
        if mode2 == "nada" and players == 1 and n["notas"] == n["total"]:
            problems.append("en VS, si J2 pierde la partida se corta: J1 no debía terminar la canción")
    # Cuadros perdidos: el bot anota cada 600 cuadros en qué cuadro de la canción va; si un cuadro del juego no
    # cabe en uno de la consola, la canción (y la música) se atrasa. Con VELOCIDAD los pasos por cuadro cambian a
    # propósito, así que ahí no se mide.
    if "velocidad" not in opts:
        marks = []
        for line in (d / "bot.log").read_text(encoding="utf-8", errors="replace").splitlines():
            if "cuadro de la canción" in line and "jugando" in line:
                f = line.split()
                marks.append((int(f[0]), int(f[7].rstrip(","))))
        lost = sum(600 - (b[1] - a[1]) for a, b in zip(marks, marks[1:]) if b[0] - a[0] == 600 and 0 < b[1] - a[1] <= 600)
        r["perdidos"] = str(lost)
        if lost > 5:
            problems.append(f"se perdieron {lost} cuadros (el bucle del juego no cupo en un cuadro)")
    # El audio: que haya sonado algo durante el juego
    try:
        rms = testrun.wav_rms(d / "audio.wav")
        r["audio_rms"] = f"{rms:.0f}"
        if rms < 200:
            problems.append(f"el audio está casi en silencio (RMS {rms:.0f})")
    except Exception as e:
        problems.append(f"no se pudo leer el audio: {e}")
    status = testrun.FAIL if problems else testrun.OK
    if mode == "leer_record":
        return Result(status, f"récord {r.get('record')} {r.get('iniciales')}", problems)
    if mode in ("practica", "marcas"):
        return Result(status, f"vueltas {r.get('vueltas')}, marca {r.get('marca')}, fin del bucle "
                              f"{r.get('fin_bucle')}, audio RMS {r.get('audio_rms')}", problems)
    extra = ""
    if players:
        extra = f", J2 {n['j2_notas']}/{n['j2_total']} fallo {n['j2_fallo']}"
        extra += f", ganador {n['ganador']}" if players == 1 else f", banda {n['banda_puntaje']} {n['banda_estrellas']}*"
    return Result(status, f"notas {n['notas']}/{n['total']}, puntaje {n['puntaje']}, estrellas {n['estrellas']}, "
                          f"combo {n['combo_max']}, fallo {n['fallo']}, audio RMS {r.get('audio_rms')}, "
                          f"cuadros perdidos {r.get('perdidos', '-')}{extra}", problems)
