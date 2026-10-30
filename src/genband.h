#ifndef GENBAND_H
#define GENBAND_H

#include <genesis.h>
#include "song.h"
#include "sfx.h"

#define SONG_LEAD_IN    128     // cuadros de autopista antes de que arranque la música
#define NUM_LANES       5

// Formato de los charts (el mismo que en NESBand): pares (cuadros desde la entrada anterior, carriles)
#define CHART_END       0xFF    // carriles = $FF: fin del chart
#define CHART_RELEASE   0x80    // entrada de fin de cola: sus bits 0-4 son los carriles que se sueltan
#define CHART_SUSTAIN   0x40    // en una nota: tiene cola
#define CHART_STAR      0x20    // en una nota: forma parte de una frase de poder estelar
#define CHART_LANES     0x1F

// --- Pantallas -----------------------------------------------------------------------------------

typedef enum { SCREEN_BOOT, SCREEN_TITLE, SCREEN_MENU, SCREEN_PLAY, SCREEN_RESULTS, SCREEN_OPTIONS } Screen;

Screen title_run(void);
Screen menu_run(void);
Screen play_run(void);
Screen results_run(void);
Screen options_run(void);

extern Screen current_screen;

// Lo que se eligió en el menú
typedef struct {
    u16 song;
    u16 instrument;
    u16 difficulty;
    bool no_fail;
    // Opciones (options.c): valen hasta que se cambian
    bool mirror;                // ESPEJO: los carriles al revés
    u16 speed;                  // VELOCIDAD: 0 = 100%, 1 = 75%, 2 = 50%, 3 = 125%
    u16 fall;                   // CAIDA DE NOTAS: 0 = la de la dificultad, 1-4 = la de fácil a experto
    u16 practice;               // PRACTICA: 0 = no, 1-3 = bucle hasta 1/4, 1/2 o 3/4 de la canción, 4 = toda
    u16 practice_from;          // INICIO DE LA PRACTICA: 0 = el principio, 1-3 = desde 1/4, 1/2 o 3/4
    u16 miss_fx;                // EFECTO AL FALLAR: MISS_FX_ALL, MISS_FX_SOUND o MISS_FX_OFF
    // Marcas de la práctica (A y B en la pausa): valen hasta volver al menú
    bool marks;
    u16 mark_start, mark_end;
} Selection;


#define MISS_FX_ALL   0         // sonido, temblor y rojo
#define MISS_FX_SOUND 1         // solo el sonido
#define MISS_FX_OFF   2

extern Selection sel;

// ¿Las opciones cambian el juego? (entonces no se guardan récords; EFECTO AL FALLAR no cuenta)
static inline bool options_changed(void)
{
    return sel.mirror || sel.speed || sel.fall || sel.practice;
}

// Lo que deja la partida para la pantalla de resultados
typedef struct {
    u32 score;
    u32 perfect;                // puntaje de acertar todo (sin poder estelar ni colas): de aquí salen las estrellas
    u16 notes_hit;
    u16 notes_total;
    u16 max_combo;
    u16 percent;
    u16 stars;
    bool failed;
} Result;

extern Result result;

extern const char *const instrument_names[NUM_INSTRUMENTS];
extern const char *const difficulty_names[NUM_DIFFICULTIES];

// --- Control (main.c) ----------------------------------------------------------------------------

extern u16 joy_held;            // botones presionados (de cualquiera de los dos controles)
extern u16 joy_pressed;         // los que se presionaron en este cuadro
void input_update(void);
void wait_frame(void);          // espera la vblank y avanza la música si está sonando

// --- Pantalla (main.c) ---------------------------------------------------------------------------

void screen_reset(void);        // apaga y limpia todo: planos, scroll, sprites, ventana
void draw_text(VDPPlane plane, const char *text, u16 x, u16 y, u16 pal);
void draw_text_center(VDPPlane plane, const char *text, u16 y, u16 pal);
void draw_number(VDPPlane plane, u32 value, u16 digits, u16 x, u16 y, u16 pal);

// Lo mismo, pero por la cola de DMA (se escribe en la siguiente vblank). En el juego no se puede tocar
// el VDP a media pantalla: la interrupción de cada línea también le escribe (ver perspective.c).
void queue_text(VDPPlane plane, const char *text, u16 x, u16 y, u16 pal);
void queue_number(VDPPlane plane, u32 value, u16 digits, u16 x, u16 y, u16 pal);
void queue_tile(VDPPlane plane, u16 attr, u16 x, u16 y);

// --- Música (music.c) ----------------------------------------------------------------------------

#define MUSIC_NO_LOOP   0xFFFF

void music_init(void);
void music_play(const u8 *stream, u16 loop);    // loop: byte del flujo adonde vuelve al terminar
void music_stop(void);
void music_update(void);                        // una vez por cuadro
void music_seek(const u8 *stream, u16 frames);  // la canción desde el principio, adelantada `frames` cuadros
void music_pause(bool pause);
void music_mute(u16 channels, bool mute);       // bits 0-5 FM, 6-8 PSG, 9 ruido
bool music_playing(void);
void music_advance(void);                       // solo la música (music_update = efectos + música)
void sfx_play(u16 id);                          // SFX_... (sfx.h); suena aunque no haya música
void sfx_update(void);                          // solo los efectos (un cuadro)

extern const u8 *const titulo_music;
extern const u16 titulo_loop;

// --- Gráficos (gfx.c) ----------------------------------------------------------------------------

void gfx_init(void);

#define GEM_SCALES 7            // tamaños de las gemas (cada uno 10% más chico)

u16 gfx_load_tile(const u32 *data);

extern u16 tile_solid;          // + color (0-15): un tile de un solo color
extern u16 tile_scroll;         // capa que se desplaza: líneas de tiempo (ver gfx.c)
extern u16 tile_gem;            // sprites de 4x2 tiles (8 tiles cada uno): + (escala * 5 + carril) * 8
extern u16 tile_star_gem;
extern u16 tile_tail;           // sprites de 1x2 tiles: + (ancho * 5 + carril) * 2 (anchos 8, 6 y 4)
extern u16 tile_ring;
extern u16 tile_ring_on;
extern u16 tile_flame;          // 4 dibujos de 8 tiles
extern u16 tile_meter;          // medidor de vida: 3 colores x 9 niveles
extern u16 tile_starbar;        // barra de poder estelar: 2 colores x 9 niveles
extern u16 tile_logo;           // + 0..6: los tiles del logo (un color por fila)

// Tile de la capa que se desplaza: line 0 = nada, 1 = tiempo, 2 = compás; row = renglón en el tile
u16 scroll_tile(u16 line, u16 row);

// --- Perspectiva (perspective.c) -----------------------------------------------------------------

#define SCREEN_LINES    224
#define HIT_Y           184             // centro de los aros
#define HWY_TOP         24              // línea de pantalla del fondo de la autopista
#define HWY_CX          160             // centro de la autopista
#define VIEW_DEPTH      200             // píxeles del mundo que se ven por delante de los aros
#define DEPTH_MIN       (-16)           // tablas por profundidad: de un poco detrás de los aros...
#define DEPTH_MAX       (VIEW_DEPTH + 16)   // ...a un poco más allá del fondo
#define STRIP_ROW       24              // la franja fija de abajo (ventana) empieza en este renglón

extern s16 line_depth[SCREEN_LINES + 1];    // profundidad que muestra cada línea de pantalla
extern u16 line_scale[SCREEN_LINES + 1];    // escala (8.8) de cada línea
extern u8 depth_y[DEPTH_MAX - DEPTH_MIN + 1];       // línea de pantalla de cada profundidad
extern u16 depth_scale[DEPTH_MAX - DEPTH_MIN + 1];  // y su escala (8.8)
extern u16 trap_map[STRIP_ROW][40];         // el fondo en trapecio, listo para el plano B

void perspective_init(void);
void perspective_start(void);               // enciende la interrupción de cada línea
void perspective_stop(void);
void perspective_set_scroll(u32 world_now); // el desplazamiento del siguiente cuadro

// Centro del carril (en píxeles) a una escala dada
static inline s16 lane_x(u16 lane, u16 scale)
{
    return HWY_CX + (((s32) (2 * lane - 4) * 16 * scale) >> 8);
}

#endif
