#!/usr/bin/env bash
# Pruebas de GENBand en MAME: el bot (tests/autoplay.lua) juega cada caso y se revisa su resultado.
# MAME corre sin video (-video none) y en ventana (-window), para que no tome la pantalla completa.
#
#   tests/run_tests.sh              compila y corre todos los casos
#   tests/run_tests.sh --no-build   con la ROM que ya está en build/
#   tests/run_tests.sh '*-nada'     solo los casos cuyo nombre coincide (acepta comodines)
#
# Cada caso deja en build/test-<nombre>/ el resultado (resultado.txt), el registro del bot, las capturas
# de pantalla y el audio (audio.wav), y aquí se comprueba lo que debe cumplir.
set -uo pipefail
cd "$(dirname "$0")/.."

build=1
only=""
for arg in "$@"; do
    case "$arg" in
        --no-build) build=0 ;;
        *) only="$arg" ;;
    esac
done
if [ $build = 1 ]; then
    ./build.sh || exit 1
fi
command -v mame >/dev/null || { echo "Falta MAME: brew install mame" >&2; exit 1; }

ROM="$PWD/build/genband.bin"
SYM="$PWD/build/genband.sym"
fails=0

# caso: nombre canción instrumento dificultad modo [opciones] [nvram]
# (con 2 jugadores: TWO="modo instrumento2 dificultad2 modo2" antes de run_case)
run_case() {
    local name=$1 song=$2 instr=$3 diff=$4 mode=$5 opts=${6:-} nvram=${7:-}
    local players=0 instr2=0 diff2=0 mode2=perfecto
    if [ -n "${TWO:-}" ]; then read -r players instr2 diff2 mode2 <<< "$TWO"; fi
    if [ -n "$only" ] && [[ "$name" != $only ]]; then return; fi
    local dir="$PWD/build/test-$name"
    rm -rf "$dir"
    mkdir -p "$dir"
    GENBAND_SYM="$SYM" GENBAND_OUT="$dir" GENBAND_SONG=$song GENBAND_INSTR=$instr GENBAND_DIFF=$diff \
    GENBAND_MODE=$mode GENBAND_OPTS="$opts" GENBAND_PLAYERS=$players GENBAND_INSTR2=$instr2 GENBAND_DIFF2=$diff2 \
    GENBAND_MODE2=$mode2 mame genesis -cart "$ROM" -window -nomaximize -frameskip 0 -noautoframeskip -video none -sound none -nothrottle -skip_gameinfo \
        -wavwrite "$dir/audio.wav" -snapshot_directory "$dir" -cfg_directory "$dir/cfg" \
        -nvram_directory "${nvram:-$dir/nvram}" -autoboot_script tests/autoplay.lua >"$dir/mame.log" 2>&1
    if [ ! -f "$dir/resultado.txt" ]; then
        echo "FALLA $name: el bot no llegó a los resultados (ver $dir/bot.log y mame.log)"
        fails=$((fails + 1))
        return
    fi
    python3 - "$dir" "$mode" "$name" "$players" "$mode2" <<'PY' || fails=$((fails + 1))
import math, struct, sys, wave
from pathlib import Path
d, mode, name = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
players, mode2 = int(sys.argv[4]), sys.argv[5]
r = dict(line.strip().split("=", 1) for line in open(d / "resultado.txt") if "=" in line)
n = {k: int(v) for k, v in r.items() if v.lstrip("-").isdigit()}
problems = []
if mode == "perfecto":
    # (con 2 jugadores el combo y las estrellas de J1 dependen del otro: en Co-Op son de la banda y en VS la
    # partida se corta si el otro pierde; eso se revisa abajo)
    solo_or_clean = not players or (players == 1 and mode2 == "perfecto")
    if n["notas"] != n["total"] and not (players == 1 and mode2 == "nada"):
        problems.append(f"acertó {n['notas']} de {n['total']}")
    if solo_or_clean and n["combo_max"] != n["total"]: problems.append(f"combo máximo {n['combo_max']} (debe ser {n['total']})")
    if solo_or_clean and n["estrellas"] != 5: problems.append(f"{n['estrellas']} estrellas")
    if n["fallo"]: problems.append("perdió")
elif mode == "nada":
    if not n["fallo"]: problems.append("no perdió sin tocar nada")
elif mode == "sinfallo":
    if n["fallo"]: problems.append("perdió con SIN FALLO")
    if n["notas"]: problems.append("acertó notas sin tocar")
elif mode == "aire":
    if n["notas"] != n["total"]: problems.append(f"acertó {n['notas']} de {n['total']}")
    if n["combo_max"] >= n["total"]: problems.append("los golpes al aire no rompieron el combo")
    if n["fallo"]: problems.append("perdió")
elif mode == "record":
    if n["notas"] != n["total"]: problems.append(f"acertó {n['notas']} de {n['total']}")
    if not n["nuevo_record"]: problems.append("no dijo NUEVO RECORD (con la SRAM vacía)")
    if n["record"] != n["puntaje"] or r.get("iniciales") != "BOT":
        problems.append(f"el récord guardado es {n['record']} {r.get('iniciales')} (debía ser {n['puntaje']} BOT)")
elif mode == "leer_record":
    if not n["record"] or r.get("iniciales") != "BOT":
        problems.append(f"al volver a encender, el récord es {n['record']} {r.get('iniciales')}")
elif mode == "practica":
    if int(r.get("vueltas", 0)) < 2: problems.append(f"la práctica no se repitió (vueltas: {r.get('vueltas')})")
elif mode == "marcas":
    if int(r.get("vueltas", 0)) < 3: problems.append(f"la práctica no se repitió (vueltas: {r.get('vueltas')})")
    if abs(int(r["fin_bucle"]) - int(r["marca"])) > 5:
        problems.append(f"el bucle terminó en {r['fin_bucle']} y la marca de fin estaba en {r['marca']}")
elif mode == "mitad":
    if n["fallo"]: pass  # fallar la mitad puede costar la canción
    if n["notas"] == 0: problems.append("no acertó ninguna")
if players:
    # Dos jugadores: lo del jugador 2, la banda (Co-Op) y quién ganó (VS)
    if mode2 == "perfecto" and n["j2_notas"] != n["j2_total"]: problems.append(f"J2 acertó {n['j2_notas']} de {n['j2_total']}")
    if players == 1:
        if mode == mode2 == "perfecto" and n["ganador"] != (0 if n["puntaje"] == n["j2_puntaje"] else (1 if n["puntaje"] > n["j2_puntaje"] else 2)):
            problems.append(f"ganador {n['ganador']} con {n['puntaje']} contra {n['j2_puntaje']}")
        if mode2 == "nada" and (not n["j2_fallo"] or n["ganador"] != 1): problems.append(f"J2 no perdió o no ganó J1 (ganador {n['ganador']})")
    if players == 2:
        if mode == mode2 == "perfecto" and (n["banda_notas"] != n["banda_total"] or n["banda_estrellas"] != 5):
            problems.append(f"la banda: {n['banda_notas']}/{n['banda_total']}, {n['banda_estrellas']} estrellas")
        if mode2 == "nada" and (not n["j2_fallo"] or n["banda_fallo"]):
            problems.append(f"en Co-Op, con J2 caído la banda debe seguir (J2 cayó {n['j2_fallo']}, banda perdió {n['banda_fallo']})")
    if mode2 == "nada" and players == 1 and n["notas"] == n["total"]:
        problems.append("en VS, si J2 pierde la partida se corta: J1 no debía terminar la canción")
# El audio: que haya sonado algo durante el juego
try:
    w = wave.open(str(d / "audio.wav"))
    rate, ch = w.getframerate(), w.getnchannels()
    data = w.readframes(w.getnframes())
    s = struct.unpack(f"<{len(data) // 2}h", data)
    rms = math.sqrt(sum(x * x for x in s[:: 97]) / max(1, len(s[:: 97])))
    r["audio_rms"] = f"{rms:.0f}"
    if rms < 200: problems.append(f"el audio está casi en silencio (RMS {rms:.0f})")
except Exception as e:
    problems.append(f"no se pudo leer el audio: {e}")
if mode == "leer_record":
    print(("FALLA " if problems else "ok    ") + f"{name}: récord {r.get('record')} {r.get('iniciales')}" + ("".join(f"\n      - {p}" for p in problems)))
    sys.exit(1 if problems else 0)
if mode in ("practica", "marcas"):
    summary = f"vueltas {r.get('vueltas')}, marca {r.get('marca')}, fin del bucle {r.get('fin_bucle')}, audio RMS {r.get('audio_rms')}"
    print(("FALLA " if problems else "ok    ") + f"{name}: {summary}" + ("".join(f"\n      - {p}" for p in problems)))
    sys.exit(1 if problems else 0)
extra = ""
if players:
    extra = f", J2 {n['j2_notas']}/{n['j2_total']} fallo {n['j2_fallo']}"
    extra += f", ganador {n['ganador']}" if players == 1 else f", banda {n['banda_puntaje']} {n['banda_estrellas']}*"
summary = f"notas {n['notas']}/{n['total']}, puntaje {n['puntaje']}, estrellas {n['estrellas']}, combo {n['combo_max']}, fallo {n['fallo']}, audio RMS {r.get('audio_rms')}{extra}"
print(("FALLA " if problems else "ok    ") + f"{name}: {summary}" + ("".join(f"\n      - {p}" for p in problems)))
sys.exit(1 if problems else 0)
PY
}

# Las canciones van en el menú por orden alfabético del título: 0 Amanecer, 1 Brisa, 2 Carrera, 3 Cumbia,
# 4 Luz de Luna, 5 Marcha, 6 Noche, 7 Primer Ensayo, 8 Salto, 9 Tormenta
run_case tormenta-guitarra-experto 9 0 3 perfecto
run_case tormenta-bajo-dificil     9 2 2 perfecto
run_case tormenta-teclado-facil    9 1 0 perfecto
run_case tormenta-nada             9 0 1 nada
run_case tormenta-sinfallo         9 0 0 sinfallo
run_case tormenta-mitad            9 0 3 mitad
run_case tormenta-aire             9 0 2 aire
run_case carrera-guitarra-experto  2 0 3 perfecto
run_case cumbia-bajo-experto       3 2 3 perfecto
run_case luna-teclado-dificil      4 1 2 perfecto
run_case demo-guitarra-medio       7 0 1 perfecto
# Récords: con la SRAM vacía, el juego perfecto es récord y se escriben las iniciales; al volver a
# encender (la misma carpeta de nvram, que es donde MAME guarda la SRAM), el récord sigue ahí
rm -rf "$PWD/build/test-nvram-records"
run_case demo-record               7 0 1 record "" "$PWD/build/test-nvram-records"
run_case demo-record-persiste      7 0 1 leer_record "" "$PWD/build/test-nvram-records"
# Batería: el bot toca los pads y el bombo (carril naranja, C)
run_case tormenta-bateria-experto  9 3 3 perfecto
run_case cumbia-bateria-facil      3 3 0 perfecto
# Dos jugadores: VS con el mismo chart (empate), VS donde J2 pierde (la partida se corta y gana J1),
# Co-Op perfecto (guitarra y bajo) y Co-Op con J2 caído (la banda sigue)
TWO="1 0 3 perfecto" run_case vs-empate        9 0 3 perfecto
TWO="1 0 3 nada"     run_case vs-j2-pierde     9 0 3 perfecto
TWO="2 2 2 perfecto" run_case coop-perfecto    9 0 3 perfecto
TWO="2 3 1 nada"     run_case coop-j2-cae      2 0 2 perfecto
rm -rf "$PWD/build/test-nvram-vs"
TWO="1 1 1 perfecto" run_case vs-record        7 0 1 record "" "$PWD/build/test-nvram-vs"
# Opciones: espejo, velocidad (75% y 125%) y práctica (de 1/2 a 3/4: debe repetirse)
run_case tormenta-espejo           9 0 3 perfecto "espejo=1"
run_case tormenta-lenta            9 0 3 perfecto "velocidad=1"
run_case tormenta-rapida           9 0 3 perfecto "velocidad=3 caida=4"
run_case marcha-practica           5 0 2 practica "practica=3 inicio=2"
run_case marcha-marcas             5 0 2 marcas "practica=4 inicio=1"

if [ $fails -gt 0 ]; then
    echo "$fails caso(s) fallaron"
    exit 1
fi
echo "Todo bien"
