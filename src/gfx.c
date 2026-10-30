// Gráficos: las paletas y todos los tiles del juego. No hay imágenes: cada dibujo (gemas, aros,
// llamaradas, colas) se genera aquí al arrancar, píxel por píxel, y se copia a la VRAM. Las gemas van en
// GEM_SCALES tamaños para la perspectiva (el VDP no escala sprites: se elige el dibujo del tamaño que toca).
//
// Paletas (el índice 15 de cada una es un color de texto, porque la fuente de SGDK usa ese índice):
//   PAL0  escenario y autopista; texto blanco
//   PAL1  gemas, aros y colas: los colores de los carriles; texto gris
//   PAL2  llamaradas y logo; texto amarillo
//   PAL3  llamaradas del poder estelar, medidor de vida y barra estelar; texto rojo

#include "genband.h"

#define C(rgb) RGB24_TO_VDPCOLOR(rgb)

// PAL1: colores de los carriles
#define P1_OUTLINE  1
#define P1_WHITE    2
#define P1_LANE     3           // + carril: verde, rojo, amarillo, azul, naranja
#define P1_DARK     8           // + carril: lo mismo, más oscuro
#define P1_STAR     13
#define P1_STAR_DK  14
#define P1_GRAY     15

static const u16 palettes[64] = {
    // PAL0: escenario y autopista
    C(0x000000), C(0x080838), C(0x384868), C(0x180828), C(0x302050), C(0x504078), C(0x201010), C(0x402020),
    C(0x606060), C(0x283040), C(0x484858), C(0x101418), C(0x000000), C(0x000000), C(0x909090), C(0xFFFFFF),
    // PAL1: carriles
    C(0x000000), C(0x000000), C(0xFFFFFF), C(0x30D040), C(0xF02828), C(0xF8E020), C(0x3070F8), C(0xF88820),
    C(0x106018), C(0x801010), C(0x887800), C(0x103080), C(0x904010), C(0xC0F0FF), C(0x40A0F0), C(0x707070),
    // PAL2: llamaradas y logo
    C(0x000000), C(0xFFFFC0), C(0xFFE040), C(0xFF8000), C(0xC02000), C(0xFFF060), C(0xFFC020), C(0xFF9010),
    C(0xFF5020), C(0xE82050), C(0xC01880), C(0x8010A0), C(0x000000), C(0x000000), C(0x000000), C(0xFFE040),
    // PAL3: poder estelar, medidor, barra estelar
    C(0x000000), C(0xFFFFFF), C(0xA0E0FF), C(0x40A0FF), C(0x2040C0), C(0x20E040), C(0xF0E020), C(0xF02020),
    C(0x181818), C(0xE0E0E0), C(0x40C0FF), C(0x303040), C(0x000000), C(0x000000), C(0x000000), C(0xFF5040),
};

u16 tile_solid, tile_scroll, tile_gem, tile_star_gem, tile_ring, tile_ring_on, tile_flame, tile_tail;
u16 tile_meter, tile_starbar, tile_logo;

static u16 next_tile;
static u32 buf[8 * 8];          // hasta 8 tiles a la vez (un sprite de 4x2)
static u8 canvas[16][32];       // un sprite de 32x16 píxeles

static u16 load(const u32 *data, u16 count)
{
    const u16 index = next_tile;
    VDP_loadTileData(data, index, count, CPU);
    next_tile += count;
    return index;
}

u16 gfx_load_tile(const u32 *data)
{
    return load(data, 1);
}

static void clear_canvas(void)
{
    memset(canvas, 0, sizeof(canvas));
}

// El lienzo de 32x16 a 8 tiles en el orden de los sprites (columna por columna)
static u16 load_canvas(void)
{
    u32 *t = buf;
    for (u16 col = 0; col < 4; col++)
        for (u16 row = 0; row < 2; row++)
            for (u16 y = 0; y < 8; y++)
            {
                u32 line = 0;
                for (u16 x = 0; x < 8; x++)
                    line = (line << 4) | canvas[row * 8 + y][col * 8 + x];
                *t++ = line;
            }
    return load(buf, 8);
}

// Las formas se dibujan una vez con los colores del carril 0 (P1_LANE y P1_DARK) y se recolorean para
// cada carril: calcular la forma es lo lento (el 68000 no divide rápido). El recoloreo se hace sobre los
// tiles ya empacados, byte por byte, con una tabla (cada byte son dos píxeles)
static u16 load_lanes(void)
{
    u32 shape[8 * 8];
    u8 map[256];
    load_canvas();
    next_tile -= 8;             // load_canvas dejó la forma en buf; el carril 0 se vuelve a cargar abajo
    memcpy(shape, buf, sizeof(shape));
    const u16 first = next_tile;
    for (u16 lane = 0; lane < NUM_LANES; lane++)
    {
        for (u16 b = 0; b < 256; b++)
        {
            u8 hi = b >> 4, lo = b & 15;
            if (hi == P1_LANE || hi == P1_DARK) hi += lane;
            if (lo == P1_LANE || lo == P1_DARK) lo += lane;
            map[b] = (hi << 4) | lo;
        }
        const u8 *src = (const u8 *) shape;
        u8 *dst = (u8 *) buf;
        for (u16 i = 0; i < sizeof(shape); i++) dst[i] = map[src[i]];
        load(buf, 8);
    }
    return first;
}

// Distancia (al cuadrado, en una escala donde 256 = el borde) de un píxel al centro de una elipse que
// llena el lienzo de 32x16 con radios rx, ry (en medios píxeles). Las divisiones son entre constantes
// (el compilador las resuelve) y las multiplicaciones son de 16 bits: el 68000 las hace en hardware.
#define INV(r) ((u16) (65536 / ((r) * (r))))
static inline s32 ellipse_inv(s16 x, s16 y, u16 inv_x, u16 inv_y)
{
    const u16 dx = abs(2 * x - 31);
    const u16 dy = abs(2 * y - 15);
    return ((u32) (u16) (dx * dx) * inv_x + (u32) (u16) (dy * dy) * inv_y) >> 8;
}
#define ellipse(x, y, rx, ry) ellipse_inv((x), (y), INV(rx), INV(ry))

// Una gema a escala k (0 = tamaño completo, cada paso es 10% más chica): elipse con brillo, o diamante
// si es estelar
static void draw_gem(bool star, u16 k)
{
    const s16 sc = 10 - k;                              // escala en décimas
    clear_canvas();
    if (star)
    {
        // Diamante: |dx|/rx + |dy|/ry <= 1, con el borde del color del carril. Los umbrales se calculan
        // antes del bucle: dentro solo hay multiplicaciones de 16 bits
        const u16 rx = 30 * sc / 10, ry = 15 * sc / 10;
        const u32 edge = (u32) rx * ry, outline = edge * 27 / 32, lane = edge * 2 / 3, shine = edge / 4;
        const s16 dark = 3 * sc / 10;
        for (s16 y = 0; y < 16; y++)
        {
            const s16 dy = 2 * y - 15;
            const u32 dy_part = (u32) (u16) abs(dy) * rx;
            for (s16 x = 0; x < 32; x++)
            {
                const u32 d = (u32) (u16) abs(2 * x - 31) * ry + dy_part;
                if (d > edge) continue;
                u8 c = P1_STAR;
                if (d > outline) c = P1_OUTLINE;
                else if (d > lane) c = P1_LANE;
                else if (dy > dark) c = P1_STAR_DK;
                else if (d < shine && dy < 0) c = P1_WHITE;
                canvas[y][x] = c;
            }
        }
        return;
    }
    const u16 rx = 29 * sc / 10, ry = 14 * sc / 10;
    const u16 inv_x = 65536 / (rx * rx), inv_y = 65536 / (ry * ry);
    const u16 hx = 12 * sc / 10, hy = max(2, 5 * sc / 10);
    const u16 hinv_x = 65536 / (hx * hx), hinv_y = 65536 / (hy * hy);
    const s16 ox = 5 * sc / 10, oy = 2 * sc / 10, dark = 5 * sc / 10;
    for (s16 y = 0; y < 16; y++)
        for (s16 x = 0; x < 32; x++)
        {
            const s32 d = ellipse_inv(x, y, inv_x, inv_y);
            if (d > 256) continue;
            u8 c = P1_LANE;
            if (d > 190) c = P1_OUTLINE;
            else if (2 * y - 15 >= dark) c = P1_DARK;
            else if (ellipse_inv(x + ox, y + oy, hinv_x, hinv_y) < 256) c = P1_WHITE;
            canvas[y][x] = c;
        }
}

static void draw_ring(bool pressed)
{
    clear_canvas();
    for (s16 y = 0; y < 16; y++)
        for (s16 x = 0; x < 32; x++)
        {
            const s32 d = ellipse(x, y, 30, 15);
            if (d > 256) continue;
            u8 c = 0;
            if (d > 200) c = P1_OUTLINE;
            else if (d > 120) c = pressed ? P1_WHITE : P1_LANE;
            else if (d > 90) c = P1_OUTLINE;
            else if (pressed) c = P1_LANE;
            canvas[y][x] = c;
        }
}

// Llamarada al acertar: un anillo que crece y se apaga en 4 dibujos (colores 1-4 de PAL2 o PAL3)
static void draw_flame(u16 frame)
{
    clear_canvas();
    const s32 outer = 120 + 50 * frame;
    for (s16 y = 0; y < 16; y++)
        for (s16 x = 0; x < 32; x++)
        {
            const s32 d = ellipse(x, y, 26, 13);     // un poco más chica que el aro
            if (d > outer) continue;
            if (frame < 2 && d < 60) canvas[y][x] = 1;
            else if (d > outer - 60) canvas[y][x] = 1 + frame;
            else if (frame == 0) canvas[y][x] = 2;
            else if (((x + y + frame) & 3) == 0) canvas[y][x] = 1 + frame;
        }
    // Chispas que salen hacia arriba
    for (u16 i = 0; i < 6; i++)
    {
        const s16 x = 4 + i * 5 + (frame & 1);
        const s16 y = 10 - frame * 3 - (i & 1) * 2;
        if (y >= 0 && y < 16) canvas[y][x] = 1 + (i % 3);
    }
}

// Un tile de 8x8 en buf[0..7] con una función de píxel
static void tile_clear(u32 *t)
{
    memset(t, 0, 32);
}

static void tile_px(u32 *t, u16 x, u16 y, u8 c)
{
    const u16 shift = (7 - x) * 4;
    t[y] = (t[y] & ~(0xFUL << shift)) | ((u32) c << shift);
}

static void tile_hline(u32 *t, u16 y, u8 c)
{
    for (u16 x = 0; x < 8; x++) tile_px(t, x, y, c);
}

// --- Capa que se desplaza (plano A): las líneas de tiempo ------------------------------------------------
//
// Con la perspectiva, a lo lejos cada línea de pantalla salta varios píxeles del mundo: una línea de 1
// píxel aparecería y desaparecería. Por eso la de tiempo mide 2 y la de compás 3. Pueden caer en
// cualquier renglón del tile, así que hay un tile por renglón:
//
//   tile_scroll + 0..7     línea de tiempo (gris) desde el renglón 0..7
//   tile_scroll + 8..15    línea de compás (blanca) desde el renglón 0..7

u16 scroll_tile(u16 line, u16 row)
{
    // line: 0 = nada, 1 = tiempo, 2 = compás; row: renglón de la línea dentro del tile
    return line ? tile_scroll + (line - 1) * 8 + row : 0;
}

static void make_scroll_tiles(void)
{
    u32 t[8];
    tile_scroll = next_tile;
    for (u16 kind = 0; kind < 2; kind++)
        for (u16 row = 0; row < 8; row++)
        {
            const u16 thick = kind ? 3 : 2;
            const u16 first = min(row, 8 - thick);
            tile_clear(t);
            for (u16 y = first; y < first + thick; y++)
                t[y] = 0x11111111UL * (kind ? P1_WHITE : P1_GRAY);
            load(t, 1);
        }
}

// Colas de las notas sostenidas: sprites de 8x16 (dos tiles iguales) en 3 anchos (8, 6 y 4 píxeles)
// por carril, que se apilan a lo largo de la cola y se angostan a lo lejos
static void make_tail_tiles(void)
{
    u32 t[8];
    tile_tail = next_tile;
    for (u16 w = 0; w < 3; w++)
        for (u16 lane = 0; lane < NUM_LANES; lane++)
        {
            const u16 width = 8 - 2 * w, first = w;
            u32 row = 0;
            for (u16 x = 0; x < 8; x++)
            {
                u32 c = 0;
                if (x >= first && x < first + width)
                    c = (x == first || x == first + width - 1) ? P1_DARK + lane : P1_LANE + lane;
                row = (row << 4) | c;
            }
            for (u16 y = 0; y < 8; y++) t[y] = row;
            load(t, 1);
            load(t, 1);
        }
}

static void make_hud_tiles(void)
{
    u32 t[8];
    // Medidor de vida: 9 niveles (0..8 renglones llenos desde abajo) en verde, amarillo y rojo (PAL3 5-7)
    tile_meter = next_tile;
    for (u16 color = 0; color < 3; color++)
        for (u16 level = 0; level <= 8; level++)
        {
            for (u16 y = 0; y < 8; y++)
            {
                const u8 c = (y >= 8 - level) ? 5 + color : 8;
                t[y] = 0x01111110UL * c;
                t[y] = (t[y] & 0x0FFFFFF0) | 0x10000001;     // el borde blanco
            }
            load(t, 1);
        }
    // Barra estelar: 9 niveles (0..8 columnas llenas desde la izquierda), blanca o azul (PAL3 9-10)
    tile_starbar = next_tile;
    for (u16 color = 0; color < 2; color++)
        for (u16 level = 0; level <= 8; level++)
        {
            tile_clear(t);
            for (u16 y = 2; y < 6; y++)
                for (u16 x = 0; x < 8; x++)
                    tile_px(t, x, y, x < level ? 9 + color : 11);
            tile_hline(t, 1, 1);
            tile_hline(t, 6, 1);
            load(t, 1);
        }
}

void gfx_init(void)
{
    PAL_setColors(0, palettes, 64, CPU);
    next_tile = TILE_USER_INDEX;

    // Las letras de NESBand (Bongo-8 Mono) en lugar de las de SGDK; lo que no trae se queda como está
    for (u16 i = 0; i < font_count; i++)
        VDP_loadTileData(&font_tiles[i * 8], TILE_FONT_INDEX + font_codes[i] - 32, 1, CPU);

    u32 t[8];
    tile_solid = next_tile;
    for (u16 c = 0; c < 16; c++)
    {
        for (u16 y = 0; y < 8; y++) t[y] = 0x11111111UL * c;
        load(t, 1);
    }

    make_scroll_tiles();
    make_tail_tiles();

    // Gemas: tile_gem + (escala * NUM_LANES + carril) * 8
    tile_gem = next_tile;
    for (u16 k = 0; k < GEM_SCALES; k++)
    {
        draw_gem(FALSE, k);
        load_lanes();
    }
    tile_star_gem = next_tile;
    for (u16 k = 0; k < GEM_SCALES; k++)
    {
        draw_gem(TRUE, k);
        load_lanes();
    }
    draw_ring(FALSE);
    tile_ring = load_lanes();
    draw_ring(TRUE);
    tile_ring_on = load_lanes();
    tile_flame = next_tile;
    for (u16 frame = 0; frame < 4; frame++)
    {
        draw_flame(frame);
        load_canvas();
    }

    make_hud_tiles();

    // Logo: un tile sólido por renglón de las letras, del amarillo al morado (PAL2 5-11)
    tile_logo = next_tile;
    for (u16 c = 0; c < 7; c++)
    {
        for (u16 y = 0; y < 8; y++) t[y] = 0x11111111UL * (5 + c);
        t[7] = 0;                                         // una línea oscura entre renglones
        load(t, 1);
    }

    perspective_init();
}
