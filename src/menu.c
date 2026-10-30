// Menú: canción, instrumento, dificultad y fallo. Mientras eliges, suena la canción.
//
// Arriba/abajo elige el renglón, izquierda/derecha cambia el valor, Start juega y B regresa al título.

#include "genband.h"

enum { ITEM_SONG, ITEM_INSTRUMENT, ITEM_DIFFICULTY, ITEM_FAIL, ITEM_COUNT };

#define LABEL_X  3
#define VALUE_X  17
#define ITEM_Y   8              // renglón del primer elemento; cada uno ocupa 3 (la canción, 4)

static const u16 item_y[ITEM_COUNT] = { ITEM_Y, ITEM_Y + 4, ITEM_Y + 7, ITEM_Y + 10 };
static const char *const labels[ITEM_COUNT] = { "CANCION", "INSTRUMENTO", "DIFICULTAD", "FALLO" };

static u16 item;

static const Song *song(void)
{
    return song_list[sel.song];
}

static bool has_instrument(u16 inst)
{
    return song()->charts[inst][0] != NULL;
}

// Si la canción no tiene el instrumento elegido, el primero que sí tenga
static void fix_instrument(void)
{
    for (u16 i = 0; i < NUM_INSTRUMENTS && !has_instrument(sel.instrument); i++)
        sel.instrument = (sel.instrument + 1) % NUM_INSTRUMENTS;
}

static void draw_value(u16 i)
{
    const u16 y = item_y[i];
    const u16 pal = (i == item) ? PAL2 : PAL0;
    VDP_clearTextLineBG(BG_A, y);
    draw_text(BG_A, i == item ? ">" : " ", LABEL_X - 2, y, PAL2);
    draw_text(BG_A, labels[i], LABEL_X, y, pal);
    switch (i)
    {
        case ITEM_SONG:
            draw_text(BG_A, song()->title, LABEL_X, y + 1, pal);
            VDP_clearTextLineBG(BG_A, y + 2);
            draw_text(BG_A, song()->game, LABEL_X, y + 2, PAL1);
            if (song_count > 1)
            {
                char pos[12];
                uintToStr(sel.song + 1, pos, 1);
                strcat(pos, "/");
                char total[6];
                uintToStr(song_count, total, 1);
                strcat(pos, total);
                draw_text(BG_A, pos, 33, y, PAL1);
            }
            break;
        case ITEM_INSTRUMENT:
            draw_text(BG_A, "<", VALUE_X - 2, y, pal);
            draw_text(BG_A, instrument_names[sel.instrument], VALUE_X, y, pal);
            draw_text(BG_A, ">", VALUE_X + 10, y, pal);
            break;
        case ITEM_DIFFICULTY:
            draw_text(BG_A, "<", VALUE_X - 2, y, pal);
            draw_text(BG_A, difficulty_names[sel.difficulty], VALUE_X, y, pal);
            draw_text(BG_A, ">", VALUE_X + 10, y, pal);
            break;
        case ITEM_FAIL:
            draw_text(BG_A, "<", VALUE_X - 2, y, pal);
            draw_text(BG_A, sel.no_fail ? "SIN FALLO" : "SI", VALUE_X, y, pal);
            draw_text(BG_A, ">", VALUE_X + 10, y, pal);
            break;
    }
}

static void draw_all(void)
{
    for (u16 i = 0; i < ITEM_COUNT; i++) draw_value(i);
    // Cuántas notas tiene el chart elegido
    VDP_clearTextLineBG(BG_A, 22);
    char text[24] = "NOTAS: ";
    char num[8];
    uintToStr(song()->notes[sel.instrument][sel.difficulty], num, 1);
    strcat(text, num);
    draw_text_center(BG_A, text, 22, PAL1);
}

static void preview(void)
{
    music_play(song()->stream, MUSIC_NO_LOOP);
}

static void change(s16 delta)
{
    switch (item)
    {
        case ITEM_SONG:
            sel.song = (sel.song + song_count + delta) % song_count;
            fix_instrument();
            preview();
            break;
        case ITEM_INSTRUMENT:
            do sel.instrument = (sel.instrument + NUM_INSTRUMENTS + delta) % NUM_INSTRUMENTS;
            while (!has_instrument(sel.instrument));
            break;
        case ITEM_DIFFICULTY:
            sel.difficulty = (sel.difficulty + NUM_DIFFICULTIES + delta) % NUM_DIFFICULTIES;
            break;
        case ITEM_FAIL:
            sel.no_fail = !sel.no_fail;
            break;
    }
}

Screen menu_run(void)
{
    screen_reset();
    draw_text_center(BG_A, "G E N B A N D", 2, PAL2);
    draw_text_center(BG_A, "START JUEGA      B REGRESA", 25, PAL1);
    if (sel.song >= song_count) sel.song = 0;
    fix_instrument();
    draw_all();
    preview();

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
            music_stop();
            return SCREEN_TITLE;
        }
        if (joy_pressed & (BUTTON_UP | BUTTON_DOWN))
        {
            item = (item + ((joy_pressed & BUTTON_UP) ? ITEM_COUNT - 1 : 1)) % ITEM_COUNT;
            draw_all();
        }
        if (joy_pressed & (BUTTON_LEFT | BUTTON_RIGHT))
        {
            change((joy_pressed & BUTTON_LEFT) ? -1 : 1);
            draw_all();
        }
        if (!music_playing()) preview();     // la canción se repite mientras eliges
        music_update();
        wait_frame();
    }
}
