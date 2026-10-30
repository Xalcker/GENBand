// Gráficos: las paletas y la carga de todos los tiles del juego a la VRAM. No hay imágenes: cada dibujo
// (gemas, aros, llamaradas, colas, el escenario) se genera en Python al compilar (`genband build-gfx`) y
// llega en gfx_data.c y stage_gfx.c. Las gemas van en GEM_SCALES tamaños para la perspectiva (el VDP no
// escala sprites: se elige el dibujo del tamaño que toca).
//
// Paletas (el índice 15 de cada una es un color de texto, porque la fuente de SGDK usa ese índice):
//   PAL0  escenario y autopista; texto blanco
//   PAL1  gemas, aros y colas: los colores de los carriles; texto gris
//   PAL2  llamaradas y logo; texto amarillo
//   PAL3  llamaradas del poder estelar, medidor de vida y barra estelar; texto rojo

#include "genband.h"

#define C(rgb) RGB24_TO_VDPCOLOR(rgb)

static const u16 palettes[64] = {
    // PAL0: escenario y autopista (la pone gfx_init desde stage_palette, la de escenario.py)
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    // PAL1: carriles (1 borde, 2 blanco, 3-7 los carriles, 8-12 lo mismo más oscuro, 13-14 la gema
    // estelar; los nombres están en graficos.py)
    C(0x000000), C(0x000000), C(0xFFFFFF), C(0x30D040), C(0xF02828), C(0xF8E020), C(0x3070F8), C(0xF88820),
    C(0x106018), C(0x801010), C(0x887800), C(0x103080), C(0x904010), C(0xC0F0FF), C(0x40A0F0), C(0x707070),
    // PAL2: llamaradas y logo
    C(0x000000), C(0xFFFFC0), C(0xFFE040), C(0xFF8000), C(0xC02000), C(0xFFF060), C(0xFFC020), C(0xFF9010),
    C(0xFF5020), C(0xE82050), C(0xC01880), C(0x8010A0), C(0x000000), C(0x000000), C(0x000000), C(0xFFE040),
    // PAL3: poder estelar, medidor, barra estelar
    C(0x000000), C(0xFFFFFF), C(0xA0E0FF), C(0x40A0FF), C(0x2040C0), C(0x20E040), C(0xF0E020), C(0xF02020),
    C(0x181818), C(0xE0E0E0), C(0x40C0FF), C(0x303040), C(0x000000), C(0x000000), C(0x000000), C(0xFF5040),
};

u16 tile_solid, tile_scroll, tile_gem, tile_star_gem, tile_cymbal, tile_ring, tile_ring_on, tile_flame, tile_tail;
u16 tile_trap;
u16 tile_stage, tile_bolt;
u16 tile_meter, tile_starbar, tile_logo;

static u16 next_tile;

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

// --- Capa que se desplaza (plano A): las líneas de tiempo ------------------------------------------------
//
// Con la perspectiva, a lo lejos cada línea de pantalla salta varios píxeles del mundo: una línea de 1
// píxel aparecería y desaparecería. Por eso la de tiempo mide 2 y la de compás 3. Pueden caer en
// cualquier renglón del tile, así que hay un tile por renglón:
//
//   tile_scroll + 0..7     línea de tiempo (gris) desde el renglón 0..7
//   tile_scroll + 8..15    línea de compás (blanca) desde el renglón 0..7
//   tile_scroll + 16..23   la barra del bombo de la batería (naranja, 4 píxeles) desde el renglón 0..7

u16 scroll_tile(u16 line, u16 row)
{
    // line: 0 = nada, 1 = tiempo, 2 = compás, 3 = bombo; row: renglón de la línea dentro del tile
    return line ? tile_scroll + (line - 1) * 8 + row : 0;
}

// Los tiles se dibujan en Python (pctools/genband_tools/graficos.py y escenario.py, `genband build-gfx`)
// y llegan hechos en gfx_data.c y stage_gfx.c: aquí solo se copian a la VRAM, en este orden
#define LOAD(group) load(group, sizeof(group) / 32)

void gfx_init(void)
{
    PAL_setColors(0, palettes, 64, CPU);
    PAL_setColors(0, stage_palette, 16, CPU);
    next_tile = TILE_USER_INDEX;

    // Las letras de NESBand (Bongo-8 Mono) en lugar de las de SGDK; lo que no trae se queda como está
    for (u16 i = 0; i < font_count; i++)
        VDP_loadTileData(&font_tiles[i * 8], TILE_FONT_INDEX + font_codes[i] - 32, 1, CPU);

    tile_solid = LOAD(gfx_solid);
    tile_scroll = LOAD(gfx_scroll);
    tile_tail = LOAD(gfx_tail);
    tile_gem = LOAD(gfx_gem);
    tile_star_gem = LOAD(gfx_star_gem);
    tile_cymbal = LOAD(gfx_cymbal);
    tile_ring = LOAD(gfx_ring);
    tile_ring_on = LOAD(gfx_ring_on);
    tile_flame = LOAD(gfx_flame);
    tile_meter = LOAD(gfx_meter);
    tile_starbar = LOAD(gfx_starbar);
    // El escenario: la franja del público al principio (stage.c la cambia por sus otros dibujos)
    tile_stage = load(stage_crowd[0], STAGE_CROWD_TILES);
    load(stage_tiles, stage_tile_count);
    tile_bolt = LOAD(gfx_bolt);
    tile_logo = LOAD(gfx_logo);

    // Lo que queda antes de la fuente es para el trapecio de la autopista, que se arma al empezar cada
    // partida (con 5 carriles, o 4 en la batería): ver perspective_build
    tile_trap = next_tile;
    perspective_init();
}
