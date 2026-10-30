// Menú: canción, jugadores, instrumento, dificultad y fallo. Mientras eliges, suena la canción.
//
// Arriba/abajo elige el renglón, izquierda/derecha cambia el valor, Start juega, A abre las opciones
// (options.c) y B regresa al título.
//
// Dos jugadores (como en NESBand): el jugador 2 elige su instrumento y su dificultad con el control 2 (su
// cursor es rojo; arriba/abajo cambia entre esos dos renglones). En VS los dos juegan la misma dificultad
// (la elige el jugador 1) y, de entrada, el mismo instrumento (el 2 copia al 1, pero puede cambiarlo): un
// duelo sobre las mismas notas. En Co-Op no pueden tocar el mismo instrumento.

#include "genband.h"

enum { ITEM_SONG, ITEM_PLAYERS, ITEM_INSTRUMENT, ITEM_DIFFICULTY, ITEM_FAIL, ITEM_COUNT };

#define LABEL_X  3
#define VALUE_X  16             // valores del jugador 1 (y de todo lo demás)
#define VALUE2_X 29             // del jugador 2
#define RECORD_Y 19

static const u16 item_y[ITEM_COUNT] = { 6, 10, 13, 15, 17 };
static const char *const labels[ITEM_COUNT] = { "CANCION", "JUGADORES", "INSTRUMENTO", "DIFICULTAD", "FALLO" };
static const char *const mode_names[3] = { "1 JUGADOR", "2 JUGADORES VS", "2 JUGADORES COOP" };

static u16 item;
static u16 item2 = ITEM_INSTRUMENT;     // el renglón del cursor del jugador 2

static const Song *song(void)
{
    return song_list[sel.song];
}

static bool has_instrument(u16 inst)
{
    return song()->charts[inst][0] != NULL;
}

// El siguiente instrumento que tenga la canción (y, en Co-Op, que no sea `taken`)
static u16 next_instrument(u16 inst, s16 delta, u16 taken)
{
    for (u16 i = 0; i < NUM_INSTRUMENTS; i++)
    {
        inst = (inst + NUM_INSTRUMENTS + delta) % NUM_INSTRUMENTS;
        if (has_instrument(inst) && !(sel.mode == MODE_COOP && inst == taken)) return inst;
    }
    return inst;
}

// Que lo elegido exista en la canción y, en Co-Op, que los instrumentos no se repitan
static void fix_instruments(void)
{
    if (!has_instrument(sel.instrument)) sel.instrument = next_instrument(sel.instrument, 1, 0xFF);
    if (!has_instrument(sel.instrument2) || (sel.mode == MODE_COOP && sel.instrument2 == sel.instrument))
        sel.instrument2 = next_instrument(sel.instrument2, 1, sel.instrument);
}

static void value(const char *text, u16 x, u16 y, u16 pal, bool arrows)
{
    if (arrows) draw_text(BG_A, "<", x - 1, y, pal);
    draw_text(BG_A, text, x, y, pal);
    if (arrows) draw_text(BG_A, ">", x + 9, y, pal);
}

static void draw_item(u16 i)
{
    const u16 y = item_y[i];
    const u16 pal = (i == item) ? PAL2 : PAL0;
    const bool two = sel.mode != MODE_SOLO;
    VDP_clearTextLineBG(BG_A, y);
    draw_text(BG_A, i == item ? ">" : " ", LABEL_X - 2, y, PAL2);
    draw_text(BG_A, labels[i], LABEL_X, y, pal);
    // El cursor del jugador 2, junto a su columna
    if (two && i == item2) draw_text(BG_A, ">", VALUE2_X - 2, y, PAL3);
    const u16 pal2 = (two && i == item2) ? PAL3 : PAL0;
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
        case ITEM_PLAYERS:
            draw_text(BG_A, "<", VALUE_X - 1, y, pal);
            draw_text(BG_A, mode_names[sel.mode], VALUE_X, y, pal);
            draw_text(BG_A, ">", VALUE_X + 17, y, pal);
            VDP_clearTextLineBG(BG_A, y + 2);
            if (two)
            {
                draw_text(BG_A, "J1", VALUE_X, y + 2, PAL1);
                draw_text(BG_A, "J2", VALUE2_X, y + 2, PAL3);
            }
            break;
        case ITEM_INSTRUMENT:
            value(instrument_names[sel.instrument], VALUE_X, y, pal, TRUE);
            if (two) value(instrument_names[sel.instrument2], VALUE2_X, y, pal2, TRUE);
            break;
        case ITEM_DIFFICULTY:
            value(difficulty_names[sel.difficulty], VALUE_X, y, pal, TRUE);
            // En VS el jugador 2 juega la dificultad del 1
            if (two) value(difficulty_names[sel.mode == MODE_VS ? sel.difficulty : sel.difficulty2], VALUE2_X, y, pal2,
                           sel.mode == MODE_COOP);
            break;
        case ITEM_FAIL:
            value(sel.no_fail ? "SIN FALLO" : "SI", VALUE_X, y, pal, TRUE);
            break;
    }
}

// Un récord: "0029920 ABC *****" o "---"
static void record_text(char *text, u16 instrument, u16 difficulty)
{
    u32 score;
    char ini[3];
    u16 stars;
    if (!record_get(sel.song, instrument, difficulty, &score, ini, &stars))
    {
        strcpy(text, "---");
        return;
    }
    uintToStr(score, text, 7);
    const u16 n = strlen(text);
    text[n] = ' ';
    memcpy(text + n + 1, ini, 3);
    text[n + 4] = ' ';
    for (u16 i = 0; i < 5; i++) text[n + 5 + i] = i < stars ? '*' : ' ';
    text[n + 10] = 0;
}

// El récord de lo elegido (en VS uno por jugador; en Co-Op, el de la banda)
static void draw_records(void)
{
    char text[32];
    VDP_clearTextLineBG(BG_A, RECORD_Y);
    VDP_clearTextLineBG(BG_A, RECORD_Y + 1);
    if (sel.mode == MODE_COOP)
    {
        draw_text(BG_A, "RECORD BANDA", LABEL_X, RECORD_Y, PAL1);
        record_text(text, BAND_RECORD, max(sel.difficulty, sel.difficulty2));
        draw_text(BG_A, text, VALUE_X, RECORD_Y, PAL0);
        return;
    }
    draw_text(BG_A, sel.mode == MODE_VS ? "RECORD J1" : "RECORD", LABEL_X, RECORD_Y, PAL1);
    record_text(text, sel.instrument, sel.difficulty);
    draw_text(BG_A, text, VALUE_X, RECORD_Y, PAL0);
    if (sel.mode == MODE_VS)
    {
        draw_text(BG_A, "RECORD J2", LABEL_X, RECORD_Y + 1, PAL1);
        record_text(text, sel.instrument2, sel.difficulty);
        draw_text(BG_A, text, VALUE_X, RECORD_Y + 1, PAL3);
    }
}

static void draw_all(void)
{
    for (u16 i = 0; i < ITEM_COUNT; i++) draw_item(i);
    draw_records();
    // Cuántas notas tiene el chart elegido (con un jugador)
    VDP_clearTextLineBG(BG_A, 22);
    if (sel.mode == MODE_SOLO)
    {
        char text[24] = "NOTAS: ";
        char num[8];
        uintToStr(song()->notes[sel.instrument][sel.difficulty], num, 1);
        strcat(text, num);
        draw_text_center(BG_A, text, 22, PAL1);
    }
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
            fix_instruments();
            preview();
            break;
        case ITEM_PLAYERS:
            sel.mode = (sel.mode + 3 + delta) % 3;
            if (sel.mode == MODE_VS) sel.instrument2 = sel.instrument;     // el 2 copia al 1
            fix_instruments();
            break;
        case ITEM_INSTRUMENT:
            sel.instrument = next_instrument(sel.instrument, delta, 0xFF);
            if (sel.mode == MODE_COOP && sel.instrument2 == sel.instrument)
                sel.instrument2 = next_instrument(sel.instrument2, 1, sel.instrument);
            break;
        case ITEM_DIFFICULTY:
            sel.difficulty = (sel.difficulty + NUM_DIFFICULTIES + delta) % NUM_DIFFICULTIES;
            break;
        case ITEM_FAIL:
            sel.no_fail = !sel.no_fail;
            break;
    }
}

// El control 2: su instrumento y su dificultad (en VS, solo el instrumento)
static bool player2(u16 pressed)
{
    if (sel.mode == MODE_SOLO || !pressed) return FALSE;
    if (pressed & (BUTTON_UP | BUTTON_DOWN))
    {
        item2 = (sel.mode == MODE_COOP && item2 == ITEM_INSTRUMENT) ? ITEM_DIFFICULTY : ITEM_INSTRUMENT;
        return TRUE;
    }
    if (pressed & (BUTTON_LEFT | BUTTON_RIGHT))
    {
        const s16 delta = (pressed & BUTTON_LEFT) ? -1 : 1;
        if (item2 == ITEM_INSTRUMENT)
            sel.instrument2 = next_instrument(sel.instrument2, delta, sel.instrument);
        else
            sel.difficulty2 = (sel.difficulty2 + NUM_DIFFICULTIES + delta) % NUM_DIFFICULTIES;
        return TRUE;
    }
    return FALSE;
}

Screen menu_run(void)
{
    screen_reset();
    draw_text_center(BG_A, "G E N B A N D", 2, PAL2);
    draw_text_center(BG_A, "START JUEGA  A OPCIONES  B REGRESA", 25, PAL1);
    if (sel.song >= song_count) sel.song = 0;
    fix_instruments();
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
        // El control 1 maneja el menú (con un jugador, también el 2)
        const u16 pressed1 = sel.mode == MODE_SOLO ? joy_pressed : pad_pressed[0];
        if (pressed1 & BUTTON_B)
        {
            music_stop();
            sfx_play(SFX_VOLVER);
            return SCREEN_TITLE;
        }
        if (pressed1 & BUTTON_A)
        {
            sfx_play(SFX_ACEPTAR);
            return SCREEN_OPTIONS;
        }
        bool moved = FALSE;
        if (pressed1 & (BUTTON_UP | BUTTON_DOWN))
        {
            item = (item + ((pressed1 & BUTTON_UP) ? ITEM_COUNT - 1 : 1)) % ITEM_COUNT;
            moved = TRUE;
        }
        if (pressed1 & (BUTTON_LEFT | BUTTON_RIGHT))
        {
            change((pressed1 & BUTTON_LEFT) ? -1 : 1);
            moved = TRUE;
        }
        if (sel.mode != MODE_SOLO) moved |= player2(pad_pressed[1]);
        if (moved)
        {
            draw_all();
            sfx_play(SFX_MOVER);
        }
        if (!music_playing()) preview();     // la canción se repite mientras eliges
        music_update();
        wait_frame();
    }
}
