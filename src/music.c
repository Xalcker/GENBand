// El reproductor de música: aplica, una vez por cuadro, las escrituras al YM2612 y al PSG que trae el
// flujo de la canción (lo genera pctools/genband_tools/vgm.py, frame_stream):
//
//   $50 v        escribir v en el PSG
//   $52 r v      escribir v en el registro r del YM2612, puerto 0 (canales 1-3 y globales)
//   $53 r v      lo mismo en el puerto 1 (canales 4-6)
//   $62          fin del cuadro
//   $7n          fin del cuadro y n cuadros más sin escrituras
//   $61 lo hi    fin del cuadro y N cuadros más sin escrituras
//   $66          fin (o vuelta al bucle)
//
// Corre en el 68000, así que el Z80 se queda detenido (con el bus pedido, que es lo que deja al 68000
// escribir en el YM2612).
//
// Silenciar un canal (cuando el jugador falla, como en Rock Band) no corta sus notas: en el FM se pone
// al mínimo el volumen (TL) de sus operadores portadores, y en el PSG la atenuación al máximo. El
// reproductor recuerda los valores que pide la canción, así que al acertar se restauran en el acto y
// la nota que ya estaba sonando se vuelve a oír.

#include "genband.h"

#define YM_ADDR0  (*(vu8 *) 0xA04000)
#define YM_DATA0  (*(vu8 *) 0xA04001)
#define YM_ADDR1  (*(vu8 *) 0xA04002)
#define YM_DATA1  (*(vu8 *) 0xA04003)
#define PSG_DATA  (*(vu8 *) 0xC00011)

#define CH_PSG    6             // primer canal del PSG en la máscara (6-8 tonos, 9 ruido)
#define TL_SILENT 0x7F

static const u8 *start;
static const u8 *ptr;
static u16 loop_offset;
static u16 wait;                // cuadros que faltan para la siguiente tanda de escrituras
static bool paused;

static u16 muted;               // canales silenciados
static u8 fm_tl[6][4];          // TL que pide la canción, por canal y operador (en el orden de los registros)
static u8 fm_alg[6];
static u8 psg_vol[4];           // atenuación que pide la canción (15 = apagado)
static u8 psg_latch;            // último registro elegido del PSG (byte con el bit 7)

// Qué operadores suenan en cada algoritmo, en el orden de los registros (op1, op3, op2, op4 = bits 0-3)
static const u8 carriers[8] = { 0x8, 0x8, 0x8, 0x8, 0xC, 0xE, 0xE, 0xF };

static void ym_write(u16 port, u8 reg, u8 value)
{
    while (YM_ADDR0 & 0x80);
    if (port)
    {
        YM_ADDR1 = reg;
        YM_DATA1 = value;
    }
    else
    {
        YM_ADDR0 = reg;
        YM_DATA0 = value;
    }
}

// Escribe el TL de los portadores del canal: el de la canción o, si está silenciado, el mínimo
static void fm_apply(u16 ch)
{
    const u16 port = ch >= 3;
    const u16 c = ch % 3;
    const u8 mask = carriers[fm_alg[ch]];
    const bool off = (muted >> ch) & 1;

    for (u16 k = 0; k < 4; k++)
        if (mask & (1 << k))
            ym_write(port, 0x40 + 4 * k + c, off ? TL_SILENT : fm_tl[ch][k]);
}

static void psg_apply(u16 ch)
{
    const bool off = (muted >> (CH_PSG + ch)) & 1;
    PSG_DATA = 0x90 | (ch << 5) | (off ? 15 : psg_vol[ch]);
}

static void fm(u16 port, u8 reg, u8 value)
{
    if (reg >= 0x40 && reg < 0x50 && (reg & 3) != 3)
    {
        const u16 ch = port * 3 + (reg & 3);
        const u16 k = (reg >> 2) & 3;
        fm_tl[ch][k] = value;
        if (((muted >> ch) & 1) && (carriers[fm_alg[ch]] & (1 << k)))
            value = TL_SILENT;
    }
    else if (reg >= 0xB0 && reg < 0xB3)
    {
        const u16 ch = port * 3 + (reg - 0xB0);
        fm_alg[ch] = value & 7;
        ym_write(port, reg, value);
        if ((muted >> ch) & 1) fm_apply(ch);     // cambiaron los portadores
        return;
    }
    ym_write(port, reg, value);
}

static void psg(u8 value)
{
    u8 latch = (value & 0x80) ? value : psg_latch;
    if (value & 0x80) psg_latch = value;
    if (latch & 0x10)           // volumen
    {
        const u16 ch = (latch >> 5) & 3;
        psg_vol[ch] = value & 0x0F;
        if ((muted >> (CH_PSG + ch)) & 1) value |= 0x0F;
    }
    PSG_DATA = value;
}

static void silence(void)
{
    for (u16 code = 0; code < 7; code++)
        if (code != 3) ym_write(0, 0x28, code);
    for (u16 ch = 0; ch < 4; ch++)
        PSG_DATA = 0x9F | (ch << 5);
}

void music_init(void)
{
    // El Z80 no hace nada (el reproductor corre en el 68000): se queda con el bus pedido para siempre
    Z80_requestBus(TRUE);
    ptr = NULL;
    muted = 0;
    ym_write(0, 0x22, 0);
    ym_write(0, 0x27, 0);
    ym_write(0, 0x2B, 0);
    silence();
}

void music_play(const u8 *stream, u16 loop)
{
    silence();
    start = ptr = stream;
    loop_offset = loop;
    wait = 0;
    paused = FALSE;
    muted = 0;
    memset(fm_tl, 0, sizeof(fm_tl));
    memset(fm_alg, 0, sizeof(fm_alg));
    memset(psg_vol, 15, sizeof(psg_vol));
}

void music_stop(void)
{
    ptr = NULL;
    silence();
}

bool music_playing(void)
{
    return ptr != NULL;
}

void music_pause(bool pause)
{
    if (!ptr || pause == paused) return;
    paused = pause;
    if (pause)
        silence();
    else
        for (u16 ch = 0; ch < 4; ch++) psg_apply(ch);   // el FM vuelve a sonar en su siguiente nota
}

void music_mute(u16 channels, bool mute)
{
    const u16 changed = mute ? (channels & ~muted) : (channels & muted);
    if (!changed) return;
    muted ^= changed;
    for (u16 ch = 0; ch < 6; ch++)
        if ((changed >> ch) & 1) fm_apply(ch);
    for (u16 ch = 0; ch < 4; ch++)
        if ((changed >> (CH_PSG + ch)) & 1) psg_apply(ch);
}

void music_update(void)
{
    if (!ptr || paused) return;
    if (wait)
    {
        wait--;
        return;
    }
    for (;;)
    {
        const u8 cmd = *ptr++;
        if (cmd == 0x52 || cmd == 0x53)
        {
            fm(cmd - 0x52, ptr[0], ptr[1]);
            ptr += 2;
        }
        else if (cmd == 0x50)
            psg(*ptr++);
        else if (cmd == 0x62)
            return;
        else if ((cmd & 0xF0) == 0x70)
        {
            wait = cmd & 0x0F;
            return;
        }
        else if (cmd == 0x61)
        {
            wait = ptr[0] | (ptr[1] << 8);
            ptr += 2;
            return;
        }
        else    // $66: fin
        {
            if (loop_offset == MUSIC_NO_LOOP)
            {
                ptr = NULL;
                silence();
                return;
            }
            ptr = start + loop_offset;
        }
    }
}
