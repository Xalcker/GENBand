// El juego: la autopista, las notas, el juicio de cada botón y el marcador, para 1 o 2 jugadores.
//
// Cómo se ve (la autopista va en perspectiva: ver perspective.c):
//   - Plano B: el escenario, el fondo de la(s) autopista(s) en trapecio y los textos de los lados. No se mueve.
//   - Plano A: las líneas de tiempo (y el bombo de la batería), que bajan con la canción. La interrupción de
//     cada línea elige qué renglón del mundo se ve en cada línea de pantalla.
//   - Sprites: las gemas (del tamaño que toca a su distancia), las colas, los aros y las llamaradas.
//   - Ventana: la franja fija de abajo (barra estelar, puntaje, combo).
//
// El tiempo es el cuadro de la canción (`now`, contando la entrada de la autopista). Cada cuadro la
// autopista avanza `speed` píxeles del mundo (en 8.8; depende de la dificultad, como en NESBand). Una
// nota del cuadro f está a la distancia del mundo wy(f) = f * speed, y a la profundidad
// d = wy(f) - wy(now) por delante de los aros; las tablas de perspective.c dicen dónde se ve y de qué tamaño.
//
// Dos jugadores (como en NESBand): las dos autopistas comparten el scroll (y la velocidad: la de la
// dificultad más alta de los dos). Cada jugador tiene su chart, sus notas, su vida y su control (Player).
// El puntaje, el combo y el poder estelar (Score) son de cada quien en VS y de la banda en Co-Op.
//
// Mientras se juega no se escribe directo en el VDP (textos, paleta): todo va por la cola de DMA, porque
// la interrupción de cada línea también le escribe.
//
// Las notas del chart se leen poco antes de que entren a la pantalla y viven en una cola circular por
// jugador (`gems`) hasta que pasan; ahí se juzgan y de ahí se dibujan.

#include "genband.h"

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
#define LIFE_REVIVE     (LIFE_MAX / 2)  // vida con la que vuelve un compañero revivido (Co-Op)
#define METER_TILES     6

#define STAR_MAX        80
#define STAR_PHRASE     (STAR_MAX / 4)
#define STAR_MIN        (STAR_MAX / 2)  // se puede activar (o revivir a un compañero) con la mitad
#define STAR_DRAIN      10              // cuadros por cada punto que se gasta (barra llena = ~13 s)
#define STARBAR_TILES   10

#define MISS_FX_FRAMES   6              // cuadros con temblor y rojo al rasguear en falso
#define MISS_FX_COOLDOWN 14             // y cuadros después sin repetirlo (6 + 14 = 20: 3 por segundo)
#define MISS_SOUNDS      3              // clank, thud y bwomp

#define PRACTICE_GRACE  60              // práctica desde un punto: las notas de los primeros cuadros se omiten
#define PRACTICE_BACK   120             // marca de inicio (A en la pausa): 2 s antes de donde pausaste
#define PRACTICE_MIN    240             // el bucle marcado debe durar al menos 4 s

#define RESULTS_DELAY   60              // cuadros entre el fin de la música y los resultados
#define FAIL_DELAY      150             // y entre perder y los resultados

// Velocidad de la autopista por dificultad: cuadros que tarda en bajar 8 píxeles (como en NESBand)
static const u16 frames_per_row[NUM_DIFFICULTIES] = { 6, 5, 4, 3 };
static const u16 life_penalty[NUM_DIFFICULTIES] = { 1, 2, 2, 2 };

// VELOCIDAD: pasos del juego cada 4 cuadros (100%, 75%, 50%, 125%). La canción, las notas y la música
// avanzan por pasos; la autopista se dibuja con la fracción de paso, así que se ve pareja
static const u16 speed_steps[4] = { 4, 3, 2, 5 };

// Botones de cada carril: con la cruz y B, C (control de 3 botones) o con X, Y, Z (de 6 botones)
static const u16 lane_buttons[NUM_LANES] = {
    BUTTON_LEFT | BUTTON_X, BUTTON_DOWN | BUTTON_Y, BUTTON_RIGHT | BUTTON_Z, BUTTON_B, BUTTON_C,
};
#define BUTTON_STAR_POWER BUTTON_A

typedef struct {
    u16 frame;
    u16 end;                    // cuadro en que termina la cola (0 = sin cola o aún sin leer su fin)
    u8 mask;                    // carriles
    u8 flags;                   // CHART_SUSTAIN, CHART_STAR, GEM_CYMBAL
    u8 hit;                     // carriles acertados
    u8 missed;                  // carriles perdidos
} Gem;

#define GEM_CYMBAL 0x80          // batería: el pad es un platillo (en el chart es el bit de la cola, $40)
#define KICK       4             // batería: el bombo es el carril naranja

#define HUD_SCORE 1
#define HUD_COMBO 2
#define HUD_STAR  4
#define HUD_LIFE  8

// Puntaje, combo y poder estelar: de cada jugador, o de la banda en Co-Op
typedef struct {
    u32 score, star_score, perfect;
    u16 combo, max_combo, multiplier;
    u16 star_energy, star_drain;
    bool star_active;
    u16 hud_dirty;              // HUD_SCORE, HUD_COMBO, HUD_STAR
    u16 hud_x;                  // columna de la ventana donde va su marcador
} Score;

typedef struct {
    Gem gems[GEM_SLOTS];        // (primero, con gem_head y gem_tail detrás: los leen las pruebas)
    u16 gem_head, gem_tail;     // números de la nota más vieja y de la siguiente por leer (la casilla es & 63)
    u16 resolve;                // siguiente nota por resolver (para las frases estelares, en orden)
    const u8 *chart;
    u16 chart_frame;            // cuadro de la última entrada leída
    bool chart_done;
    u16 instrument, difficulty;
    // Geometría de su autopista: 5 carriles de 32 px, o en la batería 4 columnas de 40 px en el orden de
    // Rock Band (rojo, amarillo, azul, verde) y el bombo como una barra que las cruza
    bool drums;
    u16 cols, col_w;
    s16 cx;                     // centro de su autopista
    u16 plane_col;              // primera columna de tiles de su autopista en el plano A (20 de ancho)
    u8 lane_col[NUM_LANES];     // la columna de cada carril (el bombo no tiene)
    u16 notes_hit;
    u16 life, grace;
    bool failed;
    bool phrase_active, phrase_ok, phrase_pending;
    u8 hold_lanes;
    u16 hold_end[NUM_LANES];
    Gem *hold_gem[NUM_LANES];
    u16 hold_timer;
    u8 fx[NUM_LANES];           // llamaradas, por columna
    u16 channels;               // canales del instrumento (se callan al fallar)
    bool muted;
    u16 hud_dirty;              // HUD_LIFE
    u16 meter_col, meter_row;   // el medidor de vida
    u16 pad;                    // su control (con un jugador, los dos)
    u16 pressed;                // botones presionados desde el paso anterior (con VELOCIDAD, varios cuadros)
    Score *s;
} Player;

static Player players[MAX_PLAYERS];
const u16 player_size = sizeof(Player);     // (para las pruebas)
static Score scores[MAX_PLAYERS], band;
static u16 nplayers;
static bool coop;

static const u8 drum_cols[NUM_LANES] = { 3, 0, 1, 2, 0 };

static const Song *song;
static u16 now;                 // el paso de la canción (con VELOCIDAD al 100%, un cuadro)
static u16 step_frac;           // fracción del siguiente paso, en cuartos (VELOCIDAD)
static u32 view;                // dónde se dibuja: la distancia del mundo del último paso, más la fracción
static u16 speed;               // 8.8: píxeles por paso
static bool no_fail;            // SIN FALLO, o una práctica
static u16 fail_timer;          // cuadros que faltan para los resultados tras perder (0 = no se perdió)
static u16 skip_frame;          // práctica desde un punto: las notas anteriores a este cuadro no se tocan
static u16 practice_start, practice_end;
static u16 next_row;            // siguiente renglón del mundo por dibujar en el plano A
static u16 beat_zero;           // cuadro de la primera línea de tiempo (antes del primer tiempo, si cabe)
static u16 bar_phase;           // cuántos tiempos hay de beat_zero al primer tiempo, módulo 4
static u16 row_buf[40];
static u16 row_first, row_width;    // las columnas del plano A que ocupan las autopistas
static u16 hwy_color;           // color de la autopista (cambia con el poder estelar)
static u16 miss_fx;             // cuadros que le quedan al efecto de fallo (y a su enfriamiento)
static u16 miss_sound;          // el último sonido de fallo (0-2)
static s16 shake[2];            // scroll horizontal de los planos A y B (el temblor al fallar)

static void build_row(u16 k);

static inline Gem *gem(Player *p, u16 n)
{
    return &p->gems[n & (GEM_SLOTS - 1)];
}

static inline u32 wy(u16 frame)
{
    return ((u32) frame * speed) >> 8;
}

static inline s16 col_x(const Player *p, u16 col, u16 scale)
{
    return p->cx + (((s32) (2 * col + 1 - p->cols) * (p->col_w / 2) * scale) >> 8);
}

static bool star_power_any(void)
{
    for (u16 i = 0; i < nplayers; i++)
        if (players[i].s->star_active) return TRUE;
    return FALSE;
}

static void set_highway_color(void)
{
    hwy_color = RGB24_TO_VDPCOLOR(star_power_any() ? 0x101878 : 0x080838);
    PAL_setColors(1, &hwy_color, 1, DMA_QUEUE);
}

// --- Leer el chart ---------------------------------------------------------------------------------

static void phrase_finish(Player *p)
{
    if (p->phrase_ok)
    {
        p->s->star_energy = min(STAR_MAX, p->s->star_energy + STAR_PHRASE);
        if (!p->failed) p->life = min(LIFE_MAX, p->life + LIFE_STAR);
        p->s->hud_dirty |= HUD_STAR;
        p->hud_dirty |= HUD_LIFE;
    }
    p->phrase_active = FALSE;
}

static void decode(Player *p)
{
    const u32 limit = wy(now) + VIEW_DEPTH + 24;
    while (!p->chart_done && p->gem_tail - p->gem_head < GEM_SLOTS)
    {
        const u16 frame = p->chart_frame + p->chart[0];
        if (wy(frame) > limit) break;
        u8 mask = p->chart[1];
        p->chart += 2;
        p->chart_frame = frame;
        if (sel.mirror && mask != CHART_END)    // ESPEJO: el verde con el naranja y el rojo con el azul
        {
            const u8 l = mask & CHART_LANES;
            mask = (mask & ~CHART_LANES) | ((l & 1) << 4) | ((l & 2) << 2) | (l & 4) | ((l & 8) >> 2) | ((l & 16) >> 4);
        }
        if (mask == CHART_END)
        {
            p->chart_done = TRUE;
            if (p->phrase_pending) phrase_finish(p);
            p->phrase_pending = FALSE;
        }
        else if (mask & CHART_RELEASE)
        {
            // El fin de una cola: es de la nota más reciente con cola en esos carriles
            for (u16 n = p->gem_tail; n != p->gem_head;)
            {
                Gem *g = gem(p, --n);
                if ((g->flags & CHART_SUSTAIN) && !g->end && (g->mask & mask & CHART_LANES))
                {
                    g->end = frame;
                    break;
                }
            }
        }
        else if ((mask & CHART_LANES) && frame >= skip_frame)
        {
            Gem *g = gem(p, p->gem_tail++);
            g->frame = frame;
            g->end = 0;
            g->mask = mask & CHART_LANES;
            g->flags = p->drums ? (mask & CHART_STAR) | ((mask & CHART_SUSTAIN) ? GEM_CYMBAL : 0)
                                : mask & (CHART_SUSTAIN | CHART_STAR);
            g->hit = g->missed = 0;
            if (p->phrase_pending)
            {
                if (!(g->flags & CHART_STAR)) phrase_finish(p);
                p->phrase_pending = FALSE;
            }
        }
        // (carriles = 0: relleno que solo hace avanzar el tiempo)
    }
}

// Las notas ya juzgadas, en orden: de aquí salen las frases estelares (4 notas seguidas con la marca
// CHART_STAR; si aciertas todas, la barra sube 25%). La frase termina donde la siguiente nota no es estelar.
static void resolve_gems(Player *p)
{
    while (p->resolve != p->gem_tail)
    {
        Gem *g = gem(p, p->resolve);
        if ((g->hit | g->missed) != g->mask) break;
        p->resolve++;
        if (!(g->flags & CHART_STAR)) continue;
        if (!p->phrase_active)
        {
            p->phrase_active = TRUE;
            p->phrase_ok = TRUE;
        }
        if (g->missed) p->phrase_ok = FALSE;
        if (p->resolve != p->gem_tail)
        {
            if (!(gem(p, p->resolve)->flags & CHART_STAR)) phrase_finish(p);
        }
        else if (p->chart_done)
            phrase_finish(p);
        else
            p->phrase_pending = TRUE;   // la siguiente nota aún no se lee: se decide al leerla
    }
    // Se olvidan las notas que ya pasaron la pantalla (y su cola)
    while (p->gem_head != p->resolve)
    {
        Gem *g = gem(p, p->gem_head);
        const u16 last = (g->flags & CHART_SUSTAIN) ? g->end : g->frame;
        if ((g->flags & CHART_SUSTAIN) && !g->end) break;
        if (wy(now) - wy(last) < (u32) -DEPTH_MIN || last > now) break;
        p->gem_head++;
    }
}

// --- Puntaje, vida y silencio ----------------------------------------------------------------------

// Los canales que se callan: los de los jugadores que están fallando (o perdieron). En VS los dos pueden
// tocar el mismo instrumento: su canal solo se calla cuando los dos están fallando.
static void apply_mutes(void)
{
    u16 off = 0, on = 0;
    for (u16 i = 0; i < nplayers; i++)
    {
        if (players[i].muted || players[i].failed) off |= players[i].channels;
        else on |= players[i].channels;
    }
    off &= ~on;
    music_mute(off, TRUE);
    music_mute(on, FALSE);
}

static void fail_text(const Player *p, const char *text)
{
    if (nplayers == 1)
        queue_text(WINDOW, "        FALLASTE        ", 8, 27, PAL3);
    else
        queue_text(WINDOW, text, p == &players[0] ? 1 : 30, 27, PAL3);
}

static void lose_life(Player *p, u16 amount)
{
    if (no_fail || p->failed || p->grace) return;
    p->grace = LIFE_GRACE;
    p->life = (p->life > amount) ? p->life - amount : 0;
    p->hud_dirty |= HUD_LIFE;
    if (!p->life)
    {
        p->failed = TRUE;
        p->muted = TRUE;
        fail_text(p, p == &players[0] ? "J1 FALLO" : "J2 FALLO");
    }
}

static void break_combo(Score *s)
{
    if (s->combo || s->multiplier != 1) s->hud_dirty |= HUD_COMBO | HUD_SCORE;
    s->combo = 0;
    s->multiplier = 1;
}

static void miss(Player *p)
{
    break_combo(p->s);
    p->muted = TRUE;
    lose_life(p, life_penalty[p->difficulty]);
}

// Rasgueaste en falso (un golpe al aire; una nota que se pasó sin tocarla solo calla el instrumento, como
// en Rock Band): suena uno de tres efectos, nunca el mismo dos veces seguidas y, con un jugador, la
// autopista tiembla y se tiñe de rojo unos cuadros (con dos se moverían las dos autopistas). Mientras dura
// el efecto y su enfriamiento no se repite: en una racha de fallos, a lo más 3 veces por segundo.
static void miss_feedback(void)
{
    if (miss_fx || sel.miss_fx == MISS_FX_OFF) return;
    miss_fx = MISS_FX_FRAMES + MISS_FX_COOLDOWN;
    miss_sound = (miss_sound + 1 + (now & 1)) % MISS_SOUNDS;
    sfx_play(SFX_CLANK + miss_sound);
}

// Un cuadro del efecto de fallo: temblor (scroll X) y la autopista roja; todo por la cola de DMA
static void update_miss_fx(void)
{
    static const s16 miss_shake[MISS_FX_FRAMES] = { 0, 1, 0, 2, 0, 2 };
    if (!miss_fx) return;
    miss_fx--;
    const bool visual = sel.miss_fx == MISS_FX_ALL && nplayers == 1;
    if (miss_fx >= MISS_FX_COOLDOWN && visual)
    {
        shake[0] = shake[1] = miss_shake[miss_fx - MISS_FX_COOLDOWN];
        hwy_color = RGB24_TO_VDPCOLOR(0x601010);
        PAL_setColors(1, &hwy_color, 1, DMA_QUEUE);
    }
    else if (miss_fx == MISS_FX_COOLDOWN - 1 && visual)
    {
        shake[0] = shake[1] = 0;
        set_highway_color();
    }
    else
        return;
    DMA_queueDma(DMA_VRAM, shake, VDP_getHScrollTableAddress(), 2, 2);
}

static void air_hit(Player *p)
{
    miss_feedback();
    break_combo(p->s);
    p->muted = TRUE;
    lose_life(p, LIFE_AIR);
}

static void hit(Player *p, Gem *g, u16 lane)
{
    Score *s = p->s;
    g->hit |= 1 << lane;
    p->notes_hit++;
    s->combo++;
    if (s->combo > s->max_combo) s->max_combo = s->combo;
    s->multiplier = min(4, 1 + s->combo / 10);
    s->star_score += 50 * s->multiplier;
    s->score += 50 * s->multiplier * (s->star_active ? 2 : 1);
    // Un acorde suma la vida de una sola nota aunque lleves dos botones (si no, se regalaría)
    if (!p->failed && !(g->hit & ~(1 << lane))) p->life = min(LIFE_MAX, p->life + LIFE_HIT);
    p->muted = FALSE;
    if (p->drums && lane == KICK)
    {
        for (u16 c = 0; c < p->cols; c++) p->fx[c] = FX_FRAMES;    // el bombo: llamarada en todas las columnas
        const u16 k = wy(g->frame) / 8;      // y su barra desaparece: se vuelve a armar su renglón
        if (k < next_row) build_row(k);
    }
    else
        p->fx[p->lane_col[lane]] = FX_FRAMES;
    if ((g->flags & CHART_SUSTAIN) && (!g->end || g->end > now))
    {
        p->hold_lanes |= 1 << lane;
        p->hold_end[lane] = g->end ? g->end : 0xFFFF;
        p->hold_gem[lane] = g;
    }
    s->hud_dirty |= HUD_SCORE | HUD_COMBO;
    p->hud_dirty |= HUD_LIFE;
}

// Co-Op: el compañero de p, si cayó (si no, NULL)
static Player *fallen_partner(const Player *p)
{
    if (!coop) return NULL;
    Player *other = &players[p == &players[0] ? 1 : 0];
    return other->failed ? other : NULL;
}

static void star_power(Player *p)
{
    Score *s = p->s;
    // Co-Op: si el compañero cayó, A lo revive con media barra (en vez de activar el poder)
    Player *partner = fallen_partner(p);
    if (partner && !p->failed && s->star_energy >= STAR_MIN)
    {
        partner->failed = FALSE;
        partner->muted = FALSE;
        partner->life = LIFE_REVIVE;
        partner->hud_dirty |= HUD_LIFE;
        s->star_energy -= STAR_MIN;
        s->hud_dirty |= HUD_STAR;
        queue_text(WINDOW, "        ", partner == &players[0] ? 1 : 30, 27, PAL3);
        sfx_play(SFX_ACEPTAR);
        return;
    }
    if (partner || s->star_active || s->star_energy < STAR_MIN || p->failed) return;
    s->star_active = TRUE;
    s->star_drain = 0;
    sfx_play(SFX_ACEPTAR);
    set_highway_color();
    s->hud_dirty |= HUD_STAR | HUD_SCORE;
}

static void judge(Player *p)
{
    const u16 held = pad_held[p->pad] | (nplayers == 1 ? pad_held[1] : 0);

    // Botones presionados: cada uno acierta la nota más vieja de su carril que esté a tiempo
    for (u16 lane = 0; lane < NUM_LANES; lane++)
    {
        if (!(p->pressed & lane_buttons[lane])) continue;
        Gem *found = NULL;
        for (u16 n = p->gem_head; n != p->gem_tail; n++)
        {
            Gem *g = gem(p, n);
            if (g->frame > now + HIT_WINDOW) break;
            const u8 open = g->mask & ~(g->hit | g->missed);
            if ((open & (1 << lane)) && g->frame + HIT_WINDOW >= now)
            {
                found = g;
                break;
            }
        }
        if (found) hit(p, found, lane);
        else if (!p->failed) air_hit(p);
    }

    // Notas que pasaron sin tocarlas
    for (u16 n = p->gem_head; n != p->gem_tail; n++)
    {
        Gem *g = gem(p, n);
        if (g->frame + HIT_WINDOW >= now) break;
        const u8 open = g->mask & ~(g->hit | g->missed);
        if (open)
        {
            g->missed |= open;
            if (!p->failed) miss(p);
        }
    }

    // Notas sostenidas: mientras el botón siga presionado, suman
    for (u16 lane = 0; lane < NUM_LANES; lane++)
        if (((p->hold_lanes >> lane) & 1) && (!(held & lane_buttons[lane]) || now >= p->hold_end[lane]))
            p->hold_lanes &= ~(1 << lane);
    if (p->hold_lanes && !p->failed)
    {
        p->hold_timer++;
        if (p->hold_timer % HOLD_TICK == 0)
        {
            p->s->score += HOLD_POINTS;
            p->s->hud_dirty |= HUD_SCORE;
        }
        if (p->hold_timer % HOLD_LIFE == 0)
        {
            p->life = min(LIFE_MAX, p->life + 1);
            p->hud_dirty |= HUD_LIFE;
        }
    }
    else
        p->hold_timer = 0;

    if (p->pressed & BUTTON_STAR_POWER) star_power(p);
    if (p->grace) p->grace--;
}

// El poder estelar se gasta (una vez por Score: en Co-Op, el de la banda)
static void drain_star(Score *s)
{
    if (!s->star_active || ++s->star_drain < STAR_DRAIN) return;
    s->star_drain = 0;
    if (s->star_energy) s->star_energy--;
    if (!s->star_energy)
    {
        s->star_active = FALSE;
        set_highway_color();
    }
    s->hud_dirty |= HUD_STAR;
}

// --- Dibujo ----------------------------------------------------------------------------------------

// La barra de un bombo (de un jugador con batería) que aún no se tocó y cae en el renglón k, si hay:
// devuelve su renglón dentro del tile, o -1
static s16 kick_in_row(Player *p, u32 top)
{
    if (!p->drums) return -1;
    for (u16 i = p->gem_head; i != p->gem_tail; i++)
    {
        const Gem *g = gem(p, i);
        if (!((g->mask >> KICK) & 1) || ((g->hit >> KICK) & 1)) continue;   // (uno fallado sigue de largo)
        const u32 y = wy(g->frame);
        if (y >= top + 8) break;
        if (y >= top) return min(7 - (y - top), 5);     // (la barra mide 4: que quede en su cuadro)
    }
    return -1;
}

// Un renglón del mundo (8 píxeles de alto) del plano A: la línea de tiempo que caiga en él, si hay, o la
// barra de un bombo de la batería (de cada jugador, en su autopista)
static void build_row(u16 k)
{
    const u32 top = (u32) k * 8;            // el renglón cubre wy de top a top + 7

    u16 line = 0, line_row = 0;
    // La primera línea de tiempo en o después de top (sin estado: el renglón se puede volver a armar)
    const u32 first = (top * 256 + speed - 1) / speed;
    const u16 n = first > beat_zero ? (first - beat_zero + song->beat_frames - 1) / song->beat_frames : 0;
    const u16 frame = beat_zero + n * song->beat_frames;
    if (frame < song->end_frame && wy(frame) < top + 8)
    {
        line = ((n + 4 - bar_phase) % 4 == 0) ? 2 : 1;
        line_row = 7 - (wy(frame) - top);
    }

    for (u16 i = 0; i < nplayers; i++)
    {
        Player *p = &players[i];
        const s16 kick = kick_in_row(p, top);
        const u16 t = kick >= 0 ? scroll_tile(3, kick) : scroll_tile(line, line_row);
        const u16 attr = t ? TILE_ATTR_FULL(PAL1, 0, 0, 0, t) : 0;
        for (u16 c = 0; c < 20; c++) row_buf[p->plane_col - row_first + c] = attr;
    }
    VDP_setTileMapDataRow(BG_A, row_buf, (-(s16) k - 1) & 31, row_first, row_width, DMA_QUEUE_COPY);
}

static void scroll_highway(void)
{
    while ((u32) next_row * 8 <= view + VIEW_DEPTH + 16)
        build_row(next_row++);
    perspective_set_scroll(view);
}

static bool phrase_failed_at(const Player *p, u16 n)
{
    // Una gema estelar se ve normal si su frase ya se perdió (como en Rock Band)
    return p->phrase_active && !p->phrase_ok && (u16) (n - p->resolve) < GEM_SLOTS;
}

static u16 sprites;

static void sprite(s16 x, s16 y, u8 size, u16 attr)
{
    if (sprites >= MAX_SPRITES) return;
    VDP_setSpriteFull(sprites, x, y, size, attr, sprites + 1);
    sprites++;
}

// Profundidad (píxeles del mundo por delante de los aros) del cuadro f
static inline s32 depth(u16 frame)
{
    return (s32) wy(frame) - (s32) view;
}

// La cola de una nota sostenida, de la profundidad d0 a la d1: sprites de 8x16 apilados, cada uno
// centrado en su carril y del ancho que toca a su altura
static void draw_tail(const Player *p, u16 lane, s32 d0, s32 d1)
{
    d0 = max(d0, DEPTH_MIN);
    d1 = min(d1, VIEW_DEPTH);
    if (d1 <= d0) return;
    s16 y = min(depth_y[d0 - DEPTH_MIN], HIT_Y + 7);
    const s16 top = depth_y[d1 - DEPTH_MIN];
    while (y - top >= 4 && sprites < MAX_SPRITES - NUM_LANES * nplayers)
    {
        const s16 h = (y - top >= 12) ? 16 : 8;
        const u16 scale = line_scale[y - h / 2];
        const u16 w = scale > 205 ? 0 : (scale > 140 ? 1 : 2);
        sprite(col_x(p, p->lane_col[lane], scale) - 4, y - h, h == 16 ? SPRITE_SIZE(1, 2) : SPRITE_SIZE(1, 1),
               TILE_ATTR_FULL(PAL1, 1, 0, 0, tile_tail + (w * NUM_LANES + lane) * 2));
        y -= h;
    }
}

static void draw_flames(Player *p)
{
    for (u16 col = 0; col < p->cols; col++)
    {
        u16 frame;
        if (p->fx[col])
        {
            frame = (FX_FRAMES - p->fx[col]) / 2;
            p->fx[col]--;
        }
        else if (!p->drums && ((p->hold_lanes >> col) & 1))
            frame = (now >> 2) & 1;     // mientras sostienes, la llama alta parpadea
        else
            continue;
        sprite(col_x(p, col, 256) - 16, HIT_Y - 16, SPRITE_SIZE(4, 2),
               TILE_ATTR_FULL(p->s->star_active ? PAL3 : PAL2, 1, 0, 0, tile_flame + frame * 8));
    }
}

static void draw_gems(Player *p)
{
    for (u16 n = p->gem_head; n != p->gem_tail; n++)
    {
        Gem *g = gem(p, n);
        const u8 visible = g->mask & ~g->hit;
        if (!visible) continue;
        const s32 d = depth(g->frame);
        if (d > VIEW_DEPTH) break;
        if (d < DEPTH_MIN) continue;
        const s16 y = depth_y[d - DEPTH_MIN];
        if (y > HIT_Y + 6) continue;    // ya pasó (la franja de abajo empieza poco después)
        const u16 scale = depth_scale[d - DEPTH_MIN];
        const u16 k = scale >= 256 ? 0 : min(GEM_SCALES - 1, ((256 - scale) * 10 + 128) >> 8);
        u16 base = (g->flags & CHART_STAR) && !phrase_failed_at(p, n) ? tile_star_gem
                   : (g->flags & GEM_CYMBAL) ? tile_cymbal : tile_gem;
        base += k * NUM_LANES * 8;
        for (u16 lane = 0; lane < NUM_LANES; lane++)
            if (((visible >> lane) & 1) && !(p->drums && lane == KICK))    // (el bombo va en el plano A)
                sprite(col_x(p, p->lane_col[lane], scale) - 16, y - 8, SPRITE_SIZE(4, 2),
                       TILE_ATTR_FULL(PAL1, 1, 0, 0, base + lane * 8));
    }
}

static void draw_tails(Player *p)
{
    // Desde la gema (o desde los aros, mientras la sostienes) hasta su fin
    for (u16 n = p->gem_head; n != p->gem_tail; n++)
    {
        Gem *g = gem(p, n);
        if (!(g->flags & CHART_SUSTAIN)) continue;
        const s32 d_start = depth(g->frame);
        if (d_start > VIEW_DEPTH) break;
        const s32 d_end = g->end ? depth(g->end) : VIEW_DEPTH;
        for (u16 lane = 0; lane < NUM_LANES; lane++)
        {
            if (!((g->mask >> lane) & 1)) continue;
            if ((g->hit >> lane) & 1)
            {
                // Acertada: la cola se va comiendo mientras la sostienes; si la soltaste, ya no se ve
                if (((p->hold_lanes >> lane) & 1) && p->hold_gem[lane] == g) draw_tail(p, lane, 0, d_end);
            }
            else
                draw_tail(p, lane, d_start, d_end);
        }
    }
}

static void draw_rings(Player *p)
{
    const u16 held = pad_held[p->pad] | (nplayers == 1 ? pad_held[1] : 0);
    for (u16 lane = 0; lane < NUM_LANES; lane++)
    {
        if (p->drums && lane == KICK) continue;
        const bool on = held & lane_buttons[lane];
        sprite(col_x(p, p->lane_col[lane], 256) - 16, HIT_Y - 8, SPRITE_SIZE(4, 2),
               TILE_ATTR_FULL(PAL1, 1, 0, 0, (on ? tile_ring_on : tile_ring) + lane * 8));
    }
}

static void draw_sprites(void)
{
    // De arriba abajo en prioridad: llamaradas, gemas, colas y aros (las gemas pasan sobre los aros)
    sprites = 0;
    for (u16 i = 0; i < nplayers; i++) draw_flames(&players[i]);
    for (u16 i = 0; i < nplayers; i++) draw_gems(&players[i]);
    for (u16 i = 0; i < nplayers; i++) draw_tails(&players[i]);
    for (u16 i = 0; i < nplayers; i++) draw_rings(&players[i]);
    VDP_setSpriteLink(sprites - 1, 0);
    VDP_updateSprites(sprites, DMA_QUEUE);
}

static void draw_score(Score *s)
{
    const u16 x = s->hud_x;
    if (s->hud_dirty & HUD_SCORE)
        queue_number(WINDOW, s->score, 7, x + 9, 25, PAL0);
    if (s->hud_dirty & HUD_COMBO)
    {
        queue_number(WINDOW, s->combo, 4, x + 9, 26, PAL0);
        char m[3] = { 'X', '0' + s->multiplier, 0 };
        queue_text(WINDOW, m, x + 14, 26, s->multiplier > 1 ? PAL2 : PAL0);
    }
    if (s->hud_dirty & HUD_STAR)
        for (u16 i = 0; i < STARBAR_TILES; i++)
        {
            const s16 fill = (s16) s->star_energy - i * 8;
            const u16 level = fill <= 0 ? 0 : (fill >= 8 ? 8 : fill);
            queue_tile(WINDOW, TILE_ATTR_FULL(PAL3, 1, 0, 0, tile_starbar + (s->star_active ? 9 : 0) + level),
                       x + 1 + i, STRIP_ROW);
        }
    s->hud_dirty = 0;
}

static void draw_meter(Player *p)
{
    if (!(p->hud_dirty & HUD_LIFE) || no_fail) return;
    const u16 color = p->life < LIFE_MAX / 4 ? 2 : (p->life < LIFE_MAX * 5 / 8 ? 1 : 0);
    for (u16 i = 0; i < METER_TILES; i++)
    {
        const s16 fill = (s16) p->life - (METER_TILES - 1 - i) * 8;
        const u16 level = fill <= 0 ? 0 : (fill >= 8 ? 8 : fill);
        queue_tile(BG_B, TILE_ATTR_FULL(PAL3, 1, 0, 0, tile_meter + color * 9 + level),
                   p->meter_col, p->meter_row + i);
    }
    p->hud_dirty = 0;
}

static void draw_hud(void)
{
    if (coop)
        draw_score(&band);
    else
        for (u16 i = 0; i < nplayers; i++) draw_score(&scores[i]);
    for (u16 i = 0; i < nplayers; i++) draw_meter(&players[i]);
}

// --- Escenario -------------------------------------------------------------------------------------

static void draw_score_labels(u16 x)
{
    draw_text(WINDOW, "PUNTOS", x, 25, PAL1);
    draw_text(WINDOW, "COMBO", x, 26, PAL1);
}

static void draw_stage(void)
{
    // El escenario con la(s) autopista(s) en trapecio (lo arma perspective.c); adentro se ve el color de fondo
    for (u16 row = 0; row < STRIP_ROW; row++)
        VDP_setTileMapDataRow(BG_B, trap_map[row], row, 0, 40, CPU);
    VDP_setBackgroundColor(1);
    // La franja fija de abajo: su fondo en el plano B y los textos en la ventana
    VDP_fillTileMapRect(BG_B, TILE_ATTR_FULL(PAL0, 1, 0, 0, tile_solid + 11), 0, STRIP_ROW, 40, 4);
    draw_text_center(WINDOW, song->title, 27, PAL1);

    if (nplayers == 1)
    {
        // Bocinas a los lados: cajas oscuras con dos conos
        for (u16 side = 0; side < 2; side++)
        {
            const u16 x = side ? 35 : 1;
            VDP_fillTileMapRect(BG_B, TILE_ATTR_FULL(PAL0, 1, 0, 0, tile_solid + 11), x, 13, 4, 11);
            VDP_fillTileMapRect(BG_B, TILE_ATTR_FULL(PAL0, 1, 0, 0, tile_solid + 9), x + 1, 14, 2, 3);
            VDP_fillTileMapRect(BG_B, TILE_ATTR_FULL(PAL0, 1, 0, 0, tile_solid + 10), x + 1, 15, 2, 1);
            VDP_fillTileMapRect(BG_B, TILE_ATTR_FULL(PAL0, 1, 0, 0, tile_solid + 9), x + 1, 19, 2, 3);
            VDP_fillTileMapRect(BG_B, TILE_ATTR_FULL(PAL0, 1, 0, 0, tile_solid + 10), x + 1, 20, 2, 1);
            // Un haz de luz desde arriba
            for (u16 y = 0; y < 10; y++)
                VDP_fillTileMapRect(BG_B, TILE_ATTR_FULL(PAL0, 1, 0, 0, tile_solid + 4), side ? x - y / 4 : x + 1 + y / 4, y, 2, 1);
        }
        draw_text(BG_B, instrument_names[players[0].instrument], 1, 2, PAL0);
        draw_text(BG_B, difficulty_names[players[0].difficulty], 1, 3, PAL1);
        if (!no_fail) draw_text(BG_B, "VIDA", players[0].meter_col, players[0].meter_row - 1, PAL1);
        if (sel.practice) draw_text(BG_B, "PRACTICA", 1, 5, PAL2);
    }
    else
    {
        // Arriba, lo de cada jugador; los medidores de vida, en las orillas
        for (u16 i = 0; i < 2; i++)
        {
            const Player *p = &players[i];
            const char *inst = instrument_names[p->instrument];
            const char *diff = difficulty_names[p->difficulty];
            draw_text(BG_B, inst, i ? 39 - strlen(inst) : 1, 0, i ? PAL3 : PAL0);
            draw_text(BG_B, diff, i ? 39 - strlen(diff) : 1, 1, PAL1);
            if (!no_fail) draw_text(BG_B, i ? "J2" : "J1", i ? 38 : 0, p->meter_row - 1, i ? PAL3 : PAL0);
        }
        if (sel.practice) draw_text_center(BG_B, "PRACTICA", 1, PAL2);
    }
    if (coop)
        draw_score_labels(band.hud_x);
    else
        for (u16 i = 0; i < nplayers; i++) draw_score_labels(scores[i].hud_x);
}

// --- Pausa -----------------------------------------------------------------------------------------

typedef enum { RUN_RESULTS, RUN_MENU, RUN_RESTART } RunEnd;

// Marcas de la práctica (en la pausa): A = el bucle empieza PRACTICE_BACK cuadros antes de donde
// pausaste (y termina donde terminaba; si eso no deja PRACTICE_MIN cuadros, hasta el final de la
// canción); B = el bucle termina donde pausaste (y empieza donde empezaba). Si el bucle quedaría de
// menos de PRACTICE_MIN cuadros, la marca no se hace. Devuelve TRUE si se marcó (hay que reiniciar).
static bool practice_mark(bool mark_start)
{
    u16 from, to;
    if (mark_start)
    {
        from = now > PRACTICE_BACK ? now - PRACTICE_BACK : 0;
        to = practice_end;
        if (to < from + PRACTICE_MIN) to = song->end_frame;
        if (to < from + PRACTICE_MIN) return FALSE;
    }
    else
    {
        from = practice_start;
        to = now;
        if (to < from + PRACTICE_MIN) return FALSE;
    }
    sel.marks = TRUE;
    sel.mark_start = from;
    sel.mark_end = to;
    return TRUE;
}

static RunEnd pause_loop(void)
{
    music_pause(TRUE);
    queue_text(WINDOW, sel.practice ? "PAUSA: START SIGUE, A INICIO, B FIN, C SALE"
                                    : "      PAUSA: START SIGUE, B SALE      ", sel.practice ? 0 : 1, 27, PAL2);
    for (;;)
    {
        wait_frame();
        input_update();
        if (joy_pressed & BUTTON_START) break;
        if ((joy_pressed & BUTTON_C) || (!sel.practice && (joy_pressed & BUTTON_B)))
        {
            sfx_play(SFX_VOLVER);
            return RUN_MENU;
        }
        if (sel.practice && (joy_pressed & (BUTTON_A | BUTTON_B)) && practice_mark(joy_pressed & BUTTON_A))
        {
            sfx_play(SFX_ACEPTAR);
            return RUN_RESTART;
        }
        music_update();         // (con la música en pausa, solo los efectos)
    }
    queue_text(WINDOW, "                                        ", 0, 27, PAL1);
    queue_text(WINDOW, song->title, (40 - strlen(song->title)) / 2, 27, PAL1);
    music_pause(FALSE);
    return RUN_RESULTS;         // (sigue la partida)
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

// PRACTICA: dónde empieza y dónde vuelve a empezar el bucle (en cuartos de la canción, o las marcas).
// Si empieza después del principio, el juego arranca ahí: las notas de los primeros PRACTICE_GRACE
// cuadros se omiten (no da tiempo de tocarlas) y la música se adelanta con music_seek.
static void practice_setup(void)
{
    const u16 quarter = song->end_frame / 4;
    practice_start = 0;
    practice_end = 0xFFFF;
    skip_frame = 0;
    if (!sel.practice) return;
    if (sel.marks)
    {
        practice_start = sel.mark_start;
        practice_end = sel.mark_end;
    }
    else
    {
        practice_end = quarter * sel.practice;
        const u16 from = min(sel.practice_from, sel.practice - 1);     // nunca en o después del final
        practice_start = quarter * from;
    }
    if (!practice_start) return;
    now = practice_start;
    skip_frame = now + PRACTICE_GRACE;
    next_row = (wy(now) > 16) ? (wy(now) - 16) / 8 : 0;
    if (now > SONG_LEAD_IN) music_seek(song->stream, now - SONG_LEAD_IN);
}

static void reset_score(Score *s, u16 notes, u16 hud_x)
{
    memset(s, 0, sizeof(Score));
    s->perfect = perfect_score(notes);
    s->multiplier = 1;
    s->hud_x = hud_x;
    s->hud_dirty = HUD_SCORE | HUD_COMBO | HUD_STAR;
}

static void start_player(u16 i, u16 instrument, u16 difficulty, s16 cx)
{
    Player *p = &players[i];
    memset(p, 0, sizeof(Player));
    p->instrument = instrument;
    p->difficulty = difficulty;
    p->drums = instrument == INSTR_DRUMS;
    p->cols = p->drums ? 4 : NUM_LANES;
    p->col_w = p->drums ? 40 : 32;
    p->cx = cx;
    p->plane_col = cx / 8 - 10;
    for (u16 lane = 0; lane < NUM_LANES; lane++) p->lane_col[lane] = p->drums ? drum_cols[lane] : lane;
    p->chart = song->charts[instrument][difficulty];
    p->life = LIFE_START;
    p->channels = song->channels[instrument];
    p->hud_dirty = HUD_LIFE;
    p->pad = i;
    p->s = coop ? &band : &scores[i];
    // El medidor de vida: con un jugador junto a la autopista; con dos, en las orillas
    p->meter_col = nplayers == 1 ? 31 : (i ? 39 : 0);
    p->meter_row = nplayers == 1 ? 15 : 9;
}

static void start(void)
{
    song = song_list[sel.song];
    (void) *(volatile const u16 *) &player_size;   // (para que el enlazador la conserve: la leen las pruebas)
    nplayers = sel.mode == MODE_SOLO ? 1 : 2;
    coop = sel.mode == MODE_COOP;
    const u16 inst[2] = { sel.instrument, sel.instrument2 };
    const u16 diff[2] = { sel.difficulty, sel.mode == MODE_VS ? sel.difficulty : sel.difficulty2 };
    Highway hw[MAX_PLAYERS];
    u16 fastest = diff[0];
    for (u16 i = 0; i < nplayers; i++)
    {
        // (con dos jugadores, las autopistas van centradas en cada mitad de la pantalla)
        start_player(i, inst[i], diff[i], nplayers == 1 ? HWY_CX : 80 + 160 * i);
        hw[i] = (Highway) { players[i].cx, players[i].cols, players[i].col_w };
        reset_score(&scores[i], song->notes[inst[i]][diff[i]], nplayers == 1 ? 14 : 1 + 20 * i);
        fastest = max(fastest, diff[i]);
    }
    reset_score(&band, nplayers == 2 ? song->notes[inst[0]][diff[0]] + song->notes[inst[1]][diff[1]] : 0, 14);
    perspective_build(nplayers, hw);
    row_first = nplayers == 1 ? players[0].plane_col : 0;
    row_width = nplayers * 20;

    now = 0;
    step_frac = 0;
    // Las dos autopistas comparten el scroll: van a la velocidad de la dificultad más alta de los dos
    speed = (8 << 8) / frames_per_row[sel.fall ? sel.fall - 1 : fastest];
    next_row = 0;
    beat_zero = song->first_beat % song->beat_frames;
    bar_phase = ((song->first_beat - beat_zero) / song->beat_frames) % 4;
    no_fail = sel.no_fail || sel.practice;
    fail_timer = 0;
    miss_fx = miss_sound = 0;
    shake[0] = shake[1] = 0;
    hwy_color = RGB24_TO_VDPCOLOR(0x080838);
    PAL_setColors(1, &hwy_color, 1, CPU);
    practice_setup();
}

static void player_result(PlayerResult *r, const Player *p, const Score *s, u16 notes_total)
{
    static const u16 thresholds[5] = { 20, 40, 60, 80, 95 };
    r->score = s->score;
    r->perfect = s->perfect;
    r->notes_hit = p ? p->notes_hit : 0;
    r->notes_total = notes_total;
    r->max_combo = s->max_combo;
    r->failed = p && p->failed;
    r->percent = notes_total ? (u32) r->notes_hit * 100 / notes_total : 0;
    const u32 pct = s->perfect ? s->star_score * 100 / s->perfect : 0;
    r->stars = 0;
    while (r->stars < 5 && pct >= thresholds[r->stars]) r->stars++;
    if (r->failed) r->stars = 0;
    r->new_record = FALSE;
}

static void finish(void)
{
    // Perder, jugar sin fallo o con opciones (salvo EFECTO AL FALLAR) no graba récord; en VS, si alguien
    // perdió (la partida se cortó), tampoco
    bool any_failed = FALSE;
    for (u16 i = 0; i < nplayers; i++) any_failed |= players[i].failed;
    const bool can_record = !sel.no_fail && !options_changed() && !any_failed;
    memset(&result, 0, sizeof(result));
    for (u16 i = 0; i < nplayers; i++)
    {
        const Player *p = &players[i];
        PlayerResult *r = &result.p[i];
        player_result(r, p, p->s, song->notes[p->instrument][p->difficulty]);
        if (!coop)
            r->new_record = can_record && record_beats(sel.song, p->instrument, p->difficulty, r->score);
    }
    if (coop)
    {
        // La banda: estrellas sobre las notas de los dos charts juntos; el récord no depende de los
        // instrumentos (la banda es la banda), sino de la dificultad más alta de los dos
        player_result(&result.band, NULL, &band, result.p[0].notes_total + result.p[1].notes_total);
        result.band.notes_hit = players[0].notes_hit + players[1].notes_hit;
        result.band.percent = result.band.notes_total ? (u32) result.band.notes_hit * 100 / result.band.notes_total : 0;
        result.band.failed = players[0].failed && players[1].failed;
        if (result.band.failed) result.band.stars = 0;
        result.band.new_record = can_record && record_beats(sel.song, BAND_RECORD,
                                                            max(players[0].difficulty, players[1].difficulty),
                                                            band.score);
    }
    if (sel.mode == MODE_VS)
    {
        if (players[0].failed != players[1].failed)
            result.winner = players[0].failed ? 2 : 1;     // gana el que no perdió, sin importar el puntaje
        else if (scores[0].score != scores[1].score)
            result.winner = scores[0].score > scores[1].score ? 1 : 2;
        else
            result.winner = 0;
    }
}

// ¿Ya se perdió? Con un jugador, al perder; en VS, en cuanto uno pierde; en Co-Op, cuando caen los dos
static bool lost(void)
{
    if (nplayers == 1) return players[0].failed;
    if (coop) return players[0].failed && players[1].failed;
    return players[0].failed || players[1].failed;
}

// Un paso del juego: la música, el chart y el juicio de los botones. Devuelve TRUE si la partida terminó.
static bool step(RunEnd *how)
{
    if (now == SONG_LEAD_IN) music_play(song->stream, MUSIC_NO_LOOP);
    music_advance();
    for (u16 i = 0; i < nplayers; i++)
    {
        Player *p = &players[i];
        decode(p);
        judge(p);
        p->pressed = 0;
        resolve_gems(p);
    }
    if (coop)
        drain_star(&band);
    else
        for (u16 i = 0; i < nplayers; i++) drain_star(&scores[i]);
    apply_mutes();
    now++;
    if (sel.practice && now >= practice_end)
    {
        *how = RUN_RESTART;
        return TRUE;
    }
    *how = RUN_RESULTS;
    if (!fail_timer && lost()) fail_timer = FAIL_DELAY;
    return (fail_timer && !--fail_timer) || now > song->end_frame + RESULTS_DELAY;
}

static RunEnd run(void)
{
    for (;;)
    {
        input_update();
        if (joy_pressed & BUTTON_START)
        {
            const RunEnd paused_end = pause_loop();
            if (paused_end != RUN_RESULTS) return paused_end;
            input_update();
        }
        // Con un jugador cuentan los dos controles; con dos, cada quien el suyo
        if (nplayers == 1)
            players[0].pressed |= joy_pressed;
        else
            for (u16 i = 0; i < 2; i++) players[i].pressed |= pad_pressed[i];

        // VELOCIDAD: este cuadro da 0, 1 o 2 pasos
        RunEnd how = RUN_RESULTS;
        step_frac += speed_steps[sel.speed];
        while (step_frac >= 4)
        {
            step_frac -= 4;
            if (step(&how)) return how;
        }
        const s32 quarters = (s32) now * 4 - 4 + step_frac;     // el último paso, más la fracción
        view = quarters > 0 ? ((u32) quarters * speed) >> 10 : 0;
        sfx_update();           // los efectos van por cuadros, no por pasos

        update_miss_fx();
        scroll_highway();
        draw_sprites();
        draw_hud();
        wait_frame();
    }
}

Screen play_run(void)
{
    for (;;)
    {
        screen_reset();
        start();
        VDP_setEnable(FALSE);
        VDP_setWindowVPos(TRUE, STRIP_ROW);
        draw_stage();
        VDP_setEnable(TRUE);
        perspective_start();
        sfx_play(SFX_ACEPTAR);     // suena mientras bajan las primeras filas

        const RunEnd how = run();
        music_stop();
        perspective_stop();
        if (how == RUN_MENU)
        {
            sel.marks = FALSE;
            return SCREEN_MENU;
        }
        if (how == RUN_RESULTS)
        {
            finish();
            return SCREEN_RESULTS;
        }
        // RUN_RESTART: la práctica vuelve a empezar
    }
}
