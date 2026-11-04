# Compila y corre las pruebas de GENBand en MAME. Envoltorio de `uv run genband test` (igual en macOS y Windows).
# Uso:  .\tests\run_tests.ps1 [--no-build] [--rapida] [-j 4] [--lista] [patron ...]
# (los argumentos pasan tal cual a `genband test`; ver tests/run_tests.sh)
$root = Split-Path $PSScriptRoot -Parent
& uv run --project $root genband test @args
exit $LASTEXITCODE
