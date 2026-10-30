// Opciones: modificadores para rejugar una canción o aprender una parte difícil (como en NESBand).
//
// Se abre con A desde el menú; arriba/abajo elige el renglón, izquierda/derecha cambia el valor, Start
// juega y B regresa al menú. Las opciones se quedan hasta que las cambies:
//
//   ESPEJO            invierte los carriles: la nota verde sale en el naranja y al revés (play.c, decode)
//   VELOCIDAD         100%, 75%, 50% o 125%: la canción, las notas y la música avanzan más lento o más
//                     rápido (el juego da 4, 3, 2 o 5 pasos cada 4 cuadros; ver play.c, run)
//   CAIDA DE NOTAS    qué tan rápido bajan las notas, sin importar la dificultad: AUTO usa la de la
//                     dificultad, o la de fácil a experto
//   PRACTICA          la canción se repite hasta 1/4, 1/2, 3/4 o el final: sin fallo y sin resultados.
//                     En la pausa, A y B marcan el inicio y el final del bucle y C regresa al menú
//   INICIO            dónde empieza la práctica: el principio, 1/4, 1/2 o 3/4 de la canción
//   EFECTO AL FALLAR  SI, SOLO SONIDO o NO
//
// Con cualquier opción distinta de la normal no se guardan récords (salvo EFECTO AL FALLAR).

#include "genband.h"

enum { OPT_MIRROR, OPT_SPEED, OPT_FALL, OPT_PRACTICE, OPT_FROM, OPT_MISS_FX, OPT_COUNT };

#define LABEL_X 3
#define VALUE_X 27
#define FIRST_Y 6

static const char *const labels[OPT_COUNT] = {
    "ESPEJO", "VELOCIDAD", "CAIDA DE NOTAS", "PRACTICA", "INICIO DE LA PRACTICA", "EFECTO AL FALLAR",
};
static const char *const mirror_names[] = { "NO", "SI" };
static const char *const speed_names[] = { "100%", "75%", "50%", "125%" };
static const char *const fall_names[] = { "AUTO", "FACIL", "MEDIO", "DIFICIL", "EXPERTO" };
static const char *const practice_names[] = { "NO", "HASTA 1/4", "HASTA 1/2", "HASTA 3/4", "TODA" };
static const char *const from_names[] = { "PRINCIPIO", "1/4", "1/2", "3/4" };
static const char *const miss_names[] = { "SI", "SOLO SONIDO", "NO" };

static u16 item;

static u16 *value_of(u16 i)
{
    static u16 mirror;
    switch (i)
    {
        case OPT_MIRROR:   mirror = sel.mirror; return &mirror;
        case OPT_SPEED:    return &sel.speed;
        case OPT_FALL:     return &sel.fall;
        case OPT_PRACTICE: return &sel.practice;
        case OPT_FROM:     return &sel.practice_from;
        default:           return &sel.miss_fx;
    }
}

static const u16 counts[OPT_COUNT] = { 2, 4, 5, 5, 4, 3 };
static const char *const *const names[OPT_COUNT] = {
    mirror_names, speed_names, fall_names, practice_names, from_names, miss_names,
};

static void draw_item(u16 i)
{
    const u16 y = FIRST_Y + i * 2;
    const u16 pal = (i == item) ? PAL2 : PAL0;
    VDP_clearTextLineBG(BG_A, y);
    draw_text(BG_A, i == item ? ">" : " ", LABEL_X - 2, y, PAL2);
    draw_text(BG_A, labels[i], LABEL_X, y, pal);
    draw_text(BG_A, "<", VALUE_X - 2, y, pal);
    draw_text(BG_A, names[i][*value_of(i)], VALUE_X, y, pal);
    draw_text(BG_A, ">", VALUE_X + 12, y, pal);
}

static void draw_all(void)
{
    for (u16 i = 0; i < OPT_COUNT; i++) draw_item(i);
    VDP_clearTextLineBG(BG_A, 22);
    if (options_changed())
        draw_text_center(BG_A, "CON ESTAS OPCIONES NO HAY RECORDS", 22, PAL3);
}

static void change(s16 delta)
{
    u16 *v = value_of(item);
    *v = (*v + counts[item] + delta) % counts[item];
    if (item == OPT_MIRROR) sel.mirror = *v;
    if (item == OPT_PRACTICE || item == OPT_FROM) sel.marks = FALSE;   // otra práctica: sin las marcas
}

Screen options_run(void)
{
    screen_reset();
    draw_text_center(BG_A, "OPCIONES", 2, PAL2);
    draw_text_center(BG_A, "LA PRACTICA ES SIN FALLO NI RESULTADOS", 19, PAL1);
    draw_text_center(BG_A, "EN SU PAUSA: A INICIO, B FIN, C SALE", 20, PAL1);
    draw_text_center(BG_A, "START JUEGA      B REGRESA", 25, PAL1);
    draw_all();

    for (;;)
    {
        input_update();
        if (joy_pressed & BUTTON_START)
        {
            music_stop();
            return SCREEN_PLAY;
        }
        if (joy_pressed & BUTTON_B)
        {
            sfx_play(SFX_VOLVER);
            return SCREEN_MENU;
        }
        if (joy_pressed & (BUTTON_UP | BUTTON_DOWN))
        {
            item = (item + ((joy_pressed & BUTTON_UP) ? OPT_COUNT - 1 : 1)) % OPT_COUNT;
            draw_all();
            sfx_play(SFX_MOVER);
        }
        if (joy_pressed & (BUTTON_LEFT | BUTTON_RIGHT))
        {
            change((joy_pressed & BUTTON_LEFT) ? -1 : 1);
            draw_all();
            sfx_play(SFX_MOVER);
        }
        music_update();         // la canción del menú sigue sonando
        wait_frame();
    }
}
