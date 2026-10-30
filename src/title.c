// Pantalla de título: el logo, "PRESIONA START" parpadeando y la música del título.

#include "genband.h"

// Letras del logo: 4 columnas x 7 renglones cada una (un bit por tile, el más alto a la izquierda)
static const u8 letters[][7] = {
    { 0x6, 0x9, 0x8, 0xB, 0x9, 0x9, 0x7 },  // G
    { 0xF, 0x8, 0x8, 0xE, 0x8, 0x8, 0xF },  // E
    { 0x9, 0xD, 0xD, 0xB, 0xB, 0x9, 0x9 },  // N
    { 0xE, 0x9, 0x9, 0xE, 0x9, 0x9, 0xE },  // B
    { 0x6, 0x9, 0x9, 0xF, 0x9, 0x9, 0x9 },  // A
    { 0x9, 0xD, 0xD, 0xB, 0xB, 0x9, 0x9 },  // N
    { 0xE, 0x9, 0x9, 0x9, 0x9, 0x9, 0xE },  // D
};

#define LOGO_X 3
#define LOGO_Y 5

static void draw_logo(void)
{
    for (u16 i = 0; i < 7; i++)
        for (u16 row = 0; row < 7; row++)
            for (u16 col = 0; col < 4; col++)
                if (letters[i][row] & (8 >> col))
                    VDP_setTileMapXY(BG_B, TILE_ATTR_FULL(PAL2, 0, 0, 0, tile_logo + row),
                                     LOGO_X + i * 5 + col, LOGO_Y + row);
}

Screen title_run(void)
{
    screen_reset();
    draw_logo();
    draw_text_center(BG_A, "UN JUEGO DE RITMO PARA LA GENESIS", 14, PAL1);
    draw_text_center(BG_A, "GENBAND V" GENBAND_VERSION " - GPL-2.0", 25, PAL1);
    music_play(titulo_music, titulo_loop);

    for (u16 frame = 0;; frame++)
    {
        input_update();
        if (frame % 60 == 0)
            draw_text_center(BG_A, "PRESIONA START", 19, PAL2);
        else if (frame % 60 == 40)
            VDP_clearTextLineBG(BG_A, 19);
        if (joy_pressed & BUTTON_START)
        {
            sfx_play(SFX_ACEPTAR);
            return SCREEN_MENU;
        }
        music_update();
        wait_frame();
    }
}
