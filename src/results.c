// Resultados: puntaje, notas, precisión, combo máximo y estrellas (como en NESBand).
//
//   1 jugador: todo al centro.
//   VS:        una columna por jugador y, arriba, quién ganó ("GANA J1 POR 0001230", "EMPATE", o "GANA J2 -
//              J1 PERDIO" si uno perdió y la partida se cortó).
//   Co-Op:     lo de la banda al centro (puntaje, combo máximo y estrellas) y, abajo, lo de cada jugador
//              (notas, precisión y si cayó).
//
// Start sigue: a escribir las iniciales si hubo récord nuevo, o al menú.

#include "genband.h"

static void stars_text(char *out, u16 stars)
{
    for (u16 i = 0; i < 5; i++) out[i] = i < stars ? '*' : ' ';
    out[5] = 0;
}

static void label_value(const char *label, const char *value, u16 x, u16 y, u16 pal)
{
    draw_text(BG_A, label, x, y, PAL1);
    draw_text(BG_A, value, x + 11, y, pal);
}

static void number_text(char *out, u32 value, u16 digits, const char *suffix)
{
    uintToStr(value, out, digits);
    strcat(out, suffix);
}

static bool any_record(void)
{
    return result.p[0].new_record || result.p[1].new_record || result.band.new_record;
}

// Un jugador (o la banda): puntaje, notas, precisión, combo y estrellas en la columna x
static void player_column(const PlayerResult *r, u16 x, u16 y, bool with_score)
{
    char text[24];
    if (with_score)
    {
        number_text(text, r->score, 7, "");
        label_value("PUNTOS", text, x, y, PAL0);
        y += 2;
    }
    number_text(text, r->notes_hit, 1, "/");
    char total[8];
    uintToStr(r->notes_total, total, 1);
    strcat(text, total);
    label_value("NOTAS", text, x, y, PAL0);
    number_text(text, r->percent, 1, "%");
    label_value("PRECISION", text, x, y + 2, PAL0);
    if (with_score)
    {
        number_text(text, r->max_combo, 1, "");
        label_value("COMBO MAX", text, x, y + 4, PAL0);
        if (r->failed)
            draw_text(BG_A, "FALLASTE", x, y + 6, PAL3);
        else
        {
            stars_text(text, r->stars);
            label_value("ESTRELLAS", text, x, y + 6, PAL2);
        }
        if (r->new_record) draw_text(BG_A, "NUEVO RECORD", x, y + 8, PAL2);
    }
    else if (r->failed)
        draw_text(BG_A, "CAYO", x, y + 4, PAL3);
}

// "GUITARRA EXPERTO" no cabe junto a la etiqueta en media pantalla: la dificultad va con sus 3 primeras
// letras ("GUITARRA EXP")
static void instrument_line(u16 inst, u16 diff, u16 x, u16 y)
{
    char line[32];
    strcpy(line, instrument_names[inst]);
    strcat(line, " ");
    const u16 n = strlen(line);
    memcpy(line + n, difficulty_names[diff], 3);
    line[n + 3] = 0;
    draw_text(BG_A, line, x, y, PAL1);
}

static void winner_line(void)
{
    char text[32];
    if (!result.winner)
        strcpy(text, "EMPATE");
    else if (result.p[result.winner == 1 ? 1 : 0].failed)
        strcpy(text, result.winner == 1 ? "GANA J1 - J2 PERDIO" : "GANA J2 - J1 PERDIO");
    else
    {
        const u32 a = result.p[0].score, b = result.p[1].score;
        strcpy(text, result.winner == 1 ? "GANA J1 POR " : "GANA J2 POR ");
        uintToStr(a > b ? a - b : b - a, text + strlen(text), 7);
    }
    draw_text_center(BG_A, text, 6, PAL2);
}

Screen results_run(void)
{
    screen_reset();
    const Song *song = song_list[sel.song];
    draw_text_center(BG_A, "RESULTADOS", 1, PAL2);
    draw_text_center(BG_A, song->title, 3, PAL0);
    draw_text_center(BG_A, song->game, 4, PAL1);
    if (sel.mode == MODE_SOLO)
    {
        char line[32];
        strcpy(line, instrument_names[sel.instrument]);
        strcat(line, " - ");
        strcat(line, difficulty_names[sel.difficulty]);
        draw_text_center(BG_A, line, 6, PAL1);
        player_column(&result.p[0], 9, 9, TRUE);
    }
    else if (sel.mode == MODE_VS)
    {
        winner_line();
        draw_text(BG_A, "J1", 1, 8, PAL0);
        draw_text(BG_A, "J2", 21, 8, PAL3);
        instrument_line(sel.instrument, sel.difficulty, 4, 8);
        instrument_line(sel.instrument2, sel.difficulty, 24, 8);
        player_column(&result.p[0], 1, 10, TRUE);
        player_column(&result.p[1], 21, 10, TRUE);
    }
    else
    {
        draw_text_center(BG_A, "BANDA", 6, PAL2);
        player_column(&result.band, 9, 7, TRUE);
        draw_text(BG_A, "J1", 1, 18, PAL0);
        draw_text(BG_A, "J2", 21, 18, PAL3);
        instrument_line(sel.instrument, sel.difficulty, 4, 18);
        instrument_line(sel.instrument2, sel.difficulty2, 24, 18);
        player_column(&result.p[0], 1, 20, FALSE);
        player_column(&result.p[1], 21, 20, FALSE);
    }
    draw_text_center(BG_A, any_record() ? "START: ESCRIBE TUS INICIALES" : "START: MENU", 27, PAL1);

    for (;;)
    {
        input_update();
        if (joy_pressed & (BUTTON_START | BUTTON_A | BUTTON_C))
        {
            sfx_play(SFX_ACEPTAR);
            return any_record() ? SCREEN_INITIALS : SCREEN_MENU;
        }
        music_update();         // (solo los efectos: aquí no hay música)
        wait_frame();
    }
}
