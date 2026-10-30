// El escenario vivo: público, luces y el rayo de las frases estelares (como en NESBand).
//
// Lo que se ve (plano B, alrededor del trapecio de la autopista):
//   1 jugador:   bocinas a los lados, una torre con su foco arriba en cada esquina y su haz de luz, y
//                el público abajo a los lados (dos filas de gente).
//   2 jugadores: una torre con dos focos en el centro, entre las autopistas (no queda lugar para público).
//
// Casi no cuesta CPU, porque nada de esto reescribe el mapa:
//   * Las luces (haces y focos) usan los colores 12 y 13 de la paleta 0: para que laten o cambien de
//     color basta cambiar esos dos colores (por la cola de DMA).
//   * El público usa 4 tiles (arriba y abajo de dos personas distintas) que se repiten: para animarlo
//     se copian a la VRAM los 4 tiles del cuadro que toca (quieto, brazos arriba o saltando).
//
// Cómo reacciona (stage_update, una vez por cuadro):
//   * Nadie sigue en pie: luces apagadas y público quieto.
//   * Sin combo (menos de STAGE_CHEER): público quieto y luz tenue.
//   * Con combo: brazos arriba, y al empezar cada tiempo de la canción salta y la luz late.
//   * Con poder estelar: además, el color de las luces cambia en cada tiempo.
//   * Frase estelar completa: destello blanco (stage_flash), además del rayo (play.c).

#include "genband.h"

#define STAGE_CHEER  10         // combo desde el que el público se anima
#define STAGE_ATTACK 6          // cuadros del inicio de cada tiempo en que el público salta y la luz late
#define FLASH_FRAMES 8

#define C(rgb) RGB24_TO_VDPCOLOR(rgb)

static u16 lights[2];           // los colores 12 (haz) y 13 (foco) de la paleta 0
static u16 crowd_frame;         // el dibujo del público en la VRAM (0 quieto, 1 brazos, 2 salto)
static u16 flash;
static u16 last_beat;
static u16 color_step;          // con poder estelar, el color de las luces avanza en cada tiempo

static const u16 star_colors[4][2] = {
    { C(0x40E0F0), C(0xC0FFFF) }, { C(0xF04040), C(0xFFC0C0) },
    { C(0xF0E040), C(0xFFFFC0) }, { C(0xC060F0), C(0xF0C0FF) },
};

// Un tile del escenario, solo donde el trapecio dejó escenario (nunca encima de la autopista)
static void put(u16 x, u16 y, u16 tile)
{
    if (y >= STRIP_ROW || x >= 40) return;
    if ((trap_map[y][x] & TILE_INDEX_MASK) != tile_solid + 3) return;
    VDP_setTileMapXY(BG_B, TILE_ATTR_FULL(PAL0, 1, 0, 0, tile), x, y);
}

static void fill(u16 x, u16 y, u16 w, u16 h, u16 tile)
{
    for (u16 j = 0; j < h; j++)
        for (u16 i = 0; i < w; i++) put(x + i, y + j, tile);
}

// Una torre: el pilar, el foco arriba y el haz que baja hacia la autopista (dir = 1 a la derecha, -1 izquierda)
static void tower(s16 x, s16 dir, u16 top)
{
    fill(x, top + 1, 1, STRIP_ROW - top - 1, tile_solid + 10);
    put(x, top, tile_lamp);
    for (u16 y = 0; y < 9; y++)
        fill(x + dir * (1 + y / 2), top + 1 + y, 2, 1, tile_solid + 12);
}

static void speaker(u16 x)
{
    fill(x, 10, 4, 8, tile_solid + 11);
    fill(x + 1, 11, 2, 2, tile_solid + 9);
    fill(x + 1, 14, 2, 3, tile_solid + 9);
    put(x + 1, 15, tile_solid + 10);
    put(x + 2, 15, tile_solid + 10);
}

// Dos filas de gente (4 renglones de tiles): arriba cabezas y brazos, abajo los cuerpos. Se alternan las
// dos personas para que no se vea todo igual
static void crowd(u16 x, u16 w)
{
    for (u16 rank = 0; rank < 2; rank++)
        for (u16 i = 0; i < w; i++)
        {
            const u16 person = (i + rank) & 1;
            put(x + i, 20 + rank * 2, tile_crowd + person * 2);
            put(x + i, 21 + rank * 2, tile_crowd + person * 2 + 1);
        }
}

void stage_draw(u16 nplayers)
{
    lights[0] = C(0x403858);
    lights[1] = C(0xA0A0A0);
    PAL_setColors(12, lights, 2, CPU);
    crowd_frame = 0xFFFF;       // (stage_update copia el primero)
    flash = 0;
    last_beat = 0xFFFF;
    color_step = 0;
    if (nplayers == 1)
    {
        speaker(1);
        speaker(35);
        tower(0, 1, 1);
        tower(39, -1, 1);
        crowd(0, 10);
        crowd(30, 10);
    }
    else
    {
        tower(19, -1, 0);
        tower(20, 1, 0);
    }
}

void stage_flash(void)
{
    flash = FLASH_FRAMES;
}

void stage_update(u16 now, const Song *song, u16 combo, bool star, bool all_failed)
{
    // ¿En qué tiempo vamos, y cuántos cuadros lleva?
    u16 beat = 0, phase = 0xFFFF;
    if (now >= song->first_beat % song->beat_frames)
    {
        const u16 since = now - song->first_beat % song->beat_frames;
        beat = since / song->beat_frames;
        phase = since % song->beat_frames;
    }
    const bool attack = phase < STAGE_ATTACK;
    if (star && beat != last_beat && attack) color_step = (color_step + 1) % 4;
    last_beat = beat;

    // Las luces
    u16 beam, lamp;
    if (all_failed)
    {
        beam = C(0x180828);
        lamp = C(0x202020);
    }
    else if (flash)
    {
        flash--;
        beam = lamp = C(0xFFFFFF);
    }
    else if (star)
    {
        beam = star_colors[color_step][0];
        lamp = star_colors[color_step][1];
    }
    else if (combo >= STAGE_CHEER && attack)
    {
        beam = C(0x8080C0);
        lamp = C(0xFFFFFF);
    }
    else
    {
        beam = C(0x403858);
        lamp = C(0xA0A0A0);
    }
    if (beam != lights[0] || lamp != lights[1])
    {
        lights[0] = beam;
        lights[1] = lamp;
        PAL_setColors(12, lights, 2, DMA_QUEUE);
    }

    // El público
    const u16 frame = (all_failed || combo < STAGE_CHEER) ? 0 : (attack ? 2 : 1);
    if (frame != crowd_frame)
    {
        crowd_frame = frame;
        DMA_queueDma(DMA_VRAM, (void *) &crowd_tiles[frame * 4 * 8], tile_crowd * 32, 4 * 16, 2);
    }
}
