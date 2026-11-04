# GENBand

- **Paridad entre versiones:** al terminar una mejora, actualiza `../NESBand/docs/paridad.md` (la fila y la columna GEN) y anota en
  "Pendientes por versión" lo que falta en NES y GB.
- **Pruebas:** `uv run genband test [--no-build] [--rapida] [-j N] [--lista] [patron]` (MAME sin ventana; igual en macOS y Windows). Es el
  corredor de `bandcore.testrun`, el mismo comando en los cuatro juegos. Las fallas ya conocidas van en `tests/known_failures.txt`.
