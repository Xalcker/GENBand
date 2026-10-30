"""Motor para componer canciones originales de GENBand como archivos VGM (YM2612 + PSG).

Las canciones del juego son originales (GPL-2.0-or-later) y se escriben en Python con la misma
notacion corta que NESBand; este modulo las convierte a `audio/<cancion>.vgm`, que
`genband import-song` importa igual que cualquier otro VGM (y que cualquier reproductor de VGM toca).

Notacion de un compas (16 filas, cada fila es una semicorchea):

    "E5:2 G5:2 r:4 A5:8"      nota:filas, `r` es silencio; las filas de un compas suman 16
    "@Riff"                   cambia de instrumento (vale para lo que sigue en ese canal)

La bateria se escribe con 16 caracteres por compas, uno por fila, en el canal "bateria":

    "K.H.S.H.K.H.S.H."        K bombo, S tarola, H platillo cerrado, O platillo abierto, . silencio

El bombo suena en el canal FM 6 (un seno con barrido de tono hacia abajo) y lo demas en el ruido del
PSG. Canales: fm1..fm6, psg1..psg3 y bateria (que ocupa fm6 y el ruido).

Uso: define los instrumentos y las listas de compases de cada canal, arma una `Cancion` y llama a
`escribir`.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pctools"))

from genband_tools.vgm import PSG_CLOCK, YM_CLOCK, VgmWriter  # noqa: E402

NOMBRES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
FILAS_POR_COMPAS = 16
CANALES_FM = ["fm1", "fm2", "fm3", "fm4", "fm5", "fm6"]
CANALES_PSG = ["psg1", "psg2", "psg3"]


def midi(nombre: str) -> int:
    """'C#4' -> 61 (C4 es la nota 60)."""
    alt = 2 if nombre[1] in "#b" else 1
    letra = nombre[:alt]
    if letra.endswith("b"):
        letra = NOMBRES[(NOMBRES.index(letra[0]) - 1) % 12]
    return 12 * (int(nombre[alt:]) + 1) + NOMBRES.index(letra)


def nombre(n: int) -> str:
    return f"{NOMBRES[n % 12]}{n // 12 - 1}"


def hz(n: float) -> float:
    return 440 * 2 ** ((n - 69) / 12)


@dataclass
class Escala:
    """Una escala (clases de altura) para armar acordes por grados y armonizar a terceras."""

    clases: list[str]

    def __post_init__(self) -> None:
        pcs = {midi(c + "4") % 12 for c in self.clases}
        self.notas = [n for n in range(24, 100) if n % 12 in pcs]

    def grado(self, n: int) -> int:
        return self.notas.index(n)

    def mover(self, n: int, pasos: int) -> int:
        """Sube o baja `pasos` grados dentro de la escala (-2 = una tercera abajo)."""
        return self.notas[self.grado(n) + pasos]

    def triada(self, raiz: str) -> list[int]:
        g = self.grado(midi(raiz))
        return [self.notas[g], self.notas[g + 2], self.notas[g + 4]]


def parsear(compas: str, instrumento: str) -> tuple[list[tuple[int, str | None, int, str]], str]:
    """Convierte un compas a [(fila, nota o None, filas, instrumento)] y el instrumento vigente."""
    fila, notas = 0, []
    for ficha in compas.split():
        if ficha.startswith("@"):
            instrumento = ficha[1:]
            continue
        n, filas = ficha.split(":")
        filas = int(filas)
        notas.append((fila, None if n == "r" else n, filas, instrumento))
        fila += filas
    if fila != FILAS_POR_COMPAS:
        raise ValueError(f"el compas '{compas}' suma {fila} filas y deberian ser {FILAS_POR_COMPAS}")
    return notas, instrumento


def armonizar(compas: str, escala: Escala, pasos: int) -> str:
    """Mueve cada nota `pasos` grados dentro de la escala (por ejemplo -2: una tercera abajo)."""
    fichas = []
    for ficha in compas.split():
        if ficha.startswith("@") or ficha.startswith("r:"):
            fichas.append(ficha)
            continue
        n, filas = ficha.split(":")
        fichas.append(f"{nombre(escala.mover(midi(n), pasos))}:{filas}")
    return " ".join(fichas)


def transportar(compas: str, semitonos: int) -> str:
    fichas = []
    for ficha in compas.split():
        if ficha.startswith("@") or ficha.startswith("r:"):
            fichas.append(ficha)
            continue
        n, filas = ficha.split(":")
        fichas.append(f"{nombre(midi(n) + semitonos)}:{filas}")
    return " ".join(fichas)


def arpegio(raiz: str, escala: Escala, orden: list[int], filas: int = 2, octava: int = 12) -> str:
    """Compas de arpegio: `orden` indexa la triada (0 raiz, 1 tercera, 2 quinta, 3 raiz arriba)."""
    t = escala.triada(raiz)
    t = [n + octava for n in t] + [t[0] + octava + 12]
    fichas = [f"{nombre(t[i])}:{filas}" for i in orden]
    if len(orden) * filas != FILAS_POR_COMPAS:
        raise ValueError("el arpegio no llena el compas")
    return " ".join(fichas)


# --- Instrumentos -----------------------------------------------------------------------------------


@dataclass
class Op:
    """Un operador del YM2612. Los nombres son los de los registros."""

    mul: int = 1  # multiplicador de frecuencia (0 = x0.5)
    dt: int = 0  # desafinacion (0-7; 4-7 hacia abajo)
    tl: int = 0  # nivel total: atenuacion, 0 = lo mas fuerte, 127 = callado
    ar: int = 31  # ataque (31 = inmediato)
    d1r: int = 0  # primera caida
    d2r: int = 0  # segunda caida (mientras se sostiene)
    d1l: int = 0  # nivel donde termina la primera caida (0-15)
    rr: int = 15  # caida al soltar (0-15)
    rs: int = 0  # escala de ritmo con la altura (0-3)


# Algoritmos: que operadores suenan (los "portadores"); los demas modulan
PORTADORES = {0: (3,), 1: (3,), 2: (3,), 3: (3,), 4: (1, 3), 5: (1, 2, 3), 6: (1, 2, 3), 7: (0, 1, 2, 3)}


@dataclass
class FM:
    """Un sonido FM: algoritmo, retroalimentacion del operador 1 y los 4 operadores (op1, op2, op3, op4)."""

    alg: int
    fb: int
    ops: tuple[Op, Op, Op, Op]
    barrido: list[float] | None = None  # semitonos que se suman a la nota en cada cuadro (el bombo)


@dataclass
class PSG:
    """Un sonido del PSG: volumen por cuadro (0-15, 15 = lo mas fuerte); el ultimo se mantiene."""

    volumen: list[int]
    ruido: int | None = None  # solo en el ruido: el byte de control ($E0-$E7)


# Golpes de bateria: K va al FM 6; los demas al ruido
GOLPES = {"K": "Bombo", "S": "Tarola", "H": "Platillo", "O": "Abierto"}


@dataclass
class Cancion:
    titulo: str
    fila_cuadros: int  # cuadros por fila: 6 = 150 BPM, 5 = 180, 8 = 112
    instrumentos: dict[str, FM | PSG]
    canales: dict[str, list[str]] = field(default_factory=dict)  # canal -> compases
    inicial: dict[str, str] = field(default_factory=dict)  # canal -> instrumento inicial
    mezcla: dict[str, int] = field(default_factory=dict)  # canal FM -> atenuacion extra de sus portadores
    autor: str = "GENBand"

    @property
    def compases(self) -> int:
        return len(next(iter(self.canales.values())))


# Registros de cada operador en el orden de los registros del YM: op1, op3, op2, op4
_ORDEN_REG = (0, 2, 1, 3)  # _ORDEN_REG[k] = indice en `ops` del operador del registro base + 4k


def _fnum(n: float) -> tuple[int, int]:
    """(bloque, F-number) de una altura MIDI (con decimales)."""
    f = hz(n)
    for bloque in range(8):
        fnum = round(f * 144 * (1 << (21 - bloque)) / YM_CLOCK)
        if fnum < 2048:
            return bloque, fnum
    return 7, 2047


def _periodo(n: float) -> int:
    return max(1, min(1023, round(PSG_CLOCK / (32 * hz(n)))))


class _Linea:
    """Las escrituras de la cancion, agrupadas por cuadro."""

    def __init__(self) -> None:
        self.cuadros: dict[int, list[tuple[int, str, int, int]]] = {}  # cuadro -> (orden, chip, reg, valor)
        self.orden = 0

    def ym(self, cuadro: int, ch: int, reg: int, valor: int) -> None:
        self._add(cuadro, f"ym{ch // 3}", reg, valor)

    def ym_global(self, cuadro: int, reg: int, valor: int) -> None:
        self._add(cuadro, "ym0", reg, valor)

    def psg(self, cuadro: int, valor: int) -> None:
        self._add(cuadro, "psg", 0, valor)

    def _add(self, cuadro: int, chip: str, reg: int, valor: int) -> None:
        self.orden += 1
        self.cuadros.setdefault(cuadro, []).append((self.orden, chip, reg, valor))


def _cargar_fm(linea: _Linea, cuadro: int, ch: int, sonido: FM, extra: int) -> None:
    c = ch % 3
    for k, i in enumerate(_ORDEN_REG):
        op = sonido.ops[i]
        tl = min(127, op.tl + (extra if i in PORTADORES[sonido.alg] else 0))
        base = 4 * k + c
        linea.ym(cuadro, ch, 0x30 + base, (op.dt << 4) | op.mul)
        linea.ym(cuadro, ch, 0x40 + base, tl)
        linea.ym(cuadro, ch, 0x50 + base, (op.rs << 6) | op.ar)
        linea.ym(cuadro, ch, 0x60 + base, op.d1r)
        linea.ym(cuadro, ch, 0x70 + base, op.d2r)
        linea.ym(cuadro, ch, 0x80 + base, (op.d1l << 4) | op.rr)
        linea.ym(cuadro, ch, 0x90 + base, 0)
    linea.ym(cuadro, ch, 0xB0 + c, (sonido.fb << 3) | sonido.alg)
    linea.ym(cuadro, ch, 0xB4 + c, 0xC0)  # suena por los dos lados


def _altura_fm(linea: _Linea, cuadro: int, ch: int, n: float) -> None:
    bloque, fnum = _fnum(n)
    c = ch % 3
    linea.ym(cuadro, ch, 0xA4 + c, (bloque << 3) | (fnum >> 8))
    linea.ym(cuadro, ch, 0xA0 + c, fnum & 0xFF)


def _codigo(ch: int) -> int:
    return ch if ch < 3 else ch + 1  # el registro $28 numera los canales 0, 1, 2, 4, 5, 6


def _notas_canal(c: Cancion, clave: str) -> list[tuple[int, int, str | None, str]]:
    """[(cuadro, cuadros, nota o None, instrumento)] de un canal."""
    f = c.fila_cuadros
    out = []
    instrumento = c.inicial.get(clave, next(iter(c.instrumentos)))
    for i, compas in enumerate(c.canales[clave]):
        notas, instrumento = parsear(compas, instrumento)
        for fila, n, filas, ins in notas:
            out.append(((i * FILAS_POR_COMPAS + fila) * f, filas * f, n, ins))
    return out


def _bateria(c: Cancion) -> tuple[list[tuple[int, str]], list[tuple[int, str]]]:
    """Golpes del canal de bateria: (bombos, golpes de ruido) como [(cuadro, instrumento)]."""
    bombos, ruido = [], []
    for i, compas in enumerate(c.canales["bateria"]):
        if len(compas) != FILAS_POR_COMPAS:
            raise ValueError(f"el compas de bateria '{compas}' no tiene {FILAS_POR_COMPAS} caracteres")
        for fila, golpe in enumerate(compas):
            if golpe == ".":
                continue
            cuadro = (i * FILAS_POR_COMPAS + fila) * c.fila_cuadros
            (bombos if golpe == "K" else ruido).append((cuadro, GOLPES[golpe]))
    return bombos, ruido


def tocar_fm(linea: _Linea, c: Cancion, ch: int, notas: list[tuple[int, int, str | None, str]]) -> None:
    cargado = None
    extra = c.mezcla.get(CANALES_FM[ch], 0)
    for cuadro, cuadros, n, ins in notas:
        if n is None:
            continue
        sonido = c.instrumentos[ins]
        if not isinstance(sonido, FM):
            raise ValueError(f"el instrumento {ins} no es FM y esta en {CANALES_FM[ch]}")
        if cargado != ins:
            _cargar_fm(linea, cuadro, ch, sonido, extra)
            cargado = ins
        altura = midi(n)
        _altura_fm(linea, cuadro, ch, altura + (sonido.barrido[0] if sonido.barrido else 0))
        linea.ym_global(cuadro, 0x28, 0xF0 | _codigo(ch))
        for k, semitonos in enumerate((sonido.barrido or [])[1:], start=1):
            if k >= cuadros - 1:
                break
            _altura_fm(linea, cuadro + k, ch, altura + semitonos)
        # Se suelta un cuadro antes de la siguiente nota: el YM necesita la tecla suelta para volver a atacar
        linea.ym_global(cuadro + cuadros - 1, 0x28, _codigo(ch))


def _tocar_psg(linea: _Linea, c: Cancion, ch: int, notas: list[tuple[int, int, str | None, str]]) -> None:
    for cuadro, cuadros, n, ins in notas:
        if n is None:
            continue
        sonido = c.instrumentos[ins]
        if not isinstance(sonido, PSG):
            raise ValueError(f"el instrumento {ins} no es PSG y esta en {CANALES_PSG[ch]}")
        p = _periodo(midi(n))
        linea.psg(cuadro, 0x80 | (ch << 5) | (p & 0x0F))
        linea.psg(cuadro, (p >> 4) & 0x3F)
        _envolvente(linea, cuadro, cuadros - 1, ch, sonido.volumen)
        linea.psg(cuadro + cuadros - 1, 0x9F | (ch << 5))


def _envolvente(linea: _Linea, cuadro: int, cuadros: int, ch: int, volumen: list[int]) -> None:
    anterior = None
    for k in range(max(1, cuadros)):
        v = volumen[min(k, len(volumen) - 1)]
        if v != anterior:
            linea.psg(cuadro + k, 0x90 | (ch << 5) | (15 - v))
            anterior = v
        if k >= len(volumen):
            break


def nueva_linea() -> _Linea:
    """Una linea de tiempo con el chip en silencio y listo (sin LFO, canal 3 normal, sin DAC)."""
    linea = _Linea()
    linea.ym_global(0, 0x22, 0)
    linea.ym_global(0, 0x27, 0)
    linea.ym_global(0, 0x2B, 0)  # sin DAC: el canal 6 es FM
    for ch in range(6):
        linea.ym_global(0, 0x28, _codigo(ch))
    for ch in range(4):
        linea.psg(0, 0x9F | (ch << 5))
    return linea


def tocar_bateria(linea: _Linea, c: Cancion, bombos: list[tuple[int, str]], ruido: list[tuple[int, str]]) -> None:
    """Bombos en el FM 6 y golpes en el ruido del PSG; cada golpe de ruido suena hasta el siguiente."""
    f = c.fila_cuadros
    tocar_fm(linea, c, 5, [(cuadro, 2 * f, "C2", ins) for cuadro, ins in bombos])
    control = None
    for i, (cuadro, ins) in enumerate(ruido):
        sonido = c.instrumentos[ins]
        assert isinstance(sonido, PSG) and sonido.ruido is not None
        siguiente = ruido[i + 1][0] if i + 1 < len(ruido) else cuadro + 4 * f
        if sonido.ruido != control:
            linea.psg(cuadro, sonido.ruido)
            control = sonido.ruido
        _envolvente(linea, cuadro, siguiente - cuadro, 3, sonido.volumen)


def escribir_linea(linea: _Linea, c: Cancion, total: int, ruta: Path, bucle: bool = False) -> None:
    """Escribe las escrituras de la linea como VGM; `total` es lo que dura la cancion (en cuadros)."""
    vgm = VgmWriter()
    if bucle:
        vgm.mark_loop()
    actual = 0
    for cuadro in sorted(linea.cuadros):
        vgm.wait_frames(cuadro - actual)
        actual = cuadro
        for _, chip, reg, valor in sorted(linea.cuadros[cuadro]):
            if chip == "psg":
                vgm.psg(valor)
            else:
                vgm.ym(int(chip[2]), reg, valor)
    # Sin bucle, medio segundo mas para que se apague lo ultimo
    vgm.wait_frames(total + (0 if bucle else 30) - actual)
    ruta.write_bytes(vgm.to_bytes(c.titulo, "GENBand", c.autor))
    print(f"{ruta}: {total / 60:.0f} s")


def escribir(c: Cancion, ruta: Path, bucle: bool = False) -> None:
    """Escribe la cancion como VGM. Con `bucle`, se repite entera (la musica del titulo)."""
    largos = {k: len(v) for k, v in c.canales.items()}
    if len(set(largos.values())) != 1:
        raise ValueError(f"los canales no miden lo mismo (en compases): {largos}")
    linea = nueva_linea()
    for ch, clave in enumerate(CANALES_FM):
        if clave in c.canales:
            tocar_fm(linea, c, ch, _notas_canal(c, clave))
    for ch, clave in enumerate(CANALES_PSG):
        if clave in c.canales:
            _tocar_psg(linea, c, ch, _notas_canal(c, clave))
    if "bateria" in c.canales:
        if "fm6" in c.canales:
            raise ValueError("la bateria usa el canal fm6 para el bombo")
        tocar_bateria(linea, c, *_bateria(c))
    escribir_linea(linea, c, c.compases * FILAS_POR_COMPAS * c.fila_cuadros, ruta, bucle)
