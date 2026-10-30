// GENBand: un juego de ritmo estilo Guitar Hero / Rock Band para la Sega Genesis / Mega Drive.
//
// main.c arranca el sistema y pasa de una pantalla a otra (título, menú, juego, resultados). Cada
// pantalla es una función que corre su propio ciclo de cuadros y devuelve la siguiente.

#include "genband.h"

Selection sel;
Result result;

const char *const instrument_names[NUM_INSTRUMENTS] = { "GUITARRA", "TECLADO", "BAJO" };
const char *const difficulty_names[NUM_DIFFICULTIES] = { "FACIL", "MEDIO", "DIFICIL", "EXPERTO" };

Screen current_screen;          // la pantalla que corre (la leen las pruebas)
u16 joy_held;
u16 joy_pressed;

void input_update(void)
{
    // Los dos controles cuentan (como en NESBand, Start o los menús funcionan desde cualquiera)
    const u16 now = JOY_readJoypad(JOY_1) | JOY_readJoypad(JOY_2);
    joy_pressed = now & ~joy_held;
    joy_held = now;
}

void wait_frame(void)
{
    SYS_doVBlankProcess();
}

void screen_reset(void)
{
    VDP_setEnable(FALSE);
    VDP_setScrollingMode(HSCROLL_PLANE, VSCROLL_PLANE);
    VDP_setHorizontalScroll(BG_A, 0);
    VDP_setHorizontalScroll(BG_B, 0);
    VDP_setVerticalScroll(BG_A, 0);
    VDP_setVerticalScroll(BG_B, 0);
    VDP_setWindowOff();
    VDP_clearPlane(BG_A, TRUE);
    VDP_clearPlane(BG_B, TRUE);
    VDP_clearPlane(WINDOW, TRUE);
    VDP_resetSprites();
    VDP_setSpriteFull(0, -32, -32, SPRITE_SIZE(1, 1), 0, 0);
    VDP_updateSprites(1, DMA);
    VDP_setBackgroundColor(0);
    VDP_setEnable(TRUE);
}

void draw_text(VDPPlane plane, const char *text, u16 x, u16 y, u16 pal)
{
    VDP_setTextPalette(pal);
    VDP_drawTextBG(plane, text, x, y);
    VDP_setTextPalette(PAL0);
}

void draw_text_center(VDPPlane plane, const char *text, u16 y, u16 pal)
{
    draw_text(plane, text, (40 - strlen(text)) / 2, y, pal);
}

void draw_number(VDPPlane plane, u32 value, u16 digits, u16 x, u16 y, u16 pal)
{
    char str[12];
    uintToStr(value, str, digits);
    draw_text(plane, str, x, y, pal);
}

void queue_text(VDPPlane plane, const char *text, u16 x, u16 y, u16 pal)
{
    u16 row[40];
    u16 n = 0;
    while (text[n] && n < 40)
    {
        row[n] = TILE_ATTR_FULL(pal, 1, 0, 0, TILE_FONT_INDEX + text[n] - 32);
        n++;
    }
    VDP_setTileMapDataRow(plane, row, y, x, n, DMA_QUEUE_COPY);
}

void queue_number(VDPPlane plane, u32 value, u16 digits, u16 x, u16 y, u16 pal)
{
    char str[12];
    uintToStr(value, str, digits);
    queue_text(plane, str, x, y, pal);
}

void queue_tile(VDPPlane plane, u16 attr, u16 x, u16 y)
{
    VDP_setTileMapDataRow(plane, &attr, y, x, 1, DMA_QUEUE_COPY);
}

int main(bool hard_reset)
{
    VDP_setScreenWidth320();
    VDP_setPlaneSize(64, 32, TRUE);
    VDP_setTextPriority(1);
    gfx_init();
    music_init();
    records_init();
    input_update();

    sel.song = 0;
    sel.instrument = 0;
    sel.difficulty = 1;
    sel.no_fail = FALSE;

    current_screen = SCREEN_TITLE;
    for (;;)
    {
        switch (current_screen)
        {
            case SCREEN_TITLE:   current_screen = title_run(); break;
            case SCREEN_MENU:    current_screen = menu_run(); break;
            case SCREEN_PLAY:    current_screen = play_run(); break;
            case SCREEN_RESULTS: current_screen = results_run(); break;
            case SCREEN_OPTIONS: current_screen = options_run(); break;
            case SCREEN_INITIALS: current_screen = initials_run(); break;
            default:             current_screen = SCREEN_TITLE; break;
        }
    }
    return 0;
}
