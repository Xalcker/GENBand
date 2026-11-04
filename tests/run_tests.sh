#!/usr/bin/env bash
# Compila y corre las pruebas de GENBand en MAME (el bot de tests/autoplay.lua juega cada caso).
# Es un envoltorio de `uv run genband test`, que es igual en macOS y en Windows (ver bandcore.testrun):
#
#   tests/run_tests.sh                 compila y corre todos los casos
#   tests/run_tests.sh --no-build      con la ROM que ya está en build/
#   tests/run_tests.sh --rapida        un subconjunto representativo
#   tests/run_tests.sh -j 4 'vs-*'     4 casos a la vez, solo los que coinciden (comodines y comas)
#   tests/run_tests.sh --lista         solo muestra los casos
#
# Cada caso deja en build/test-<nombre>/ el resultado, el registro del bot, las capturas y el audio.
# Las fallas que ya se conocen van en tests/known_failures.txt: no cambian el código de salida.
exec uv run --project "$(cd "$(dirname "$0")/.." && pwd)" genband test "$@"
