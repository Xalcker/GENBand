"""Lógica del editor de charts, sin interfaz: aplicar ediciones manuales y validar.

Es la de bandcore (`bandcore.chartedit`), igual en los cuatro juegos; este módulo solo la vuelve a exportar para que el
resto de GENBand la siga usando como `chartedit.<nombre>`. Ahí está el formato de edits.json.
"""

from bandcore.chartedit import (  # noqa: F401
    EDITS_FILE,
    EDITS_VERSION,
    KICK_MASK,
    LANE_MASK,
    MAX_DRUM_BUTTONS,
    MAX_DRUM_HANDS,
    TOM_MASK,
    apply_edits,
    chart_from_json,
    chart_problems,
    diff_charts,
    dump_edits,
    lanes_of,
    load_edits,
    save_edits,
    validate_chart,
)
