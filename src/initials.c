// "NUEVO RECORD": escribir las 3 iniciales, como en un arcade (como en NESBand).
//
// Se llega desde los resultados (Start) si la partida superó el récord de esa canción, instrumento y
// dificultad:
//   arriba / abajo        cambia la letra (A-Z, dando la vuelta)
//   izquierda / derecha   cambia de letra
//   A, C o Start          listo: se guarda el récord y se regresa al menú
// Empieza con las últimas iniciales que se escribieron.

#include "genband.h"

#define LETTERS_X 18
#define LETTERS_Y 15

static void draw_letters(const char *ini, u16 pos)
{
    for (u16 i = 0; i < 3; i++)
    {
        const char c[2] = { ini[i], 0 };
        draw_text(BG_A, c, LETTERS_X + i * 2, LETTERS_Y, i == pos ? PAL2 : PAL0);
        draw_text(BG_A, i == pos ? "-" : " ", LETTERS_X + i * 2, LETTERS_Y + 1, PAL2);
    }
}

Screen initials_run(void)
{
    screen_reset();
    const Song *song = song_list[sel.song];
    draw_text_center(BG_A, "NUEVO RECORD", 3, PAL2);
    draw_text_center(BG_A, song->title, 6, PAL0);
    char line[32];
    strcpy(line, instrument_names[sel.instrument]);
    strcat(line, " - ");
    strcat(line, difficulty_names[sel.difficulty]);
    draw_text_center(BG_A, line, 8, PAL1);
    char score[12];
    uintToStr(result.score, score, 7);
    draw_text_center(BG_A, score, 11, PAL0);
    draw_text_center(BG_A, "ESCRIBE TUS INICIALES", 13, PAL1);
    draw_text_center(BG_A, "ARRIBA/ABAJO LETRA, START LISTO", 25, PAL1);

    char ini[3];
    memcpy(ini, last_initials, 3);
    u16 pos = 0;
    draw_letters(ini, pos);

    for (;;)
    {
        input_update();
        if (joy_pressed & (BUTTON_START | BUTTON_A | BUTTON_C))
        {
            record_save(sel.song, sel.instrument, sel.difficulty, result.score, ini, result.stars);
            sfx_play(SFX_ACEPTAR);
            return SCREEN_MENU;
        }
        if (joy_pressed & (BUTTON_UP | BUTTON_DOWN))
        {
            const s16 delta = (joy_pressed & BUTTON_UP) ? 1 : 25;
            ini[pos] = 'A' + (ini[pos] - 'A' + delta) % 26;
            draw_letters(ini, pos);
            sfx_play(SFX_MOVER);
        }
        if (joy_pressed & (BUTTON_LEFT | BUTTON_RIGHT))
        {
            pos = (pos + ((joy_pressed & BUTTON_LEFT) ? 2 : 1)) % 3;
            draw_letters(ini, pos);
            sfx_play(SFX_MOVER);
        }
        music_update();
        wait_frame();
    }
}
