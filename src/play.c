// El juego: la autopista, las notas, el juicio de cada botón y el marcador.
//
// Cómo se ve:
//   - Plano B: el escenario y el fondo de la autopista (5 carriles de 32 px, de x = 80 a 240). No se mueve.
//   - Plano A: lo que baja con la canción (líneas de tiempo y colas de las notas sostenidas). Usa el
//     scroll vertical por columnas del VDP: las 10 columnas de la autopista se desplazan y las de los
//     lados no, así que ahí van textos fijos (instrumento, medidor de vida).
//   - Sprites: las gemas (en su posición exacta, píxel por píxel), los aros y las llamaradas.
//   - Ventana: la franja fija de abajo (barra estelar, puntaje, combo). Tapa al plano A; debajo, en el
//     plano B, va su fondo oscuro.
//
// El tiempo es el cuadro de la canción (`now`, contando la entrada de la autopista). Cada cuadro la
// autopista baja `speed` píxeles (en 8.8; depende de la dificultad, como en NESBand). Una nota del
// cuadro f está a la altura del mundo wy(f) = f * speed, y se ve en y = HIT_Y - (wy(f) - wy(now)).
//
// Las notas del chart se leen poco antes de que entren a la pantalla y viven en una cola circular
// (`gems`) hasta que pasan; ahí se juzgan y de ahí se dibujan.

#include "genband.h"

#define HWY_X           80
#define HWY_COL         (HWY_X / 8)
#define LANE_W          32
#define HIT_Y           184             // centro de los aros
#define STRIP_ROW       24              // la ventana (franja fija) empieza en este renglón
#define HIT_WINDOW      6               // tolerancia: +-6 cuadros (~100 ms) para acertar
#define GEM_SLOTS       64              // notas leídas a la vez (potencia de 2)
#define MAX_SPRITES     80

#define FX_FRAMES       8               // llamarada al acertar (2 cuadros por dibujo)
#define HOLD_TICK       8               // mientras sostienes, cada 8 cuadros sumas 10 puntos
#define HOLD_POINTS     10
#define HOLD_LIFE       32              // y cada 32, un punto de vida

#define LIFE_MAX        48
#define LIFE_START      (LIFE_MAX * 2 / 3)
#define LIFE_HIT        1
#define LIFE_AIR        1
#define LIFE_STAR       6
#define LIFE_GRACE      8               // tras perder vida, 8 cuadros sin perder más
#define METER_COL       31
#define METER_ROW       15
#define METER_TILES     6

#define STAR_MAX        80
#define STAR_PHRASE     (STAR_MAX / 4)
#define STAR_MIN        (STAR_MAX / 2)
#define STAR_DRAIN      10              // cuadros por cada punto que se gasta (barra llena = ~13 s)
#define STARBAR_COL     15
#define STARBAR_TILES   10

#define RESULTS_DELAY   60              // cuadros entre el fin de la música y los resultados
#define FAIL_DELAY      150             // y entre perder y los resultados

// Velocidad de la autopista por dificultad: cuadros que tarda en bajar 8 píxeles (como en NESBand)
static const u16 frames_per_row[NUM_DIFFICULTIES] = { 6, 5, 4, 3 };
static const u16 life_penalty[NUM_DIFFICULTIES] = { 1, 2, 2, 2 };

// Botones de cada carril: con la cruz y B, C (control de 3 botones) o con X, Y, Z (de 6 botones)
static const u16 lane_buttons[NUM_LANES] = {
    BUTTON_LEFT | BUTTON_X, BUTTON_DOWN | BUTTON_Y, BUTTON_RIGHT | BUTTON_Z, BUTTON_B, BUTTON_C,
};
#define BUTTON_STAR_POWER BUTTON_A

typedef struct {
    u16 frame;
    u16 end;                    // cuadro en que termina la cola (0 = sin cola o aún sin leer su fin)
    u8 mask;                    // carriles
    u8 flags;                   // CHART_SUSTAIN, CHART_STAR
    u8 hit;                     // carriles acertados
    u8 missed;                  // carriles perdidos
} Gem;

static Gem gems[GEM_SLOTS];
static u16 gem_head, gem_tail;  // números de la nota más vieja y de la siguiente por leer (la casilla es & 63)
static u16 resolve;             // siguiente nota por resolver (para las frases estelares, en orden)

static const Song *song;
static const u8 *chart;
static u16 chart_frame;         // cuadro de la última entrada leída
static bool chart_done;

static u16 now;
static u16 speed;               // 8.8: píxeles por cuadro
static u16 next_row;            // siguiente renglón del mundo por dibujar en el plano A
static u16 beat_index;          // siguiente línea de tiempo por dibujar
static u16 beat_zero;           // cuadro de la primera línea de tiempo (antes del primer tiempo, si cabe)
static u16 bar_phase;           // cuántos tiempos hay de beat_zero al primer tiempo, módulo 4

static u32 score, star_score, perfect;
static u16 combo, max_combo, multiplier, notes_hit;
static u16 life, grace;
static bool failed;
static u16 fail_timer;
static u16 star_energy, star_drain;
static bool star_active;
static bool phrase_active, phrase_ok, phrase_pending;
static u8 hold_lanes;
static u16 hold_end[NUM_LANES];
static u16 hold_timer;
static u8 fx[NUM_LANES];
static u16 channels;            // canales del instrumento (se callan al fallar)
static bool muted;
static bool paused;

static u16 hud_dirty;
#define HUD_SCORE 1
#define HUD_COMBO 2
#define HUD_STAR  4
#define HUD_LIFE  8

static u16 row_buf[NUM_LANES * 4];
static s16 vscroll[20];

static inline Gem *gem(u16 n)
{
    return &gems[n & (GEM_SLOTS - 1)];
}

static inline u32 wy(u16 frame)
{
    return ((u32) frame * speed) >> 8;
}

// --- Leer el chart ---------------------------------------------------------------------------------

static void phrase_finish(void)
{
    if (phrase_ok)
    {
        star_energy = min(STAR_MAX, star_energy + STAR_PHRASE);
        life = min(LIFE_MAX, life + LIFE_STAR);
        hud_dirty |= HUD_STAR | HUD_LIFE;
    }
    phrase_active = FALSE;
}

static void decode(void)
{
    const u32 limit = wy(now) + HIT_Y + 24;
    while (!chart_done && gem_tail - gem_head < GEM_SLOTS)
    {
        const u16 frame = chart_frame + chart[0];
        if (wy(frame) > limit) break;
        const u8 mask = chart[1];
        chart += 2;
        chart_frame = frame;
        if (mask == CHART_END)
        {
            chart_done = TRUE;
            if (phrase_pending) phrase_finish();
            phrase_pending = FALSE;
        }
        else if (mask & CHART_RELEASE)
        {
            // El fin de una cola: es de la nota más reciente con cola en esos carriles
            for (u16 n = gem_tail; n != gem_head;)
            {
                Gem *g = gem(--n);
                if ((g->flags & CHART_SUSTAIN) && !g->end && (g->mask & mask & CHART_LANES))
                {
                    g->end = frame;
                    break;
                }
            }
        }
        else if (mask & CHART_LANES)
        {
            Gem *g = gem(gem_tail++);
            g->frame = frame;
            g->end = 0;
            g->mask = mask & CHART_LANES;
            g->flags = mask & (CHART_SUSTAIN | CHART_STAR);
            g->hit = g->missed = 0;
            if (phrase_pending)
            {
                if (!(g->flags & CHART_STAR)) phrase_finish();
                phrase_pending = FALSE;
            }
        }
        // (carriles = 0: relleno que solo hace avanzar el tiempo)
    }
}

// Las notas ya juzgadas, en orden: de aquí salen las frases estelares (4 notas seguidas con la marca
// CHART_STAR; si aciertas todas, la barra sube 25%). La frase termina donde la siguiente nota no es estelar.
static void resolve_gems(void)
{
    while (resolve != gem_tail)
    {
        Gem *g = gem(resolve);
        if ((g->hit | g->missed) != g->mask) break;
        resolve++;
        if (!(g->flags & CHART_STAR)) continue;
        if (!phrase_active)
        {
            phrase_active = TRUE;
            phrase_ok = TRUE;
        }
        if (g->missed) phrase_ok = FALSE;
        if (resolve != gem_tail)
        {
            if (!(gem(resolve)->flags & CHART_STAR)) phrase_finish();
        }
        else if (chart_done)
            phrase_finish();
        else
            phrase_pending = TRUE;      // la siguiente nota aún no se lee: se decide al leerla
    }
    // Se olvidan las notas que ya pasaron la pantalla (y su cola)
    while (gem_head != resolve)
    {
        Gem *g = gem(gem_head);
        const u16 last = (g->flags & CHART_SUSTAIN) ? g->end : g->frame;
        if ((g->flags & CHART_SUSTAIN) && !g->end) break;
        if (wy(now) - wy(last) < (224 - HIT_Y) + 16 || last > now) break;
        gem_head++;
    }
}

// --- Puntaje, vida y silencio ----------------------------------------------------------------------

static void set_muted(bool m)
{
    if (failed) m = TRUE;
    if (m == muted) return;
    muted = m;
    music_mute(channels, m);
}

static void lose_life(u16 amount)
{
    if (sel.no_fail || failed || grace) return;
    grace = LIFE_GRACE;
    life = (life > amount) ? life - amount : 0;
    hud_dirty |= HUD_LIFE;
    if (!life)
    {
        failed = TRUE;
        fail_timer = FAIL_DELAY;
        set_muted(TRUE);
        draw_text(WINDOW, "        FALLASTE        ", 8, 27, PAL3);
    }
}

static void break_combo(void)
{
    if (combo || multiplier != 1) hud_dirty |= HUD_COMBO | HUD_SCORE;
    combo = 0;
    multiplier = 1;
}

static void miss(u16 lanes_missed)
{
    (void) lanes_missed;
    break_combo();
    set_muted(TRUE);
    lose_life(life_penalty[sel.difficulty]);
}

static void air_hit(void)
{
    break_combo();
    set_muted(TRUE);
    lose_life(LIFE_AIR);
}

static void hit(Gem *g, u16 lane)
{
    g->hit |= 1 << lane;
    notes_hit++;
    combo++;
    if (combo > max_combo) max_combo = combo;
    multiplier = min(4, 1 + combo / 10);
    star_score += 50 * multiplier;
    score += 50 * multiplier * (star_active ? 2 : 1);
    if (!failed) life = min(LIFE_MAX, life + LIFE_HIT);
    set_muted(FALSE);
    fx[lane] = FX_FRAMES;
    if ((g->flags & CHART_SUSTAIN) && (!g->end || g->end > now))
    {
        hold_lanes |= 1 << lane;
        hold_end[lane] = g->end ? g->end : 0xFFFF;
    }
    hud_dirty |= HUD_SCORE | HUD_COMBO | HUD_LIFE;
}

static void judge(void)
{
    // Botones presionados: cada uno acierta la nota más vieja de su carril que esté a tiempo
    for (u16 lane = 0; lane < NUM_LANES; lane++)
    {
        if (!(joy_pressed & lane_buttons[lane])) continue;
        Gem *found = NULL;
        for (u16 n = gem_head; n != gem_tail; n++)
        {
            Gem *g = gem(n);
            if (g->frame > now + HIT_WINDOW) break;
            const u8 open = g->mask & ~(g->hit | g->missed);
            if ((open & (1 << lane)) && g->frame + HIT_WINDOW >= now)
            {
                found = g;
                break;
            }
        }
        if (found) hit(found, lane);
        else if (!failed) air_hit();
    }

    // Notas que pasaron sin tocarlas
    for (u16 n = gem_head; n != gem_tail; n++)
    {
        Gem *g = gem(n);
        if (g->frame + HIT_WINDOW >= now) break;
        const u8 open = g->mask & ~(g->hit | g->missed);
        if (open)
        {
            g->missed |= open;
            if (!failed) miss(open);
        }
    }

    // Notas sostenidas: mientras el botón siga presionado, suman
    for (u16 lane = 0; lane < NUM_LANES; lane++)
        if (((hold_lanes >> lane) & 1) && (!(joy_held & lane_buttons[lane]) || now >= hold_end[lane]))
            hold_lanes &= ~(1 << lane);
    if (hold_lanes && !failed)
    {
        hold_timer++;
        if (hold_timer % HOLD_TICK == 0)
        {
            score += HOLD_POINTS;
            hud_dirty |= HUD_SCORE;
        }
        if (hold_timer % HOLD_LIFE == 0)
        {
            life = min(LIFE_MAX, life + 1);
            hud_dirty |= HUD_LIFE;
        }
    }
    else
        hold_timer = 0;

    // Poder estelar
    if ((joy_pressed & BUTTON_STAR_POWER) && !star_active && star_energy >= STAR_MIN && !failed)
    {
        star_active = TRUE;
        star_drain = 0;
        PAL_setColor(1, RGB24_TO_VDPCOLOR(0x101878));
        hud_dirty |= HUD_STAR;
    }
    if (star_active && ++star_drain >= STAR_DRAIN)
    {
        star_drain = 0;
        if (star_energy) star_energy--;
        if (!star_energy)
        {
            star_active = FALSE;
            PAL_setColor(1, RGB24_TO_VDPCOLOR(0x080838));
        }
        hud_dirty |= HUD_STAR;
    }

    if (grace) grace--;
}

// --- Dibujo ----------------------------------------------------------------------------------------

// Un renglón del mundo (8 píxeles de alto) del plano A: líneas de tiempo y colas
static void build_row(u16 k)
{
    const u32 top = (u32) k * 8;            // el renglón cubre wy de top a top + 7

    // Línea de tiempo que cae en este renglón, si hay
    u16 line = 0, line_row = 0;
    for (;;)
    {
        const u16 frame = beat_zero + beat_index * song->beat_frames;
        if (frame >= song->end_frame) break;
        const u32 y = wy(frame);
        if (y < top)
        {
            beat_index++;
            continue;
        }
        if (y < top + 8)
        {
            line = ((beat_index + 4 - bar_phase) % 4 == 0) ? 2 : 1;
            line_row = 7 - (y - top);
        }
        break;
    }

    // Colas que pasan por este renglón
    u8 tails = 0;
    for (u16 n = gem_head; n != gem_tail; n++)
    {
        Gem *g = gem(n);
        if (!(g->flags & CHART_SUSTAIN)) continue;
        const u32 start = wy(g->frame);
        if (start >= top + 8) break;
        if (!g->end || wy(g->end) >= top) tails |= g->mask;
    }

    for (u16 lane = 0; lane < NUM_LANES; lane++)
        for (u16 col = 0; col < 4; col++)
        {
            const u16 t = scroll_tile(lane, col, (tails >> lane) & 1, line, line_row);
            row_buf[lane * 4 + col] = t ? TILE_ATTR_FULL(PAL1, 0, 0, 0, t) : 0;
        }
    VDP_setTileMapDataRow(BG_A, row_buf, (-(s16) k - 1) & 31, HWY_COL, NUM_LANES * 4, DMA_QUEUE_COPY);
}

static void scroll_highway(void)
{
    const u32 world_now = wy(now);
    while ((u32) next_row * 8 <= world_now + HIT_Y + 8)
        build_row(next_row++);
    const s16 v = (-1 - HIT_Y - (s32) world_now) & 0x3FF;
    for (u16 c = HWY_COL / 2; c < HWY_COL / 2 + NUM_LANES * 2; c++) vscroll[c] = v;
    VDP_setVerticalScrollTile(BG_A, 0, vscroll, 20, DMA_QUEUE);
}

static bool phrase_failed_at(u16 n)
{
    // Una gema estelar se ve normal si su frase ya se perdió (como en Rock Band)
    return phrase_active && !phrase_ok && n >= resolve;
}

static u16 sprites;

static void sprite(s16 x, s16 y, u16 attr)
{
    if (sprites >= MAX_SPRITES) return;
    VDP_setSpriteFull(sprites, x, y, SPRITE_SIZE(4, 2), attr, sprites + 1);
    sprites++;
}

static void draw_sprites(void)
{
    sprites = 0;
    // Llamaradas (encima de todo)
    for (u16 lane = 0; lane < NUM_LANES; lane++)
    {
        u16 frame;
        if (fx[lane])
        {
            frame = (FX_FRAMES - fx[lane]) / 2;
            fx[lane]--;
        }
        else if ((hold_lanes >> lane) & 1)
            frame = (now >> 2) & 1;     // mientras sostienes, la llama alta parpadea
        else
            continue;
        sprite(HWY_X + lane * LANE_W, HIT_Y - 16,
               TILE_ATTR_FULL(star_active ? PAL3 : PAL2, 1, 0, 0, tile_flame + frame * 8));
    }
    // Gemas
    const u32 world_now = wy(now);
    for (u16 n = gem_head; n != gem_tail; n++)
    {
        Gem *g = gem(n);
        const u8 visible = g->mask & ~g->hit;
        if (!visible) continue;
        const s32 y = HIT_Y - ((s32) wy(g->frame) - (s32) world_now) - 8;
        if (y > 224 - 40) continue;     // ya pasó (la franja de abajo la taparía de todos modos)
        if (y < -16) break;
        const u16 base = (g->flags & CHART_STAR) && !phrase_failed_at(n) ? tile_star_gem : tile_gem;
        for (u16 lane = 0; lane < NUM_LANES; lane++)
            if ((visible >> lane) & 1)
                sprite(HWY_X + lane * LANE_W, y, TILE_ATTR_FULL(PAL1, 0, 0, 0, base + lane * 8));
    }
    // Aros
    for (u16 lane = 0; lane < NUM_LANES; lane++)
    {
        const bool on = joy_held & lane_buttons[lane];
        sprite(HWY_X + lane * LANE_W, HIT_Y - 8,
               TILE_ATTR_FULL(PAL1, 0, 0, 0, (on ? tile_ring_on : tile_ring) + lane * 8));
    }
    VDP_setSpriteLink(sprites - 1, 0);
    VDP_updateSprites(sprites, DMA_QUEUE);
}

static void draw_hud(void)
{
    if (hud_dirty & HUD_SCORE)
        draw_number(WINDOW, score, 7, 23, 25, PAL0);
    if (hud_dirty & HUD_COMBO)
    {
        draw_number(WINDOW, combo, 4, 23, 26, PAL0);
        char m[3] = { 'X', '0' + multiplier, 0 };
        draw_text(WINDOW, m, 28, 26, multiplier > 1 ? PAL2 : PAL0);
    }
    if (hud_dirty & HUD_STAR)
    {
        for (u16 i = 0; i < STARBAR_TILES; i++)
        {
            const s16 fill = (s16) star_energy - i * 8;
            const u16 level = fill <= 0 ? 0 : (fill >= 8 ? 8 : fill);
            VDP_setTileMapXY(WINDOW, TILE_ATTR_FULL(PAL3, 1, 0, 0, tile_starbar + (star_active ? 9 : 0) + level),
                             STARBAR_COL + i, STRIP_ROW);
        }
    }
    if ((hud_dirty & HUD_LIFE) && !sel.no_fail)
    {
        const u16 color = life < LIFE_MAX / 4 ? 2 : (life < LIFE_MAX * 5 / 8 ? 1 : 0);
        for (u16 i = 0; i < METER_TILES; i++)
        {
            const s16 fill = (s16) life - (METER_TILES - 1 - i) * 8;
            const u16 level = fill <= 0 ? 0 : (fill >= 8 ? 8 : fill);
            VDP_setTileMapXY(BG_A, TILE_ATTR_FULL(PAL3, 1, 0, 0, tile_meter + color * 9 + level),
                             METER_COL, METER_ROW + i);
        }
    }
    hud_dirty = 0;
}

// --- Escenario -------------------------------------------------------------------------------------

static void draw_stage(void)
{
    // Fondo del escenario y la autopista
    VDP_fillTileMapRect(BG_B, TILE_ATTR_FULL(PAL0, 0, 0, 0, tile_solid + 3), 0, 0, 40, 28);
    for (u16 lane = 0; lane < NUM_LANES; lane++)
    {
        VDP_fillTileMapRect(BG_B, TILE_ATTR_FULL(PAL0, 0, 0, 0, tile_hwy + 1), HWY_COL + lane * 4, 0, 1, STRIP_ROW);
        VDP_fillTileMapRect(BG_B, TILE_ATTR_FULL(PAL0, 0, 0, 0, tile_hwy), HWY_COL + lane * 4 + 1, 0, 3, STRIP_ROW);
    }
    VDP_fillTileMapRect(BG_B, TILE_ATTR_FULL(PAL0, 0, 0, 0, tile_hwy + 2), HWY_COL + NUM_LANES * 4, 0, 1, STRIP_ROW);
    // Bocinas a los lados: cajas oscuras con dos conos
    for (u16 side = 0; side < 2; side++)
    {
        const u16 x = side ? 35 : 1;
        VDP_fillTileMapRect(BG_B, TILE_ATTR_FULL(PAL0, 0, 0, 0, tile_solid + 11), x, 13, 4, 11);
        VDP_fillTileMapRect(BG_B, TILE_ATTR_FULL(PAL0, 0, 0, 0, tile_solid + 9), x + 1, 14, 2, 3);
        VDP_fillTileMapRect(BG_B, TILE_ATTR_FULL(PAL0, 0, 0, 0, tile_solid + 10), x + 1, 15, 2, 1);
        VDP_fillTileMapRect(BG_B, TILE_ATTR_FULL(PAL0, 0, 0, 0, tile_solid + 9), x + 1, 19, 2, 3);
        VDP_fillTileMapRect(BG_B, TILE_ATTR_FULL(PAL0, 0, 0, 0, tile_solid + 10), x + 1, 20, 2, 1);
        // Un haz de luz desde arriba
        for (u16 y = 0; y < 10; y++)
            VDP_fillTileMapRect(BG_B, TILE_ATTR_FULL(PAL0, 0, 0, 0, tile_solid + 4), side ? x - y / 4 : x + 1 + y / 4, y, 2, 1);
    }
    // La franja fija de abajo: su fondo en el plano B (con prioridad, para tapar las gemas que ya pasaron)
    // y los textos en la ventana
    VDP_fillTileMapRect(BG_B, TILE_ATTR_FULL(PAL0, 1, 0, 0, tile_solid + 11), 0, STRIP_ROW, 40, 4);
    draw_text(WINDOW, "PUNTOS", 14, 25, PAL1);
    draw_text(WINDOW, "COMBO", 14, 26, PAL1);
    draw_text_center(WINDOW, song->title, 27, PAL1);
    // Los lados (plano A, columnas sin scroll)
    draw_text(BG_A, instrument_names[sel.instrument], 1, 2, PAL0);
    draw_text(BG_A, difficulty_names[sel.difficulty], 1, 3, PAL1);
    if (!sel.no_fail) draw_text(BG_A, "VIDA", METER_COL, METER_ROW - 1, PAL1);
}

// --- Pausa -----------------------------------------------------------------------------------------

// Devuelve TRUE si hay que salir al menú
static bool pause_loop(void)
{
    music_pause(TRUE);
    draw_text(WINDOW, "PAUSA: START SIGUE, B SALE", 7, 27, PAL2);
    for (;;)
    {
        wait_frame();
        input_update();
        if (joy_pressed & BUTTON_START) break;
        if (joy_pressed & BUTTON_B)
        {
            music_stop();
            return TRUE;
        }
    }
    VDP_clearTextLineBG(WINDOW, 27);
    draw_text_center(WINDOW, song->title, 27, PAL1);
    music_pause(FALSE);
    return FALSE;
}

// --- Partida ---------------------------------------------------------------------------------------

// Puntaje de acertar todas las notas sin fallar (sin poder estelar ni colas): la nota número i vale
// 50 por su multiplicador (1-9 x1, 10-19 x2, 20-29 x3, desde la 30 x4)
static u32 perfect_score(u16 notes)
{
    u32 total = 0;
    for (u16 i = 1; i <= notes; i++) total += 50 * min(4, 1 + i / 10);
    return total;
}

static void start(void)
{
    song = song_list[sel.song];
    chart = song->charts[sel.instrument][sel.difficulty];
    chart_frame = 0;
    chart_done = FALSE;
    gem_head = gem_tail = resolve = 0;
    now = 0;
    speed = (8 << 8) / frames_per_row[sel.difficulty];
    next_row = 0;
    beat_zero = song->first_beat % song->beat_frames;
    bar_phase = ((song->first_beat - beat_zero) / song->beat_frames) % 4;
    beat_index = 0;
    score = star_score = 0;
    perfect = perfect_score(song->notes[sel.instrument][sel.difficulty]);
    combo = max_combo = notes_hit = 0;
    multiplier = 1;
    life = LIFE_START;
    grace = 0;
    failed = FALSE;
    star_energy = star_drain = 0;
    star_active = FALSE;
    phrase_active = phrase_ok = phrase_pending = FALSE;
    hold_lanes = 0;
    hold_timer = 0;
    memset(fx, 0, sizeof(fx));
    channels = song->channels[sel.instrument];
    muted = FALSE;
    paused = FALSE;
    memset(vscroll, 0, sizeof(vscroll));
    hud_dirty = HUD_SCORE | HUD_COMBO | HUD_STAR | HUD_LIFE;
}

static void finish(void)
{
    result.score = score;
    result.perfect = perfect;
    result.notes_hit = notes_hit;
    result.notes_total = song->notes[sel.instrument][sel.difficulty];
    result.max_combo = max_combo;
    result.failed = failed;
    result.percent = result.notes_total ? (u32) notes_hit * 100 / result.notes_total : 0;
    static const u16 thresholds[5] = { 20, 40, 60, 80, 95 };
    const u32 pct = perfect ? star_score * 100 / perfect : 0;
    result.stars = 0;
    while (result.stars < 5 && pct >= thresholds[result.stars]) result.stars++;
    if (failed) result.stars = 0;
}

Screen play_run(void)
{
    screen_reset();
    start();
    VDP_setEnable(FALSE);
    VDP_setScrollingMode(HSCROLL_PLANE, VSCROLL_COLUMN);
    VDP_setWindowVPos(TRUE, STRIP_ROW);
    draw_stage();
    VDP_setEnable(TRUE);

    for (;;)
    {
        input_update();
        if (joy_pressed & BUTTON_START)
        {
            if (pause_loop()) return SCREEN_MENU;
            input_update();
        }

        if (now == SONG_LEAD_IN) music_play(song->stream, MUSIC_NO_LOOP);
        music_update();

        decode();
        judge();
        resolve_gems();
        scroll_highway();
        draw_sprites();
        draw_hud();

        if (failed && !--fail_timer) break;
        if (now >= song->end_frame + RESULTS_DELAY) break;
        now++;
        wait_frame();
    }
    music_stop();
    finish();
    return SCREEN_RESULTS;
}
