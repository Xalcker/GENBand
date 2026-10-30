"""Los gráficos del juego, dibujados aquí y no al arrancar: `genband build-gfx` escribe src/gfx_data.c.

Antes src/gfx.c los dibujaba píxel por píxel al encender la consola (gemas en 7 tamaños, aros, llamaradas,
colas...), y el 68000 tardaba unos 2 segundos. Ahora la ROM los trae hechos y gfx_init solo los copia a
la VRAM. Los dibujos son los mismos, con las mismas cuentas enteras que tenía el C (las divisiones
truncan y los valores de 16 bits se cortan igual), así que los tiles salen idénticos.

Cada grupo es una lista de tiles (8 renglones de 8 píxeles de 4 bits, empacados en un u32 por renglón),
en el orden en que gfx_init los carga. El escenario (el truss, las bocinas, el público) está aparte, en
escenario.py.
"""

from __future__ import annotations

from pathlib import Path

NUM_LANES = 5
GEM_SCALES = 7

# PAL1 (gfx.c)
P1_OUTLINE, P1_WHITE, P1_LANE, P1_DARK, P1_STAR, P1_STAR_DK, P1_GRAY = 1, 2, 3, 8, 13, 14, 15

Tile = tuple[int, ...]      # 8 renglones (u32)


def solid(c: int) -> Tile:
    return (0x11111111 * c,) * 8


def canvas_tiles(canvas: list[list[int]]) -> list[Tile]:
    """El lienzo de 32x16 en 8 tiles, en el orden de los sprites (columna por columna)."""
    tiles = []
    for col in range(4):
        for row in range(2):
            tiles.append(tuple(_pack(canvas[row * 8 + y][col * 8 : col * 8 + 8]) for y in range(8)))
    return tiles


def _pack(pixels: list[int]) -> int:
    line = 0
    for p in pixels:
        line = (line << 4) | p
    return line


def lanes(canvas: list[list[int]]) -> list[Tile]:
    """Una forma dibujada con los colores del carril 0, en los 5 carriles (8 tiles cada uno)."""
    out = []
    for lane in range(NUM_LANES):
        recolored = [[p + lane if p in (P1_LANE, P1_DARK) else p for p in row] for row in canvas]
        out += canvas_tiles(recolored)
    return out


def blank() -> list[list[int]]:
    return [[0] * 32 for _ in range(16)]


def ellipse_inv(x: int, y: int, inv_x: int, inv_y: int) -> int:
    """Distancia (al cuadrado, 256 = el borde) al centro de una elipse que llena el lienzo de 32x16."""
    dx, dy = abs(2 * x - 31), abs(2 * y - 15)
    return ((dx * dx & 0xFFFF) * inv_x + (dy * dy & 0xFFFF) * inv_y) >> 8


def inv(r: int) -> int:
    return (65536 // (r * r)) & 0xFFFF


def draw_gem(star: bool, k: int, cymbal: bool) -> list[list[int]]:
    """Una gema a escala k (0 = tamaño completo, cada paso es 10% más chica): elipse con brillo, o diamante
    si es estelar (azul con el borde del carril) o un platillo de la batería (del color del carril)."""
    sc = 10 - k
    c = blank()
    if star:
        rx, ry = 30 * sc // 10, 15 * sc // 10
        edge = rx * ry
        outline, lane, shine = edge * 27 // 32, edge * 2 // 3, edge // 4
        dark = 3 * sc // 10
        for y in range(16):
            dy = 2 * y - 15
            for x in range(32):
                d = abs(2 * x - 31) * ry + abs(dy) * rx
                if d > edge:
                    continue
                color = P1_LANE if cymbal else P1_STAR
                if d > outline:
                    color = P1_OUTLINE
                elif d > lane:
                    color = P1_DARK if cymbal else P1_LANE
                elif dy > dark:
                    color = P1_DARK if cymbal else P1_STAR_DK
                elif d < shine and dy < 0:
                    color = P1_WHITE
                c[y][x] = color
        return c
    rx, ry = 29 * sc // 10, 14 * sc // 10
    inv_x, inv_y = inv(rx), inv(ry)
    hx, hy = 12 * sc // 10, max(2, 5 * sc // 10)
    hinv_x, hinv_y = inv(hx), inv(hy)
    ox, oy, dark = 5 * sc // 10, 2 * sc // 10, 5 * sc // 10
    for y in range(16):
        for x in range(32):
            d = ellipse_inv(x, y, inv_x, inv_y)
            if d > 256:
                continue
            color = P1_LANE
            if d > 190:
                color = P1_OUTLINE
            elif 2 * y - 15 >= dark:
                color = P1_DARK
            elif ellipse_inv(x + ox, y + oy, hinv_x, hinv_y) < 256:
                color = P1_WHITE
            c[y][x] = color
    return c


def draw_ring(pressed: bool) -> list[list[int]]:
    c = blank()
    for y in range(16):
        for x in range(32):
            d = ellipse_inv(x, y, inv(30), inv(15))
            if d > 256:
                continue
            color = 0
            if d > 200:
                color = P1_OUTLINE
            elif d > 120:
                color = P1_WHITE if pressed else P1_LANE
            elif d > 90:
                color = P1_OUTLINE
            elif pressed:
                color = P1_LANE
            c[y][x] = color
    return c


def draw_flame(frame: int) -> list[list[int]]:
    """Llamarada al acertar: un anillo que crece y se apaga en 4 dibujos (colores 1-4 de PAL2 o PAL3)."""
    c = blank()
    outer = 120 + 50 * frame
    for y in range(16):
        for x in range(32):
            d = ellipse_inv(x, y, inv(26), inv(13))     # un poco más chica que el aro
            if d > outer:
                continue
            if frame < 2 and d < 60:
                c[y][x] = 1
            elif d > outer - 60:
                c[y][x] = 1 + frame
            elif frame == 0:
                c[y][x] = 2
            elif (x + y + frame) & 3 == 0:
                c[y][x] = 1 + frame
    for i in range(6):          # chispas que salen hacia arriba
        x = 4 + i * 5 + (frame & 1)
        y = 10 - frame * 3 - (i & 1) * 2
        if 0 <= y < 16:
            c[y][x] = 1 + i % 3
    return c


def scroll_tiles() -> list[Tile]:
    """Las líneas de tiempo (2 px, gris), de compás (3 px, blanca) y la barra del bombo (4 px, naranja),
    cada una desde los renglones 0..7 del tile."""
    out = []
    for kind, thick in enumerate((2, 3, 4)):
        for row in range(8):
            first = min(row, 8 - thick)
            t = [0] * 8
            for y in range(first, first + thick):
                if kind == 2:
                    color = P1_DARK + 4 if y in (first, first + thick - 1) else P1_LANE + 4
                else:
                    color = P1_WHITE if kind else P1_GRAY
                t[y] = 0x11111111 * color
            out.append(tuple(t))
    return out


def tail_tiles() -> list[Tile]:
    """Colas de 8x16 (dos tiles iguales) en 3 anchos (8, 6 y 4 píxeles) por carril."""
    out = []
    for w in range(3):
        for lane in range(NUM_LANES):
            width, first = 8 - 2 * w, w
            pixels = [
                (P1_DARK + lane if x in (first, first + width - 1) else P1_LANE + lane) if first <= x < first + width else 0
                for x in range(8)
            ]
            t = (_pack(pixels),) * 8
            out += [t, t]
    return out


def meter_tiles() -> list[Tile]:
    """Medidor de vida: 9 niveles (0..8 renglones llenos desde abajo) en verde, amarillo y rojo (PAL3 5-7)."""
    out = []
    for color in range(3):
        for level in range(9):
            rows = []
            for y in range(8):
                c = 5 + color if y >= 8 - level else 8
                rows.append(((0x01111110 * c) & 0x0FFFFFF0) | 0x10000001)     # con el borde blanco
            out.append(tuple(rows))
    return out


def starbar_tiles() -> list[Tile]:
    """Barra estelar: 9 niveles (0..8 columnas llenas desde la izquierda), blanca o azul (PAL3 9-10)."""
    out = []
    for color in range(2):
        for level in range(9):
            rows = [0] * 8
            for y in range(2, 6):
                rows[y] = _pack([9 + color if x < level else 11 for x in range(8)])
            rows[1] = rows[6] = 0x11111111
            out.append(tuple(rows))
    return out


def bolt_tiles() -> list[Tile]:
    """El rayo de una frase estelar: 16x32 (2x4 tiles, columna por columna) en zigzag, blanco con borde
    amarillo (colores 1 y 2 de la paleta 2)."""
    px = [[0] * 16 for _ in range(32)]
    for y in range(32):
        phase = y % 16
        cx = 4 + (phase if phase < 8 else 16 - phase)
        for dx in range(-2, 3):
            if 0 <= cx + dx < 16:
                px[y][cx + dx] = 1 if abs(dx) <= 1 else 2
    return [tuple(_pack(px[row * 8 + y][col * 8 : col * 8 + 8]) for y in range(8)) for col in range(2) for row in range(4)]


def logo_tiles() -> list[Tile]:
    """El logo: un tile sólido por renglón de las letras, del amarillo al morado (PAL2 5-11), con una línea
    oscura abajo."""
    return [(0x11111111 * (5 + c),) * 7 + (0,) for c in range(7)]


def build() -> dict[str, list[Tile]]:
    """Todos los grupos, en el orden en que los carga gfx_init."""
    return {
        "solid": [solid(c) for c in range(16)],
        "scroll": scroll_tiles(),
        "tail": tail_tiles(),
        "gem": [t for k in range(GEM_SCALES) for t in lanes(draw_gem(False, k, False))],
        "star_gem": [t for k in range(GEM_SCALES) for t in lanes(draw_gem(True, k, False))],
        "cymbal": [t for k in range(GEM_SCALES) for t in lanes(draw_gem(True, k, True))],
        "ring": lanes(draw_ring(False)),
        "ring_on": lanes(draw_ring(True)),
        "flame": [t for frame in range(4) for t in canvas_tiles(draw_flame(frame))],
        "meter": meter_tiles(),
        "starbar": starbar_tiles(),
        "bolt": bolt_tiles(),
        "logo": logo_tiles(),
    }


def write_c(groups: dict[str, list[Tile]], path: Path) -> None:
    out = [
        "// Generado por `genband build-gfx` (pctools/genband_tools/graficos.py): no editar a mano",
        '#include "genband.h"',
    ]
    for name, tiles in groups.items():
        out.append("")
        out.append(f"const u32 gfx_{name}[{len(tiles)} * 8] = {{")
        for t in tiles:
            out.append("    " + ", ".join(f"0x{v:08X}" for v in t) + ",")
        out.append("};")
    path.write_text("\n".join(out) + "\n", encoding="utf-8", newline="\n")


# --- El trapecio de la autopista (perspective.c) -----------------------------------------------------
#
# El fondo de la autopista en perspectiva, para cada combinación de autopistas que puede haber: 1 jugador
# (5 carriles de 32 px, o 4 de 40 en la batería) o 2 jugadores (cada uno con lo suyo). Cada uno es una lista
# de tiles distintos y un mapa de 24x40: 0 = adentro de la autopista (el color de fondo), 1 = afuera (el
# escenario, color 3), n + 2 = el tile n de la lista (una orilla o una línea de carril).

HWY_TOP, STRIP_ROW = 24, 24
YV3, SPAN3 = -248, 800
TRAP_OUT, TRAP_LINE = 3, 2
LANE_KINDS = ((5, 32), (4, 40))     # (carriles, ancho): guitarra/teclado/bajo, o batería
LAYOUTS = [((160,) + a,) for a in LANE_KINDS] + [((80,) + a, (240,) + b) for a in LANE_KINDS for b in LANE_KINDS]


def line_scale(line: int) -> int:
    y = max(line, HWY_TOP)
    return 256 * (3 * y - YV3) // SPAN3


def trap_line(line: int, highways: tuple) -> list[int]:
    px = [TRAP_OUT] * 320
    if line < HWY_TOP:
        return px
    scale = line_scale(line)
    for cx, lanes, lane_w in highways:
        half = lanes * lane_w // 2
        bx = [min(319, max(0, cx + (((lane_w * k - half) * scale + 128) >> 8))) for k in range(lanes + 1)]
        for x in range(bx[0], bx[-1] + 1):
            px[x] = 0
        for x in bx:
            px[x] = TRAP_LINE
    return px


def trapezoid(highways: tuple) -> tuple[list[Tile], list[list[int]]]:
    tiles: list[Tile] = []
    index: dict[Tile, int] = {}
    grid = []
    for row in range(STRIP_ROW):
        lines = [trap_line(row * 8 + y, highways) for y in range(8)]
        cells = []
        for col in range(40):
            pixels = [line[col * 8 : col * 8 + 8] for line in lines]
            values = {p for r in pixels for p in r}
            if values == {TRAP_OUT}:
                cells.append(1)
            elif values == {0}:
                cells.append(0)
            else:
                t = tuple(_pack(r) for r in pixels)
                if t not in index:
                    index[t] = len(tiles)
                    tiles.append(t)
                cells.append(index[t] + 2)
        grid.append(cells)
    return tiles, grid


def write_trap_c(path: Path) -> None:
    out = [
        "// Generado por `genband build-gfx` (pctools/genband_tools/graficos.py): no editar a mano",
        '#include "genband.h"',
    ]
    entries = []
    for n, highways in enumerate(LAYOUTS):
        tiles, grid = trapezoid(highways)
        out.append("")
        out.append(f"static const u32 trap{n}_tiles[{len(tiles)} * 8] = {{")
        for t in tiles:
            out.append("    " + ", ".join(f"0x{v:08X}" for v in t) + ",")
        out.append("};")
        out.append(f"static const u8 trap{n}_map[{STRIP_ROW}][40] = {{")
        for cells in grid:
            out.append("    { " + ", ".join(str(v) for v in cells) + " },")
        out.append("};")
        hw = ", ".join(f"{{ {cx}, {lanes}, {w} }}" for cx, lanes, w in highways)
        entries.append(f"    {{ {len(highways)}, {{ {hw} }}, trap{n}_tiles, {len(tiles)}, trap{n}_map }},")
    out.append("")
    out.append(f"const TrapLayout trap_layouts[{len(LAYOUTS)}] = {{")
    out += entries
    out.append("};")
    out.append(f"const u16 trap_layout_count = {len(LAYOUTS)};")
    path.write_text("\n".join(out) + "\n", encoding="utf-8", newline="\n")
