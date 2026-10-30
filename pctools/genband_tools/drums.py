"""Batería: de los golpes de los canales de batería de un VGM a un chart de 4 pads y bombo, al estilo de Rock Band.

Es el mismo generador de NESBand. Un VGM no dice qué es cada golpe, así que primero se agrupan: cada grupo es
un canal (el ruido del PSG, o un canal FM que toca batería, como el bombo de las canciones de GENBand en el
FM 6) y un tono (en el ruido, su tipo: el byte de control). El usuario (o una sugerencia automática) le
asigna a cada grupo un papel; la asignación vive en src/songs/<canción>/drums.json, aparte del chart, para
que `genband reimport` no la pierda. Con ella se genera un chart por dificultad (build_drum_chart).

Papeles y carriles (cada carril es el color de siempre, que fija el botón del control):
    tarola = rojo (↓)   tom 1 / hi-hat = amarillo (→)   tom 2 / ride = azul (B)   tom 3 / crash = verde (←)
    bombo = naranja (C), la barra
En el nivel experto (el "Pro" de Rock Band) un golpe de platillo se marca con el bit $40 (la batería no usa
colas); va en el mismo carril y botón que un tom, solo se ve distinto. En las demás dificultades los
platillos se tocan como toms.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .chart import DIFFICULTIES, BeatGrid, ChartNote, star_notes
from .vgm import CHANNEL_NAMES, DacSample, Note

NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def midi_to_name(pitch: int) -> str:
    return f"{NAMES[pitch % 12]}{pitch // 12 - 1}"

DRUMS_FILE = "drums.json"
DRUMS_VERSION = 1
# Los golpes del ruido del PSG se identifican por su tipo (el byte de control de 0 a 7, que extract_notes
# deja como "altura"): 4-7 es ruido blanco, del más agudo (4) al más grave (6); 7 sigue al tono 3
ROLE_LANE = {"tom3": 0, "snare": 1, "tom1": 2, "tom2": 3, "kick": 4}
ROLE_LABELS = {"kick": "Bombo (barra naranja)", "snare": "Tarola (rojo)", "tom1": "Tom 1 / Hi-hat (amarillo)",
               "tom2": "Tom 2 / Ride (azul)", "tom3": "Tom 3 / Crash (verde)"}
ROLES = tuple(ROLE_LABELS)
ROLE_WEIGHT = {"kick": 3, "snare": 3, "tom1": 2, "tom2": 2, "tom3": 2}
# Con menos dificultad, los toms se juntan en los que quedan: fácil usa bombo, tarola y tom 1; medio agrega el 2
FOLD = {"facil": {"tom2": "tom1", "tom3": "tom1"}, "medio": {"tom3": "tom2"}, "dificil": {}, "experto": {}}
# Botones a la vez: como máximo 3 (el pie y dos manos); fácil y medio quedan en 1 y 2
MAX_BUTTONS = {"facil": 1, "medio": 2, "dificil": 3, "experto": 3}
MAX_HANDS = 2   # golpes de mano a la vez (sin contar el bombo): solo hay dos manos
PRO_CYMBALS = {"experto"}   # dificultades donde los platillos se distinguen de los toms
CYMBAL_WEIGHT_PENALTY = 0.5   # los platillos (hi-hat) son lo primero que se quita al reducir
MERGE_FRAMES = 1   # golpes a esta distancia son el mismo momento
MIN_GROUP_HITS = 3   # sugerencia: grupos con menos golpes no se asignan


@dataclass(frozen=True)
class Group:
    key: str  # "ruido:5" (el ruido, por tipo), "dac:2" (el DAC, por sample) o "fm6:G3" (un canal FM o PSG, por tono)
    channel: str
    pitch: int
    instrument: str
    count: int
    avg_duration: float
    first_frame: int

    @property
    def tone(self) -> str:
        if self.channel == "dac":
            return f"sample {self.pitch}"
        return f"tipo {self.pitch}" if self.channel == "ruido" else midi_to_name(self.pitch)


UNPITCHED = ("ruido", "dac")    # canales cuyos golpes se distinguen por tipo o sample, no por altura


def group_key(channel: str, pitch: int) -> str:
    return f"{channel}:{pitch}" if channel in UNPITCHED else f"{channel}:{midi_to_name(pitch)}"


def channel_strikes(channel: str, ns: list[Note]) -> list[Note]:
    """Los golpes de un canal (en el DAC cada nota ya es un golpe: uno que corta al anterior no es legato)."""
    return sorted(ns, key=lambda n: n.frame) if channel == "dac" else strikes(ns)


def strikes(ns: list[Note]) -> list[Note]:
    """Los golpes de un canal: una nota que empieza justo donde termina la anterior es la misma, con otro
    tono (el barrido del bombo FM baja de tono cuadro por cuadro y extract_notes lo ve como notas ligadas)."""
    out: list[Note] = []
    end = None
    for n in sorted(ns, key=lambda n: n.frame):
        if end is not None and n.frame == end and out:
            end = n.frame + n.duration
            continue
        out.append(n)
        end = n.frame + n.duration
    return out


def drum_groups(notes: dict[int, list[Note]], channels: list[int]) -> list[Group]:
    """Los grupos de golpes de los canales de batería, ordenados por canal y tono."""
    found: dict[str, tuple[str, list[Note]]] = {}
    for ch in channels:
        name = CHANNEL_NAMES[ch]
        for note in channel_strikes(name, notes.get(ch, [])):
            found.setdefault(group_key(name, note.pitch), (name, []))[1].append(note)
    groups = []
    for key, (channel, ns) in found.items():
        groups.append(Group(key, channel, ns[0].pitch, ns[0].instrument or "", len(ns),
                            sum(n.duration for n in ns) / len(ns), min(n.frame for n in ns)))
    return sorted(groups, key=lambda g: (CHANNEL_NAMES.index(g.channel), g.pitch))


NAME_HINTS = (
    (("bombo", "kick", "bass drum", "bd"), "kick", False),
    (("tarola", "snare", "caja", "sd"), "snare", False),
    (("hat", "hh", "cerrado", "abierto", "closed", "open"), "tom1", True),   # hi-hat: amarillo
    (("ride",), "tom2", True),                                              # ride: azul
    (("platillo", "cymbal", "crash"), "tom3", True),                        # crash: verde
    (("tom",), "tom1", False),
)


DAC_MIN_SECONDS = 0.03   # samples más cortos son restos de un golpe cortado: no se sugieren
DAC_COMMON = 6           # bombo y tarola: entre los que suenan al menos 1/6 de lo que suena el que más


def sample_seconds(sample: DacSample) -> float:
    return len(sample.data) / (32000, 22050, 16000, 13400, 11025, 8000)[sample.rate]


def zero_crossings(sample: DacSample) -> float:
    """Qué tan seguido cruza el cero un sample (por byte): bajo en un bombo, alto en una tarola o un platillo."""
    data = [b - 256 if b >= 128 else b for b in sample.data]
    rate = (32000, 22050, 16000, 13400, 11025, 8000)[sample.rate]
    crossings = sum(1 for a, b in zip(data, data[1:]) if (a < 0) != (b < 0))
    return crossings * rate / max(1, len(data))     # cruces por segundo: no depende de la frecuencia


def suggest_assignment(groups: list[Group], dac_samples: list[DacSample] | None = None) -> dict[str, dict]:
    """Una primera asignación, por el canal y el tono.

    En el DAC, por cómo suena cada sample (cruces por cero): el más grave es el bombo, el más ruidoso la
    tarola y los demás toms (del más grave al más agudo: tom 3, 2, 1). En los canales FM o PSG, el tono más grave es el bombo y los siguientes son toms. En el ruido, el tipo:
    el blanco más agudo (4) es el hi-hat (platillo, amarillo), el siguiente (5) la tarola y los más graves
    (6, 7) toms; el periódico (0-3) son toms. Casi nunca acierta del todo con la música de otros juegos: es
    el punto de partida para corregir drums.json."""
    assignment: dict[str, dict] = {g.key: {"lane": None, "cymbal": False} for g in groups}
    used: set[str] = set()

    def give(group: Group, preferred: list[str], cymbal: bool = False) -> None:
        role = next((r for r in preferred if r not in used), preferred[-1])
        assignment[group.key] = {"lane": role, "cymbal": cymbal}
        used.add(role)

    if dac_samples:
        # Sin los restos (unos milisegundos de un golpe cortado), del más grave al más agudo
        dac = sorted((g for g in groups if g.channel == "dac" and g.count >= MIN_GROUP_HITS and g.pitch < len(dac_samples)
                      and sample_seconds(dac_samples[g.pitch]) >= DAC_MIN_SECONDS),
                     key=lambda g: zero_crossings(dac_samples[g.pitch]))
        # El bombo y la tarola salen de los que más suenan (un timbal que suena 3 veces no es el bombo)
        common = [g for g in dac if g.count * DAC_COMMON >= max((g.count for g in dac), default=0)]
        if common:
            give(common[0], ["kick"])
        if len(common) > 1:
            give(common[-1], ["snare"])
        for group in dac:
            if assignment[group.key]["lane"] is None:
                give(group, ["tom3", "tom2", "tom1"])
    tonal = sorted((g for g in groups if g.channel not in UNPITCHED and g.count >= MIN_GROUP_HITS), key=lambda g: g.pitch)
    for index, group in enumerate(tonal):
        give(group, ["kick", "tom3", "tom2", "tom1"] if index == 0 else ["tom3", "tom2", "tom1"])
    for group in sorted((g for g in groups if g.channel == "ruido" and g.count >= MIN_GROUP_HITS), key=lambda g: g.pitch):
        if group.pitch == 4:
            give(group, ["tom1", "tom2", "tom3"], cymbal=True)
        elif group.pitch == 5:
            give(group, ["snare", "tom2", "tom3"])
        else:
            give(group, ["tom2", "tom3", "snare", "tom1"])
    if "snare" not in used:      # sin tarola en el ruido: el siguiente tono FM, o el tipo 6
        candidates = [g for g in groups if assignment[g.key]["lane"] in ("tom3", "tom2") and not assignment[g.key]["cymbal"]]
        if candidates:
            assignment[candidates[0].key] = {"lane": "snare", "cymbal": False}
    return assignment


# --- drums.json -----------------------------------------------------------------------------------


def load_drums(song_dir: Path) -> dict[str, dict] | None:
    """La asignación guardada (grupo -> {"lane", "cymbal"}), o None si la canción aún no tiene."""
    path = song_dir / DRUMS_FILE
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("version") != DRUMS_VERSION:
        raise ValueError(f"{path}: versión de drums.json no soportada ({data.get('version')})")
    return data.get("groups", {})


def check_assignment(assignment: dict[str, dict]) -> None:
    for key, item in assignment.items():
        if item.get("lane") not in (*ROLES, None):
            raise ValueError(f"{key}: papel desconocido {item.get('lane')!r}")


def dump_drums(assignment: dict[str, dict]) -> str:
    lines = [f'{{\n  "version": {DRUMS_VERSION},\n  "groups": {{']
    lines.append(",\n".join(
        f"    {json.dumps(key, ensure_ascii=False)}: {json.dumps({'lane': item.get('lane'), 'cymbal': bool(item.get('cymbal'))})}"
        for key, item in sorted(assignment.items())))
    lines.append("  }\n}\n")
    return "\n".join(lines)


def save_drums(song_dir: Path, assignment: dict[str, dict]) -> None:
    check_assignment(assignment)
    (song_dir / DRUMS_FILE).write_text(dump_drums(assignment), encoding="utf-8", newline="\n")


# --- Chart --------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Hit:
    frame: int
    role: str
    cymbal: bool


def drum_hits(notes: dict[int, list[Note]], channels: list[int], assignment: dict[str, dict]) -> list[Hit]:
    hits = []
    for ch in channels:
        for note in channel_strikes(CHANNEL_NAMES[ch], notes.get(ch, [])):
            item = assignment.get(group_key(CHANNEL_NAMES[ch], note.pitch))
            if item and item.get("lane"):
                hits.append(Hit(note.frame, item["lane"], bool(item.get("cymbal")) and item["lane"] not in ("kick", "snare")))
    return sorted(hits, key=lambda h: h.frame)


def build_drum_chart(hits: list[Hit], difficulty_name: str, grid: BeatGrid, lead_in: int) -> list[ChartNote]:
    """El chart de batería de una dificultad.

    1. Los toms se juntan según la dificultad (FOLD) y los golpes casi simultáneos son un "momento".
    2. De cada momento quedan hasta MAX_BUTTONS botones (primero bombo y tarola), con a lo más MAX_HANDS
       golpes de mano y sin verde + amarillo.
    3. Se quitan momentos hasta que ninguno quede a menos de min_gap cuadros de otro, conservando los
       de los tiempos fuertes y los de bombo y tarola.
    4. Los platillos solo se marcan en las dificultades Pro (PRO_CYMBALS)."""
    difficulty = next(d for d in DIFFICULTIES if d.name == difficulty_name)
    fold, max_buttons = FOLD[difficulty_name], MAX_BUTTONS[difficulty_name]
    moments: list[dict] = []   # {"frame", "lanes": {lane: (peso, platillo)}}
    for hit in hits:
        role = fold.get(hit.role, hit.role)
        weight = ROLE_WEIGHT[role] - (CYMBAL_WEIGHT_PENALTY if hit.cymbal else 0)
        if moments and hit.frame - moments[-1]["frame"] <= MERGE_FRAMES:
            lanes = moments[-1]["lanes"]
            old = lanes.get(ROLE_LANE[role])
            lanes[ROLE_LANE[role]] = (max(weight, old[0]) if old else weight, hit.cymbal and (old[1] if old else True))
        else:
            moments.append({"frame": hit.frame, "lanes": {ROLE_LANE[role]: (weight, hit.cymbal)}})
    pro = difficulty_name in PRO_CYMBALS
    for moment in moments:
        lanes = moment["lanes"]
        if not pro and any(not cymbal for _, cymbal in lanes.values()):
            # Sin Pro un platillo es un tom más: si el momento ya tiene un golpe de bombo o tarola, el
            # platillo se omite (si no, casi todo sería un acorde con el hi-hat)
            lanes = {lane: value for lane, value in lanes.items() if not value[1]}
        ranked = sorted(lanes.items(), key=lambda item: -item[1][0])
        kept: dict[int, tuple] = {}
        for lane, value in ranked:
            is_hand = lane != ROLE_LANE["kick"]
            hands = sum(1 for other in kept if other != ROLE_LANE["kick"])
            if (len(kept) < max_buttons and (not is_hand or hands < MAX_HANDS)
                    and not any({lane, other} == {0, 2} for other in kept)):
                kept[lane] = value
        moment["lanes"] = kept
        moment["weight"] = max(w for w, _ in kept.values())
    by_priority = sorted(moments, key=lambda m: (-grid.strength(m["frame"]), -m["weight"], m["frame"]))
    chosen: list[dict] = []
    for moment in by_priority:
        if all(abs(moment["frame"] - other["frame"]) >= difficulty.min_gap for other in chosen):
            chosen.append(moment)
    chosen.sort(key=lambda m: m["frame"])
    masks = [sum(1 << lane for lane in m["lanes"]) for m in chosen]
    stars = star_notes(len(chosen), [mask & (mask - 1) != 0 for mask in masks])
    return [
        ChartNote(lead_in + m["frame"], mask, None, star,
                  pro and any(cymbal for lane, (_, cymbal) in m["lanes"].items() if lane not in (ROLE_LANE["kick"], ROLE_LANE["snare"])))
        for m, mask, star in zip(chosen, masks, stars)
    ]
