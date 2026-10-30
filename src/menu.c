// Menú: canción, instrumento, dificultad y fallo. Mientras eliges, suena la canción.
//
// Arriba/abajo elige el renglón, izquierda/derecha cambia el valor, Start juega, A abre las opciones
// (options.c) y B regresa al título.

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
            VDP_clearTextLineBG(BG_A, y + 1);   // el título anterior puede ser más largo
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

// El récord de la canción, el instrumento y la dificultad elegidos: "0029920 ABC *****" o "---"
static void draw_record(void)
{
    const u16 y = item_y[ITEM_FAIL] + 2;
    u32 score;
    char ini[3];
    u16 stars;
    char text[32];
    VDP_clearTextLineBG(BG_A, y);
    draw_text(BG_A, "RECORD", LABEL_X, y, PAL1);
    if (!record_get(sel.song, sel.instrument, sel.difficulty, &score, ini, &stars))
    {
        draw_text(BG_A, "---", VALUE_X, y, PAL1);
        return;
    }
    uintToStr(score, text, 7);
    const u16 n = strlen(text);
    text[n] = ' ';
    memcpy(text + n + 1, ini, 3);
    text[n + 4] = ' ';
    for (u16 i = 0; i < 5; i++) text[n + 5 + i] = i < stars ? '*' : ' ';
    text[n + 10] = 0;
    draw_text(BG_A, text, VALUE_X, y, PAL0);
}

static void draw_all(void)
{
    for (u16 i = 0; i < ITEM_COUNT; i++) draw_value(i);
    draw_record();
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
    draw_text_center(BG_A, "START JUEGA  A OPCIONES  B REGRESA", 25, PAL1);
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
            sfx_play(SFX_VOLVER);
            return SCREEN_TITLE;
        }
        if (joy_pressed & BUTTON_A)
        {
            sfx_play(SFX_ACEPTAR);
            return SCREEN_OPTIONS;
        }
        if (joy_pressed & (BUTTON_UP | BUTTON_DOWN))
        {
            item = (item + ((joy_pressed & BUTTON_UP) ? ITEM_COUNT - 1 : 1)) % ITEM_COUNT;
            draw_all();
            sfx_play(SFX_MOVER);
        }
        if (joy_pressed & (BUTTON_LEFT | BUTTON_RIGHT))
        {
            change((joy_pressed & BUTTON_LEFT) ? -1 : 1);
            draw_all();
            sfx_play(SFX_MOVER);
        }
        if (!music_playing()) preview();     // la canción se repite mientras eliges
        music_update();
        wait_frame();
    }
}
