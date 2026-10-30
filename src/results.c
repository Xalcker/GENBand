// Resultados: puntaje, notas, precisión, combo máximo y estrellas. Start regresa al menú.

#include "genband.h"

static void row(const char *label, u32 value, u16 digits, const char *suffix, u16 y)
{
    char text[32];
    char num[12];
    strcpy(text, label);
    uintToStr(value, num, digits);
    strcat(text, num);
    strcat(text, suffix);
    draw_text(BG_A, text, 9, y, PAL0);
}

Screen results_run(void)
{
    screen_reset();
    const Song *song = song_list[sel.song];
    draw_text_center(BG_A, "RESULTADOS", 2, PAL2);
    draw_text_center(BG_A, song->title, 5, PAL0);
    draw_text_center(BG_A, song->game, 6, PAL1);
    char line[32];
    strcpy(line, instrument_names[sel.instrument]);
    strcat(line, " - ");
    strcat(line, difficulty_names[sel.difficulty]);
    draw_text_center(BG_A, line, 8, PAL1);

    row("PUNTOS      ", result.score, 7, "", 11);
    char total[12] = "/";
    uintToStr(result.notes_total, total + 1, 1);
    row("NOTAS       ", result.notes_hit, 1, total, 13);
    row("PRECISION   ", result.percent, 1, "%", 15);
    row("COMBO MAX   ", result.max_combo, 1, "", 17);

    if (result.failed)
        draw_text_center(BG_A, "FALLASTE", 20, PAL3);
    else
    {
        char stars[6] = "     ";
        for (u16 i = 0; i < result.stars; i++) stars[i] = '*';
        draw_text(BG_A, "ESTRELLAS", 9, 20, PAL0);
        draw_text(BG_A, stars, 21, 20, PAL2);
    }
    if (result.new_record)
    {
        draw_text_center(BG_A, "NUEVO RECORD", 22, PAL2);
        draw_text_center(BG_A, "START: ESCRIBE TUS INICIALES", 25, PAL1);
    }
    else
        draw_text_center(BG_A, "START: MENU", 25, PAL1);

    for (;;)
    {
        input_update();
        if (joy_pressed & (BUTTON_START | BUTTON_A | BUTTON_C))
        {
            sfx_play(SFX_ACEPTAR);
            return result.new_record ? SCREEN_INITIALS : SCREEN_MENU;
        }
        music_update();         // (solo los efectos: aquí no hay música)
        wait_frame();
    }
}
