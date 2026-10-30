// La ficha de una canción. Cada src/songs/<nombre>/song.c (lo genera `genband import-song`) define una,
// y build.sh arma la lista con todas las que haya (build/song_list.c).
#ifndef SONG_H
#define SONG_H

#include <genesis.h>

#define NUM_INSTRUMENTS  4      // guitarra, teclado, bajo, batería
#define INSTR_DRUMS      3
#define NUM_DIFFICULTIES 4      // fácil, medio, difícil, experto

// Un sample del DAC (la batería sampleada de los VGM de otros juegos): 8 bits con signo, alineado a 256
// bytes y de un largo múltiplo de 256, como lo pide el driver PCM de SGDK
typedef struct {
    const u8 *data;
    u32 length;
    u16 rate;                   // SOUND_PCM_RATE_... (0 = 32000 ... 5 = 8000 Hz)
} DacSample;

typedef struct {
    const char *title;          // en mayúsculas y sin acentos (la fuente no los tiene)
    const char *game;
    const u8 *stream;           // la música (ver music.c)
    u16 end_frame;              // cuadro en que termina, contando la entrada de la autopista
    u16 beat_frames;            // cuadros por tiempo
    u16 first_beat;             // cuadro del primer tiempo (contando la entrada)
    u16 hash;                   // identifica la canción para los récords
    u16 channels[NUM_INSTRUMENTS];  // canales que se callan al fallar (bits 0-5 FM, 6-8 PSG, 9 ruido, 10 DAC)
    const u8 *charts[NUM_INSTRUMENTS][NUM_DIFFICULTIES];  // NULL = ese instrumento no está en la canción
    u16 notes[NUM_INSTRUMENTS][NUM_DIFFICULTIES];         // notas de cada chart (cada botón de un acorde cuenta)
    const DacSample *dac;       // los samples del DAC que toca su flujo ($54 n), o NULL (va al final: las
                                // pruebas leen los campos de arriba por su lugar)
} Song;

extern const Song *const song_list[];
extern const u16 song_count;

#endif
