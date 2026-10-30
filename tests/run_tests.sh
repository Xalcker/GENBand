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

# caso: nombre canción instrumento dificultad modo [opciones]
run_case() {
    local name=$1 song=$2 instr=$3 diff=$4 mode=$5 opts=${6:-}
    if [ -n "$only" ] && [[ "$name" != $only ]]; then return; fi
    local dir="$PWD/build/test-$name"
    rm -rf "$dir"
    mkdir -p "$dir"
    GENBAND_SYM="$SYM" GENBAND_OUT="$dir" GENBAND_SONG=$song GENBAND_INSTR=$instr GENBAND_DIFF=$diff \
    GENBAND_MODE=$mode GENBAND_OPTS="$opts" mame genesis -cart "$ROM" -video none -sound none -nothrottle -skip_gameinfo \
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
elif mode == "aire":
    if n["notas"] != n["total"]: problems.append(f"acertó {n['notas']} de {n['total']}")
    if n["combo_max"] >= n["total"]: problems.append("los golpes al aire no rompieron el combo")
    if n["fallo"]: problems.append("perdió")
elif mode == "practica":
    if int(r.get("vueltas", 0)) < 2: problems.append(f"la práctica no se repitió (vueltas: {r.get('vueltas')})")
elif mode == "marcas":
    if int(r.get("vueltas", 0)) < 3: problems.append(f"la práctica no se repitió (vueltas: {r.get('vueltas')})")
    if abs(int(r["fin_bucle"]) - int(r["marca"])) > 5:
        problems.append(f"el bucle terminó en {r['fin_bucle']} y la marca de fin estaba en {r['marca']}")
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
if mode in ("practica", "marcas"):
    summary = f"vueltas {r.get('vueltas')}, marca {r.get('marca')}, fin del bucle {r.get('fin_bucle')}, audio RMS {r.get('audio_rms')}"
    print(("FALLA " if problems else "ok    ") + f"{name}: {summary}" + ("".join(f"\n      - {p}" for p in problems)))
    sys.exit(1 if problems else 0)
summary = f"notas {n['notas']}/{n['total']}, puntaje {n['puntaje']}, estrellas {n['estrellas']}, combo {n['combo_max']}, fallo {n['fallo']}, audio RMS {r.get('audio_rms')}"
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
