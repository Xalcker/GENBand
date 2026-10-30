"""El escenario de la partida: se dibuja aquí, en Python, y sale como tiles para la ROM (src/stage_gfx.c).

`genband build-stage` dibuja la escena completa (320x192 píxeles, lo que queda arriba de la franja del
marcador) para 1 jugador y para 2, la corta en tiles de 8x8 y quita los repetidos (también los que son el
espejo de otro: el VDP los voltea al dibujarlos). El juego (src/stage.c) pone cada tile solo donde el
trapecio de la autopista deja escenario, así que la escena puede pasar por debajo de la autopista sin
cuidado: esa parte nunca se ve. `--png` escribe además una vista previa de cada escena.

Todo usa la paleta 0 (la del escenario y la autopista):

   0 negro            1 la autopista (cambia)   2 orillas y líneas de carril   3 la pared del fondo
   4..10, 14: los del escenario (ver COLORS)    11 la franja del marcador      12 el haz de luz (cambia)
  13 el foco (cambia)                            15 blanco (texto)

Los colores 12 y 13 los cambia stage.c en cada cuadro (laten con la música y cambian con el poder
estelar): todo lo que se ilumina (los haces, los focos, el borde de las cabezas del público) los usa.

El público es aparte: una franja de CROWD_W x CROWD_H tiles que se repite, en 3 dibujos (quieto, brazos
arriba, saltando); stage.c copia a la VRAM el que toca, así que se anima sin reescribir el mapa.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

W, H = 320, 192             # la escena: 40 x 24 tiles
COLS, ROWS = W // 8, H // 8

# PAL0. Los que cambian en el juego (1, 12, 13) tienen aquí su valor de partida (el de la vista previa).
COLORS = [
    0x000000, 0x080838, 0x384868, 0x180828,     # negro, autopista, líneas, pared
    0x24143C, 0x5A5A78, 0xA0A0BC, 0x0A0612,     # 4 pared en sombra, 5 metal, 6 metal con brillo, 7 silueta
    0x3A2C58, 0x1C1C24, 0x34343E, 0x101418,     # 8 silueta iluminada, 9 rejilla, 10 gabinete, 11 franja
    0x403858, 0xA0A0A0, 0xE0A040, 0xFFFFFF,     # 12 haz, 13 foco, 14 ámbar (lucecitas), 15 blanco
]
WALL, SHADE, METAL, SHINE, DARK, LIT, GRILLE, CABINET = 3, 4, 5, 6, 7, 8, 9, 10
BLACK, BEAM, LAMP, AMBER = 0, 12, 13, 14

CROWD_W, CROWD_H = 4, 8     # la franja del público, en tiles
CROWD_FRAMES = 3


class Canvas:
    def __init__(self, color: int = WALL) -> None:
        self.px = [[color] * W for _ in range(H)]

    def set(self, x: int, y: int, c: int) -> None:
        if 0 <= x < W and 0 <= y < H:
            self.px[y][x] = c

    def rect(self, x0: int, y0: int, x1: int, y1: int, c: int) -> None:
        for y in range(max(0, y0), min(H, y1)):
            for x in range(max(0, x0), min(W, x1)):
                self.px[y][x] = c

    def line(self, x0: int, y0: int, x1: int, y1: int, c: int) -> None:
        steps = max(abs(x1 - x0), abs(y1 - y0), 1)
        for i in range(steps + 1):
            self.set(round(x0 + (x1 - x0) * i / steps), round(y0 + (y1 - y0) * i / steps), c)

    def disc(self, cx: float, cy: float, r: float, c: int) -> None:
        for y in range(int(cy - r - 1), int(cy + r + 2)):
            for x in range(int(cx - r - 1), int(cx + r + 2)):
                if (x - cx) ** 2 + (y - cy) ** 2 <= r * r:
                    self.set(x, y, c)

    def mirror(self) -> None:
        """La mitad izquierda, copiada en espejo a la derecha (la escena de 1 jugador es simétrica)."""
        for row in self.px:
            row[W // 2:] = row[: W // 2][::-1]


# --- Las piezas -----------------------------------------------------------------------------------


def wall(c: Canvas, top: int, bottom: int) -> None:
    """La pared del fondo: un punto más oscuro cada 8 píxeles (una pantalla de LEDs apagada)."""
    for y in range(top + 3, bottom, 8):
        for x in range(3, W, 8):
            c.set(x, y, SHADE)


def truss(c: Canvas, x0: int, x1: int) -> None:
    """La estructura de las luces, arriba: dos tubos con diagonales en zigzag (renglones 0 y 1)."""
    for x in range(x0, x1):
        c.set(x, 1, SHINE)
        c.set(x, 2, METAL)
        c.set(x, 13, SHINE)
        c.set(x, 14, METAL)
    for x in range(x0, x1, 16):
        c.line(x, 3, x + 8, 12, METAL)
        c.line(x + 8, 12, x + 16, 3, METAL)


def lamp(c: Canvas, x: int) -> None:
    """Un foco colgado del truss (renglón 2): el soporte, la lata y el lente encendido."""
    c.rect(x - 1, 15, x + 1, 17, METAL)
    c.rect(x - 3, 17, x + 3, 21, CABINET)
    c.set(x - 3, 17, BLACK)
    c.set(x + 2, 17, BLACK)
    c.rect(x - 2, 21, x + 2, 23, LAMP)
    c.rect(x - 3, 23, x + 3, 24, BEAM)


def beam(c: Canvas, x: int, y0: int, y1: int, slope: float, spread: float) -> None:
    """Un haz de luz: un cono a medias (un píxel sí y otro no) del color 12, que se abre al bajar."""
    for y in range(y0, y1):
        d = y - y0
        center = x + slope * d
        half = 1 + spread * d
        for px in range(int(center - half), int(center + half) + 1):
            if (px + y) % 2 == 0:
                c.set(px, y, BEAM)


def speaker(c: Canvas, x: int, y: int, w: int, h: int, cones: int) -> None:
    """Un gabinete: borde, rejilla con trama y `cones` bocinas en columna (o en cuadro, si caben dos)."""
    c.rect(x, y, x + w, y + h, BLACK)
    c.rect(x + 1, y + 1, x + w - 1, y + h - 1, CABINET)
    c.rect(x + 3, y + 3, x + w - 3, y + h - 3, GRILLE)
    for yy in range(y + 3, y + h - 3):
        for xx in range(x + 3, x + w - 3):
            if (xx + yy) % 3 == 0:
                c.set(xx, yy, BLACK)
    per_row = 2 if w >= 36 else 1
    rows = cones // per_row
    for i in range(cones):
        col, row = i % per_row, i // per_row
        cx = x + (w * (2 * col + 1)) / (2 * per_row) - 0.5
        cy = y + 3 + (h - 6) * (2 * row + 1) / (2 * rows) - 0.5
        r = min(w / per_row, (h - 6) / rows) / 2 - 2
        c.disc(cx, cy, r, BLACK)
        c.disc(cx, cy, r - 1, CABINET)
        c.disc(cx, cy, r - 2.5, GRILLE)
        c.disc(cx, cy, max(1.5, r / 4), METAL)
    c.rect(x + 3, y + h - 3, x + 9, y + h - 2, AMBER)      # el logo (una plaquita)


def tower(c: Canvas, x: int, y0: int, y1: int) -> None:
    """Una torre de luces vertical (2 tiles de ancho): dos tubos y diagonales."""
    for y in range(y0, y1):
        c.set(x + 1, y, SHINE)
        c.set(x + 2, y, METAL)
        c.set(x + 13, y, SHINE)
        c.set(x + 14, y, METAL)
    for y in range(y0, y1 - 15, 16):
        c.line(x + 3, y, x + 12, y + 8, METAL)
        c.line(x + 12, y + 8, x + 3, y + 16, METAL)


# --- El público -----------------------------------------------------------------------------------

# Las personas de la franja, en 3 filas (de atrás para adelante): (x del centro, fila, mitad del ancho de
# hombros). La franja mide CROWD_W tiles y se repite, así que las de la orilla siguen en la copia de al
# lado. Atrás, iluminados por el escenario; adelante, a contraluz.
PEOPLE = [
    (4, 0, 3), (12, 0, 3), (20, 0, 3), (28, 0, 3),
    (0, 1, 4), (11, 1, 4), (21, 1, 4),
    (6, 2, 5), (16, 2, 5), (26, 2, 5),
]
RANK_HEAD = (11, 25, 40)            # la altura de la cabeza de cada fila
RANK_COLOR = (LIT, SHADE, DARK)     # a contraluz: adelante, más oscuros (atrás los aclara la bruma)


def crowd_frame(frame: int) -> list[list[int]]:
    """La franja del público (CROWD_W*8 x CROWD_H*8) en uno de sus dibujos: 0 quieto (algunos con un brazo
    arriba), 1 brazos arriba (con lucecitas), 2 saltando (unos más que otros). Siluetas a contraluz: el
    borde de arriba de cabezas, hombros y brazos toma la luz del escenario (el color 12, que late)."""
    w, h = CROWD_W * 8, CROWD_H * 8
    px = [[WALL] * w for _ in range(h)]
    shape = [[False] * w for _ in range(h)]

    def put(x: int, y: int, c: int) -> None:
        if 0 <= y < h:
            px[y][x % w] = c

    for index, (cx, rank, shoulders) in enumerate(PEOPLE):
        jump = 3 if frame == 2 and index % 2 == 0 else (1 if frame == 2 else 0)
        hy = RANK_HEAD[rank] - jump
        body = RANK_COLOR[rank]
        mine = [[False] * w for _ in range(h)]

        def fill(x: int, y: int) -> None:
            if 0 <= y < h:
                mine[y][x % w] = True

        # Cabeza
        for dy in range(-4, 4):
            for dx in range(-4, 4):
                if (dx + 0.5) ** 2 + (dy + 0.5) ** 2 <= 10:
                    fill(cx + dx, hy + dy)
        # Cuello, hombros que caen y el torso hasta abajo
        fill(cx - 1, hy + 4)
        fill(cx, hy + 4)
        for y in range(hy + 5, h):
            d = y - (hy + 5)
            spread = min(shoulders, 2 + d * 2)
            for x in range(cx - spread - 1, cx + spread + 1):
                fill(x, y)
        # Brazos arriba (2 píxeles de grueso)
        side = 1 if index % 2 else -1
        arms = []
        if frame > 0 or index % 3 == 0:
            arms.append(side)
            if frame > 0 and index % 3 != 1:
                arms.append(-side)
        for a in arms:
            base = cx + (shoulders if a > 0 else -shoulders - 1)
            for k in range(10):
                ax = base + a * (k // 4)
                fill(ax, hy + 6 - k)
                fill(ax + a, hy + 6 - k)
        # La silueta, con su borde de arriba iluminado
        for y in range(h):
            for x in range(w):
                if mine[y][x]:
                    lit_edge = y == 0 or not mine[y - 1][x]
                    px[y][x] = BEAM if lit_edge and y < h - 1 else body
                    shape[y][x] = True
        if frame == 1 and index % 4 == 1 and arms:      # una lucecita en la mano
            a = arms[0]
            put(cx + (shoulders if a > 0 else -shoulders - 1) + a * 2, hy - 4, AMBER)
            put(cx + (shoulders if a > 0 else -shoulders - 1) + a * 2, hy - 5, AMBER)
    return px


# --- Las escenas ----------------------------------------------------------------------------------


def scene_1p() -> tuple[Canvas, dict[tuple[int, int], tuple[int, int]]]:
    """1 jugador: truss y focos arriba, haces sobre la pared, bocinas a los lados y público abajo.
    Se dibuja la mitad izquierda y se refleja (salvo el público, que va en su franja)."""
    c = Canvas()
    wall(c, 24, H)
    for x, slope in ((20, 0.45), (60, 0.15), (100, -0.25)):
        beam(c, x, 24, 120, slope, 0.22)
    truss(c, 0, W)
    for x in (20, 60, 100, 140):
        lamp(c, x)
    speaker(c, 8, 50, 40, 34, 4)
    speaker(c, 12, 84, 32, 42, 2)
    c.mirror()
    crowd = {(row, col): ((col % CROWD_W), row - 16) for row in range(16, ROWS) for col in range(COLS)}
    return c, crowd


def scene_2p() -> tuple[Canvas, dict[tuple[int, int], tuple[int, int]]]:
    """2 jugadores: el truss en medio (las esquinas de arriba son de los nombres), una torre de luces entre
    las autopistas con el público abajo de ella, y un balcón con público en cada esquina de arriba."""
    c = Canvas()
    wall(c, 24, H)
    for x, slope in ((140, -0.35), (180, 0.35)):
        beam(c, x, 24, 112, slope, 0.12)
    truss(c, 72, 248)
    for x in (100, 140, 180, 220):
        lamp(c, x)
    tower(c, 152, 24, 112)
    # Balcones: una baranda bajo el público de las esquinas
    for x0, x1 in ((0, 40), (280, 320)):
        c.rect(x0, 64, x1, 66, SHINE)
        c.rect(x0, 66, x1, 70, METAL)
        for x in range(x0 + 3, x1, 6):
            c.rect(x, 70, x + 1, 72, METAL)
    crowd = {}
    for row in range(3, 8):              # el balcón: las dos filas de atrás de la franja
        for col in list(range(0, 5)) + list(range(35, 40)):
            crowd[(row, col)] = (col % CROWD_W, row - 3)
    for row in range(14, 20):            # entre las autopistas, abajo de la torre
        for col in range(17, 23):
            crowd[(row, col)] = (col % CROWD_W, row - 14 + 2)
    return c, crowd


# --- A tiles --------------------------------------------------------------------------------------


def tile_of(px: list[list[int]], col: int, row: int) -> tuple[int, ...]:
    return tuple(px[row * 8 + y][col * 8 + x] for y in range(8) for x in range(8))


def flip_h(t: tuple[int, ...]) -> tuple[int, ...]:
    return tuple(t[y * 8 + 7 - x] for y in range(8) for x in range(8))


def flip_v(t: tuple[int, ...]) -> tuple[int, ...]:
    return tuple(t[(7 - y) * 8 + x] for y in range(8) for x in range(8))


H_FLIP, V_FLIP = 0x0800, 0x1000    # los bits del VDP


class TileSet:
    """Tiles únicos (contando los volteados). Índice 0: la pared lisa (no se pone: queda la del trapecio)."""

    def __init__(self) -> None:
        self.tiles: list[tuple[int, ...]] = []
        self.index: dict[tuple[int, ...], int] = {}

    def add(self, t: tuple[int, ...]) -> int:
        """El valor del mapa: 0 si es pared lisa; si no, (número de tile + 1) con los bits de volteo."""
        if all(p == WALL for p in t):
            return 0
        for flags, variant in ((0, t), (H_FLIP, flip_h(t)), (V_FLIP, flip_v(t)), (H_FLIP | V_FLIP, flip_v(flip_h(t)))):
            if variant in self.index:
                return (self.index[variant] + 1) | flags
        self.index[t] = len(self.tiles)
        self.tiles.append(t)
        return len(self.tiles)


def pack(t: tuple[int, ...]) -> list[int]:
    return [int("".join(f"{p:X}" for p in t[y * 8 : y * 8 + 8]), 16) for y in range(8)]


def build() -> dict:
    """Las dos escenas, ya en tiles: lo que va en src/stage_gfx.c."""
    tiles = TileSet()
    frames = [crowd_frame(f) for f in range(CROWD_FRAMES)]
    maps = {}
    for name, (canvas, crowd) in (("1p", scene_1p()), ("2p", scene_2p())):
        grid = []
        for row in range(ROWS):
            line = []
            for col in range(COLS):
                if (row, col) in crowd:
                    cx, cy = crowd[(row, col)]
                    line.append(CROWD_MARK | (cy * CROWD_W + cx))
                else:
                    line.append(tiles.add(tile_of(canvas.px, col, row)))
            grid.append(line)
        maps[name] = (grid, canvas, crowd)
    crowd_tiles = [[tile_of(px, col, row) for row in range(CROWD_H) for col in range(CROWD_W)] for px in frames]
    return {"tiles": tiles.tiles, "maps": maps, "crowd": crowd_tiles, "frames": frames}


CROWD_MARK = 0x8000     # en el mapa: un tile de la franja del público (los bits de abajo: cuál)


def write_c(data: dict, path: Path) -> None:
    out = [
        "// Generado por `genband build-stage` (pctools/genband_tools/escenario.py): no editar a mano",
        '#include "genband.h"',
        "",
        f"const u16 stage_palette[16] = {{ {', '.join(f'0x{rgb_to_vdp(c):03X}' for c in COLORS)} }};",
        "",
        f"const u16 stage_tile_count = {len(data['tiles'])};",
        "const u32 stage_tiles[] = {",
    ]
    for t in data["tiles"]:
        out.append("    " + ", ".join(f"0x{v:08X}" for v in pack(t)) + ",")
    out.append("};")
    out.append("")
    out.append(f"const u32 stage_crowd[{CROWD_FRAMES}][{CROWD_W * CROWD_H * 8}] = {{")
    for frame in data["crowd"]:
        out.append("    {")
        for t in frame:
            out.append("        " + ", ".join(f"0x{v:08X}" for v in pack(t)) + ",")
        out.append("    },")
    out.append("};")
    for name, (grid, _, _) in data["maps"].items():
        out.append("")
        out.append(f"const u16 stage_map_{name}[{ROWS}][{COLS}] = {{")
        for line in grid:
            out.append("    { " + ", ".join(f"0x{v:04X}" for v in line) + " },")
        out.append("};")
    path.write_text("\n".join(out) + "\n", encoding="utf-8", newline="\n")


def rgb_to_vdp(rgb: int) -> int:
    """Como RGB24_TO_VDPCOLOR de SGDK: 3 bits por componente."""
    r, g, b = (rgb >> 16) & 0xFF, (rgb >> 8) & 0xFF, rgb & 0xFF
    return ((r >> 5) << 1) | ((g >> 5) << 5) | ((b >> 5) << 9)


def preview_png(data: dict, name: str, path: Path, highways: list[tuple[int, int, int]]) -> None:
    """La escena como la vería el juego: con la autopista encima y el público en su primer dibujo."""
    grid, canvas, crowd = data["maps"][name]
    frame = data["frames"][1]
    px = [row[:] for row in canvas.px]
    for (row, col), (cx, cy) in crowd.items():
        for y in range(8):
            for x in range(8):
                px[row * 8 + y][col * 8 + x] = frame[cy * 8 + y][cx * 8 + x]
    for y in range(24, H):
        s = 256 * (3 * y + 248) // 800
        for cx, lanes, lw in highways:
            half = lanes * lw // 2
            edges = [max(0, min(319, cx + ((lw * k - half) * s + 128) // 256)) for k in range(lanes + 1)]
            for x in range(edges[0], edges[-1] + 1):
                px[y][x] = 1
            for e in edges:
                px[y][e] = 2
    write_png(px, path)


def write_png(px: list[list[int]], path: Path, zoom: int = 2) -> None:
    rows = b""
    for row in px:
        line = bytearray([0])
        for c in row:
            rgb = COLORS[c]
            line += bytes(((rgb >> 16) & 0xFF, (rgb >> 8) & 0xFF, rgb & 0xFF)) * zoom
        rows += bytes(line) * zoom
    w, h = len(px[0]) * zoom, len(px) * zoom

    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)

    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(rows, 9)) + chunk(b"IEND", b"")
    path.write_bytes(png)
