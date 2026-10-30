// Récords guardados en la SRAM del cartucho (la RAM con batería).
//
// La cabecera de la ROM (boot/rom_head.c, "RA") dice que el cartucho tiene SRAM: el emulador la guarda en
// un archivo (en MAME, en la carpeta nvram; en BlastEm, junto a sus partidas) y un flash cart la guarda en
// la tarjeta SD. Si el archivo falta o está dañado, el juego arranca con la tabla vacía.
//
// Lo que se guarda (bytes de la SRAM):
//   0     firma "GNR1" (4 bytes): si no está, la SRAM está vacía o es de otro juego
//   4     suma de comprobación de la tabla (2 bytes): detecta datos corruptos
//   8     tabla de REC_MAX registros de REC_SIZE bytes, uno por (canción, instrumento, dificultad)
//
// Registro (11 bytes):
//   0-1   id de la canción (Song.hash, de su título y su juego: así un récord no se pega a otra canción
//         si cambia el orden o el número de canciones del cartucho)
//   2     clave = instrumento * 4 + dificultad (REC_FREE = registro libre)
//   3-6   puntaje
//   7-9   iniciales
//   10    estrellas (0-5)
//
// Al empezar, la tabla se copia a la RAM (`table`); al guardar un récord se reescribe completa.

#include "genband.h"

#define REC_MAGIC   "GNR1"
#define REC_TABLE   8
#define REC_SIZE    11
#define REC_MAX     250         // 250 * 11 = 2750 bytes; con 10 canciones hay 120 combinaciones
#define REC_FREE    0xFF

typedef struct {
    u16 id;
    u8 key;
    u32 score;
    char initials[3];
    u8 stars;
} Record;

static Record rec_table[REC_MAX];
char last_initials[3] = { 'A', 'A', 'A' };      // las últimas que se escribieron (para la siguiente vez)

static u16 checksum(void)
{
    u16 sum = 0;
    for (u16 i = 0; i < REC_MAX * REC_SIZE; i++)
        sum = (sum << 1 | sum >> 15) + SRAM_readByte(REC_TABLE + i);
    return sum;
}

static void read_entry(u16 i, Record *r)
{
    const u32 o = REC_TABLE + (u32) i * REC_SIZE;
    r->id = SRAM_readByte(o) << 8 | SRAM_readByte(o + 1);
    r->key = SRAM_readByte(o + 2);
    r->score = 0;
    for (u16 b = 0; b < 4; b++) r->score = r->score << 8 | SRAM_readByte(o + 3 + b);
    for (u16 b = 0; b < 3; b++) r->initials[b] = SRAM_readByte(o + 7 + b);
    r->stars = SRAM_readByte(o + 10);
}

static void write_entry(u16 i, const Record *r)
{
    const u32 o = REC_TABLE + (u32) i * REC_SIZE;
    SRAM_writeByte(o, r->id >> 8);
    SRAM_writeByte(o + 1, r->id);
    SRAM_writeByte(o + 2, r->key);
    for (u16 b = 0; b < 4; b++) SRAM_writeByte(o + 3 + b, r->score >> (24 - 8 * b));
    for (u16 b = 0; b < 3; b++) SRAM_writeByte(o + 7 + b, r->initials[b]);
    SRAM_writeByte(o + 10, r->stars);
}

static void save_all(void)
{
    SRAM_enable();
    for (u16 i = 0; i < REC_MAX; i++) write_entry(i, &rec_table[i]);
    const u16 sum = checksum();
    for (u16 b = 0; b < 4; b++) SRAM_writeByte(b, REC_MAGIC[b]);
    SRAM_writeByte(4, sum >> 8);
    SRAM_writeByte(5, sum);
    SRAM_disable();
}

void records_init(void)
{
    SRAM_enableRO();
    bool valid = TRUE;
    for (u16 b = 0; b < 4; b++)
        if (SRAM_readByte(b) != (u8) REC_MAGIC[b]) valid = FALSE;
    if (valid && checksum() != (SRAM_readByte(4) << 8 | SRAM_readByte(5))) valid = FALSE;
    if (valid)
        for (u16 i = 0; i < REC_MAX; i++) read_entry(i, &rec_table[i]);
    SRAM_disable();
    if (!valid)
    {
        for (u16 i = 0; i < REC_MAX; i++) rec_table[i].key = REC_FREE;
        save_all();
    }
}

static Record *find(u16 id, u8 key)
{
    for (u16 i = 0; i < REC_MAX; i++)
        if (rec_table[i].key == key && rec_table[i].id == id) return &rec_table[i];
    return NULL;
}

bool record_get(u16 song, u16 instrument, u16 difficulty, u32 *score, char *initials, u16 *stars)
{
    const Record *r = find(song_list[song]->hash, instrument * 4 + difficulty);
    if (!r) return FALSE;
    *score = r->score;
    memcpy(initials, r->initials, 3);
    *stars = r->stars;
    return TRUE;
}

bool record_beats(u16 song, u16 instrument, u16 difficulty, u32 score)
{
    u32 best;
    char ini[3];
    u16 stars;
    return score > 0 && (!record_get(song, instrument, difficulty, &best, ini, &stars) || score > best);
}

void record_save(u16 song, u16 instrument, u16 difficulty, u32 score, const char *initials, u16 stars)
{
    const u16 id = song_list[song]->hash;
    const u8 key = instrument * 4 + difficulty;
    Record *r = find(id, key);
    for (u16 i = 0; i < REC_MAX && !r; i++)
        if (rec_table[i].key == REC_FREE) r = &rec_table[i];
    if (!r)
    {
        // Tabla llena (no debería pasar): se reemplaza el registro más bajo
        r = &rec_table[0];
        for (u16 i = 1; i < REC_MAX; i++)
            if (rec_table[i].score < r->score) r = &rec_table[i];
    }
    r->id = id;
    r->key = key;
    r->score = score;
    memcpy(r->initials, initials, 3);
    r->stars = stars;
    memcpy(last_initials, initials, 3);
    save_all();
}
