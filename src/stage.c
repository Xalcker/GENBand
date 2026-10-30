// El escenario vivo: público, luces y el rayo de las frases estelares (como en NESBand).
//
// Lo que se ve (plano B, alrededor del trapecio de la autopista) se dibuja en Python
// (pctools/genband_tools/escenario.py) y llega en stage_gfx.c: una escena para 1 jugador (truss con
// focos, haces sobre la pared, bocinas y el público abajo) y otra para 2 (truss en medio, una torre de
// luces entre las autopistas con público abajo y un balcón con público en cada esquina). Cada tile se
// pone solo donde el trapecio deja escenario.
//
// Casi no cuesta CPU, porque nada de esto reescribe el mapa:
//   * Las luces (haces, focos y el borde iluminado del público) usan los colores 12 y 13 de la paleta 0:
//     para que laten o cambien de color basta cambiar esos dos colores (por la cola de DMA).
//   * El público es una franja de tiles que se repite: para animarlo se copian a la VRAM los tiles de la
//     franja en el dibujo que toca (quieto, brazos arriba o saltando).
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

void stage_draw(u16 nplayers)
{
    lights[0] = C(0x403858);
    lights[1] = C(0xA0A0A0);
    PAL_setColors(12, lights, 2, CPU);
    crowd_frame = 0xFFFF;       // (stage_update copia el primero)
    flash = 0;
    last_beat = 0xFFFF;
    color_step = 0;
    const u16 (*map)[40] = nplayers == 1 ? stage_map_1p : stage_map_2p;
    for (u16 y = 0; y < STRIP_ROW; y++)
    {
        u16 row[40];
        u16 changed = 0;
        for (u16 x = 0; x < 40; x++)
        {
            row[x] = trap_map[y][x];
            const u16 v = map[y][x];
            if (!v || (row[x] & TILE_INDEX_MASK) != tile_solid + 3) continue;   // pared lisa, o la autopista
            const u16 index = (v & STAGE_CROWD_MARK) ? (v & 0xFF) : STAGE_CROWD_TILES + (v & 0x7FF) - 1;
            row[x] = TILE_ATTR_FULL(PAL0, 1, 0, 0, tile_stage + index) | (v & (TILE_ATTR_HFLIP_MASK | TILE_ATTR_VFLIP_MASK));
            changed++;
        }
        if (changed) VDP_setTileMapDataRow(BG_B, row, y, 0, 40, CPU);
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
        DMA_queueDma(DMA_VRAM, (void *) stage_crowd[frame], tile_stage * 32, STAGE_CROWD_TILES * 16, 2);
    }
}
