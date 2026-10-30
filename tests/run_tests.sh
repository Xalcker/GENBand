#!/usr/bin/env bash
# Pruebas de GENBand en MAME: el bot (tests/autoplay.lua) juega cada caso y se revisa su resultado.
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

# caso: nombre canción instrumento dificultad modo
run_case() {
    local name=$1 song=$2 instr=$3 diff=$4 mode=$5
    if [ -n "$only" ] && [[ "$name" != $only ]]; then return; fi
    local dir="$PWD/build/test-$name"
    rm -rf "$dir"
    mkdir -p "$dir"
    GENBAND_SYM="$SYM" GENBAND_OUT="$dir" GENBAND_SONG=$song GENBAND_INSTR=$instr GENBAND_DIFF=$diff \
    GENBAND_MODE=$mode mame genesis -cart "$ROM" -video none -sound none -nothrottle -skip_gameinfo \
        -wavwrite "$dir/audio.wav" -snapshot_directory "$dir" -cfg_directory "$dir/cfg" \
        -nvram_directory "$dir/nvram" -autoboot_script tests/autoplay.lua >"$dir/mame.log" 2>&1
    if [ ! -f "$dir/resultado.txt" ]; then
        echo "FALLA $name: el bot no llegó a los resultados (ver $dir/bot.log y mame.log)"
        fails=$((fails + 1))
        return
    fi
    python3 - "$dir" "$mode" "$name" <<'PY' || fails=$((fails + 1))
import math, struct, sys, wave
from pathlib import Path
d, mode, name = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
r = dict(line.strip().split("=", 1) for line in open(d / "resultado.txt") if "=" in line)
n = {k: int(v) for k, v in r.items() if v.lstrip("-").isdigit()}
problems = []
if mode == "perfecto":
    if n["notas"] != n["total"]: problems.append(f"acertó {n['notas']} de {n['total']}")
    if n["combo_max"] != n["total"]: problems.append(f"combo máximo {n['combo_max']} (debe ser {n['total']})")
    if n["estrellas"] != 5: problems.append(f"{n['estrellas']} estrellas")
    if n["fallo"]: problems.append("perdió")
elif mode == "nada":
    if not n["fallo"]: problems.append("no perdió sin tocar nada")
elif mode == "sinfallo":
    if n["fallo"]: problems.append("perdió con SIN FALLO")
    if n["notas"]: problems.append("acertó notas sin tocar")
elif mode == "mitad":
    if n["fallo"]: pass  # fallar la mitad puede costar la canción
    if n["notas"] == 0: problems.append("no acertó ninguna")
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
summary = f"notas {n['notas']}/{n['total']}, puntaje {n['puntaje']}, estrellas {n['estrellas']}, combo {n['combo_max']}, fallo {n['fallo']}, audio RMS {r.get('audio_rms')}"
print(("FALLA " if problems else "ok    ") + f"{name}: {summary}" + ("".join(f"\n      - {p}" for p in problems)))
sys.exit(1 if problems else 0)
PY
}

run_case tormenta-guitarra-experto 0 0 3 perfecto
run_case tormenta-bajo-dificil     0 2 2 perfecto
run_case tormenta-teclado-facil    0 1 0 perfecto
run_case tormenta-nada             0 0 1 nada
run_case tormenta-sinfallo         0 0 0 sinfallo
run_case tormenta-mitad            0 0 3 mitad

if [ $fails -gt 0 ]; then
    echo "$fails caso(s) fallaron"
    exit 1
fi
echo "Todo bien"
