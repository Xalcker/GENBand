// Perspectiva de la autopista.
//
// La Genesis no escala por hardware, así que la perspectiva se arma con tres trucos:
//
//   1. El fondo (plano B) es un trapecio ya dibujado: los carriles convergen hacia arriba. Fuera del
//      trapecio el plano B es opaco y tiene prioridad alta, así que tapa lo que se desplaza (plano A).
//   2. Las líneas de tiempo (plano A) se desplazan con un scroll vertical distinto en cada línea de
//      pantalla: una interrupción por línea (HInt) elige qué renglón del mundo se ve en cada una. Arriba
//      se ven muchos renglones apretados y abajo pocos estirados. Es el truco de las carreteras de los
//      juegos de carreras (OutRun, Road Rash).
//   3. Las gemas y las colas son sprites dibujados en varios tamaños (gfx.c), puestos donde caen.
//
// La proyección: a la profundidad d (píxeles del mundo por delante de los aros) la escala es
// s(d) = K / (K + d) y la línea de pantalla y(d) = YV + (HIT_Y - YV) * s(d). Con K = 133.3 y el punto de
// fuga en YV = -82.7, los aros (d = 0) quedan en y = 184 con el ancho completo (160 px) y lo más lejano
// que se ve (d = VIEW_DEPTH = 200) en y = 24, con el 40% del ancho. VIEW_DEPTH es lo mismo que se veía
// en la autopista plana, así que las notas se ven venir con la misma anticipación.
//
// Las cuentas van multiplicadas por 3 para que todo sea entero: 3 * YV = -248, 3 * (HIT_Y - YV) = 800,
// 3 * K = 400.

#include "genband.h"

#define YV3     (-248)
#define SPAN3   800
#define K3      400

s16 line_depth[SCREEN_LINES + 1];
u16 line_scale[SCREEN_LINES + 1];
u8 depth_y[DEPTH_MAX - DEPTH_MIN + 1];
u16 depth_scale[DEPTH_MAX - DEPTH_MIN + 1];
u16 trap_map[STRIP_ROW][40];

// --- Interrupciones -------------------------------------------------------------------------------
//
// En cada cuadro, durante la vblank (cuando SGDK ya vació la cola de DMA), se calcula la tabla con el
// scroll de cada línea y se deja la VDP apuntando a la VSRAM del plano A con autoincremento 0. Así la
// interrupción de cada línea (hint.s) solo copia un valor: llega a tiempo, antes de que el VDP empiece
// a dibujar la autopista. Mientras se juega nadie más escribe en el VDP fuera de la vblank (todo va por la
// cola de DMA), así que esa dirección no se pierde. Si un cuadro se atrasa y la cola se vacía con la
// pantalla ya dibujándose, las interrupciones de ese cuadro no hacen nada (se ve sin perspectiva un
// cuadro, pero no se corrompe nada).

static s16 line_offset[SCREEN_LINES + 1];   // lo que se resta al scroll en cada línea: profundidad + línea + 1
static s16 scroll_table[SCREEN_LINES + 1];
static vs16 next_base;          // -wy(now) del siguiente cuadro (lo pone el juego)
extern u32 hint_src;            // (hint.s) la dirección del siguiente valor, dentro de la instrucción que lo copia
extern void hint_handler(void);
extern void hint_idle(void);    // la interrupción sin efecto

#define VDP_CTRL_L (*(vu32 *) VDP_CTRL_PORT)
#define VDP_DATA_W (*(vu16 *) VDP_DATA_PORT)
#define VSRAM_WRITE_0 0x40000010

static void vint(void)
{
    SYS_setHIntCallback(hint_idle);     // hasta que SGDK termine con la cola de DMA
}

static void vblank_done(void)
{
    const s16 base = next_base;
    for (u16 line = 0; line <= SCREEN_LINES; line++) scroll_table[line] = base - line_offset[line];
    VDP_setAutoInc(0);
    VDP_CTRL_L = VSRAM_WRITE_0;
    VDP_DATA_W = scroll_table[0];
    hint_src = (u32) &scroll_table[1];
    SYS_setHIntCallback(hint_handler);
}

void perspective_set_scroll(u32 world_now)
{
    next_base = -(s16) world_now;
}

void perspective_start(void)
{
    SYS_disableInts();
    next_base = 0;
    hint_src = (u32) &scroll_table[1];
    SYS_setVIntCallback(vint);
    SYS_setVBlankCallback(vblank_done);
    SYS_setHIntCallback(hint_idle);
    VDP_setHIntCounter(0);
    VDP_setHInterrupt(TRUE);
    SYS_enableInts();
}

void perspective_stop(void)
{
    // Primero se deja la interrupción sin efecto y se espera a la vblank; ya ahí (sin nada que compita
    // por el VDP) se apaga y se devuelve el autoincremento de siempre
    SYS_disableInts();
    SYS_setHIntCallback(hint_idle);
    SYS_setVIntCallback(NULL);
    SYS_setVBlankCallback(NULL);
    SYS_enableInts();
    SYS_doVBlankProcess();
    SYS_disableInts();
    VDP_setHInterrupt(FALSE);
    SYS_setHIntCallback(NULL);
    VDP_setAutoInc(2);          // lo normal: el resto del juego escribe en el VDP con la CPU
    VDP_setVerticalScroll(BG_A, 0);
    SYS_enableInts();
}

// --- Tablas y trapecio ----------------------------------------------------------------------------

// El trapecio de cada combinación de autopistas se dibuja en Python (graficos.py, `genband build-gfx`) y
// llega en trap_gfx.c: sus tiles distintos (las orillas y las líneas de los carriles) y un mapa. Afuera
// queda el escenario (el color 3, que stage.c cubre con su dibujo) y adentro el color de fondo, que es el
// de la autopista.

static const TrapLayout *trap_now;      // el que está en la VRAM

static bool layout_is(const TrapLayout *l, u16 count, const Highway *highways)
{
    if (l->count != count) return FALSE;
    for (u16 i = 0; i < count; i++)
        if (l->highways[i].cx != highways[i].cx || l->highways[i].lanes != highways[i].lanes
            || l->highways[i].lane_w != highways[i].lane_w)
            return FALSE;
    return TRUE;
}

void perspective_build(u16 count, const Highway *highways)
{
    const TrapLayout *l = &trap_layouts[0];
    for (u16 i = 0; i < trap_layout_count; i++)
        if (layout_is(&trap_layouts[i], count, highways)) l = &trap_layouts[i];
    if (l == trap_now) return;
    trap_now = l;
    VDP_loadTileData(l->tiles, tile_trap, l->tile_count, CPU);
    const u16 out = TILE_ATTR_FULL(PAL0, 1, 0, 0, tile_solid + 3);
    const u16 inside = TILE_ATTR_FULL(PAL0, 1, 0, 0, 0);
    for (u16 row = 0; row < STRIP_ROW; row++)
        for (u16 col = 0; col < 40; col++)
        {
            const u8 v = l->map[row][col];
            trap_map[row][col] = v == 0 ? inside : (v == 1 ? out : TILE_ATTR_FULL(PAL0, 1, 0, 0, tile_trap + v - 2));
        }
}

void perspective_init(void)
{
    for (u16 line = 0; line <= SCREEN_LINES; line++)
    {
        const s32 y = max(line, HWY_TOP);
        // d = K * (1 / s - 1), con s = (y - YV) / (HIT_Y - YV)
        line_depth[line] = (s32) K3 * (SPAN3 - (3 * y - YV3)) / (3 * (3 * y - YV3));
        line_scale[line] = (u32) 256 * (3 * y - YV3) / SPAN3;
        line_offset[line] = line_depth[line] + line + 1;
    }
    for (s16 d = DEPTH_MIN; d <= DEPTH_MAX; d++)
    {
        const s32 den = K3 + 3 * d;
        depth_y[d - DEPTH_MIN] = ((s32) SPAN3 * K3 / den + YV3) / 3;
        depth_scale[d - DEPTH_MIN] = (s32) 256 * K3 / den;
    }
}
