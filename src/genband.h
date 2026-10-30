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

typedef enum { SCREEN_BOOT, SCREEN_TITLE, SCREEN_MENU, SCREEN_PLAY, SCREEN_RESULTS, SCREEN_OPTIONS, SCREEN_INITIALS } Screen;

Screen title_run(void);
Screen menu_run(void);
Screen play_run(void);
Screen results_run(void);
Screen options_run(void);
Screen initials_run(void);

extern Screen current_screen;

// Lo que se eligió en el menú
#define MODE_SOLO 0
#define MODE_VS   1             // 2 jugadores: cada quien su partida
#define MODE_COOP 2             // 2 jugadores: una banda (puntaje, combo y poder estelar compartidos)

typedef struct {
    u16 song;
    u16 instrument;
    u16 difficulty;
    u16 mode;                   // MODE_SOLO, MODE_VS o MODE_COOP
    u16 instrument2;            // los del jugador 2
    u16 difficulty2;
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

// Lo que deja la partida para la pantalla de resultados: lo de cada jugador y, en Co-Op, lo de la banda
typedef struct {
    u32 score;
    u32 perfect;                // puntaje de acertar todo (sin poder estelar ni colas): de aquí salen las estrellas
    u16 notes_hit;
    u16 notes_total;
    u16 max_combo;
    u16 percent;
    u16 stars;
    bool failed;
    bool new_record;            // superó el récord (y la partida podía guardarlo)
} PlayerResult;

typedef struct {
    PlayerResult p[2];          // (el del jugador 1 va primero: lo leen las pruebas)
    PlayerResult band;          // Co-Op
    u16 winner;                 // VS: 0 = empate, 1 o 2 = el que ganó
} Result;

#define BAND_RECORD 4           // "instrumento" de los récords de la banda (Co-Op): su clave es 16 + dificultad

extern Result result;

extern const char *const instrument_names[NUM_INSTRUMENTS];
extern const char *const difficulty_names[NUM_DIFFICULTIES];

// --- Récords (records.c) -------------------------------------------------------------------------

void records_init(void);
bool record_get(u16 song, u16 instrument, u16 difficulty, u32 *score, char *initials, u16 *stars);
bool record_beats(u16 song, u16 instrument, u16 difficulty, u32 score);
void record_save(u16 song, u16 instrument, u16 difficulty, u32 score, const char *initials, u16 stars);
extern char last_initials[3];

// --- Control (main.c) ----------------------------------------------------------------------------

extern u16 joy_held;            // botones presionados (de cualquiera de los dos controles)
extern u16 joy_pressed;         // los que se presionaron en este cuadro
extern u16 pad_held[2];         // lo mismo, de cada control
extern u16 pad_pressed[2];
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
void music_play(const u8 *stream, const DacSample *dac, u16 loop);   // dac: Song.dac (o NULL); loop: byte del flujo adonde vuelve al terminar
void music_stop(void);
void music_update(void);                        // una vez por cuadro
void music_seek(const u8 *stream, const DacSample *dac, u16 frames);  // la canción desde el principio, adelantada `frames` cuadros
void music_pause(bool pause);
void music_mute(u16 channels, bool mute);       // bits 0-5 FM, 6-8 PSG, 9 ruido, 10 DAC
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

// La fuente de NESBand (font_data.c, de genband build-font): reemplaza las letras de la de SGDK
extern const u16 font_count;
extern const u8 font_codes[];
extern const u32 font_tiles[];

extern u16 tile_solid;          // + color (0-15): un tile de un solo color
extern u16 tile_scroll;         // capa que se desplaza: líneas de tiempo (ver gfx.c)
extern u16 tile_gem;            // sprites de 4x2 tiles (8 tiles cada uno): + (escala * 5 + carril) * 8
extern u16 tile_star_gem;
extern u16 tile_cymbal;         // platillos de la batería (rombos del color del carril), como tile_gem
extern u16 tile_trap;           // de aquí hasta la fuente: el trapecio de la autopista (perspective_build)
extern u16 tile_lamp;           // el foco de una torre del escenario
extern u16 tile_crowd;          // el público: 4 tiles que stage.c redibuja (ver crowd_tiles)
extern u16 tile_bolt;           // el rayo de una frase estelar: sprite de 2x4 tiles
extern u32 crowd_tiles[3 * 4 * 8];
extern u16 tile_tail;           // sprites de 1x2 tiles: + (ancho * 5 + carril) * 2 (anchos 8, 6 y 4)
extern u16 tile_ring;
extern u16 tile_ring_on;
extern u16 tile_flame;          // 4 dibujos de 8 tiles
extern u16 tile_meter;          // medidor de vida: 3 colores x 9 niveles
extern u16 tile_starbar;        // barra de poder estelar: 2 colores x 9 niveles
extern u16 tile_logo;           // + 0..6: los tiles del logo (un color por fila)

// Tile de la capa que se desplaza: line 0 = nada, 1 = tiempo, 2 = compás, 3 = bombo; row = renglón en el tile
u16 scroll_tile(u16 line, u16 row);

// --- Escenario (stage.c) -------------------------------------------------------------------------

void stage_draw(u16 nplayers);
void stage_update(u16 now, const Song *song, u16 combo, bool star, bool all_failed);
void stage_flash(void);

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
#define MAX_PLAYERS 2
typedef struct {
    s16 cx;                     // centro (x) de la autopista
    u16 lanes;                  // carriles (columnas): 5, o 4 en la batería
    u16 lane_w;                 // ancho de cada uno en los aros (px)
} Highway;
void perspective_build(u16 count, const Highway *highways);    // el trapecio de 1 o 2 autopistas
void perspective_start(void);               // enciende la interrupción de cada línea
void perspective_stop(void);
void perspective_set_scroll(u32 world_now); // el desplazamiento del siguiente cuadro


#endif
