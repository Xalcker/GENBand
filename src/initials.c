// "NUEVO RECORD": escribir las 3 iniciales, como en un arcade (como en NESBand).
//
// Se llega desde los resultados (Start) si alguien superó su récord. En VS cada jugador con récord escribe
// las suyas con su propio control, al mismo tiempo; en Co-Op el récord es de la banda y lo escribe el
// jugador 1:
//   arriba / abajo        cambia la letra (A-Z, dando la vuelta)
//   izquierda / derecha   cambia de letra
//   A, C o Start          listo
// Cuando todos terminan, se guardan los récords y se regresa al menú. Empiezan con las últimas iniciales
// que se escribieron.

#include "genband.h"

#define LETTERS_Y 15

typedef struct {
    u16 pad;                    // el control con que se escribe (con un jugador, cualquiera)
    u16 instrument, difficulty; // la clave del récord (BAND_RECORD en Co-Op)
    const PlayerResult *r;
    u16 x;                      // columna de la primera letra
    char ini[3];
    u16 pos;
    bool done;
} Entry;

static void draw_letters(const Entry *e)
{
    for (u16 i = 0; i < 3; i++)
    {
        const char c[2] = { e->ini[i], 0 };
        draw_text(BG_A, c, e->x + i * 2, LETTERS_Y, (i == e->pos && !e->done) ? PAL2 : PAL0);
        draw_text(BG_A, (i == e->pos && !e->done) ? "-" : " ", e->x + i * 2, LETTERS_Y + 1, PAL2);
    }
    if (e->done) draw_text(BG_A, "LISTO", e->x, LETTERS_Y + 3, PAL1);
}

static void draw_heading(const Entry *e, const char *who, u16 center)
{
    char line[32];
    strcpy(line, who);
    if (*who) strcat(line, " ");
    strcat(line, e->instrument == BAND_RECORD ? "BANDA" : instrument_names[e->instrument]);
    draw_text(BG_A, line, center - strlen(line) / 2, 8, PAL1);
    draw_text(BG_A, difficulty_names[e->difficulty], center - strlen(difficulty_names[e->difficulty]) / 2, 9, PAL1);
    char score[12];
    uintToStr(e->r->score, score, 7);
    draw_text(BG_A, score, center - 3, 11, PAL0);
}

Screen initials_run(void)
{
    screen_reset();
    const Song *song = song_list[sel.song];
    draw_text_center(BG_A, "NUEVO RECORD", 2, PAL2);
    draw_text_center(BG_A, song->title, 5, PAL0);
    draw_text_center(BG_A, "ESCRIBE TUS INICIALES", 13, PAL1);
    draw_text_center(BG_A, "ARRIBA/ABAJO LETRA, START LISTO", 25, PAL1);

    Entry entries[2];
    u16 count = 0;
    if (sel.mode == MODE_COOP)
        entries[count++] = (Entry) { .pad = 0, .instrument = BAND_RECORD,
                                     .difficulty = max(sel.difficulty, sel.difficulty2), .r = &result.band };
    else
        for (u16 i = 0; i < (sel.mode == MODE_VS ? 2 : 1); i++)
            if (result.p[i].new_record)
                entries[count++] = (Entry) { .pad = i, .instrument = i ? sel.instrument2 : sel.instrument,
                                             .difficulty = sel.difficulty, .r = &result.p[i] };
    for (u16 i = 0; i < count; i++)
    {
        Entry *e = &entries[i];
        // Con dos récords, uno en cada mitad de la pantalla
        const u16 center = count == 1 ? 20 : (e->pad ? 30 : 10);
        e->x = center - 2;
        memcpy(e->ini, last_initials, 3);
        draw_heading(e, sel.mode == MODE_VS ? (e->pad ? "J2" : "J1") : "", center);
        draw_letters(e);
    }

    for (;;)
    {
        input_update();
        bool all_done = TRUE;
        for (u16 i = 0; i < count; i++)
        {
            Entry *e = &entries[i];
            if (e->done) continue;
            const u16 pressed = sel.mode == MODE_SOLO ? joy_pressed : pad_pressed[e->pad];
            if (pressed & (BUTTON_START | BUTTON_A | BUTTON_C))
            {
                e->done = TRUE;
                sfx_play(SFX_ACEPTAR);
            }
            else if (pressed & (BUTTON_UP | BUTTON_DOWN))
            {
                e->ini[e->pos] = 'A' + (e->ini[e->pos] - 'A' + ((pressed & BUTTON_UP) ? 1 : 25)) % 26;
                sfx_play(SFX_MOVER);
            }
            else if (pressed & (BUTTON_LEFT | BUTTON_RIGHT))
            {
                e->pos = (e->pos + ((pressed & BUTTON_LEFT) ? 2 : 1)) % 3;
                sfx_play(SFX_MOVER);
            }
            if (pressed) draw_letters(e);
            all_done &= e->done;
        }
        if (all_done)
        {
            for (u16 i = 0; i < count; i++)
            {
                const Entry *e = &entries[i];
                record_save(sel.song, e->instrument, e->difficulty, e->r->score, e->ini, e->r->stars);
            }
            return SCREEN_MENU;
        }
        music_update();
        wait_frame();
    }
}
