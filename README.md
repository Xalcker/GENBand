# GENBand

Un juego de ritmo estilo Guitar Hero / Rock Band para la Sega Genesis / Mega Drive. Es el hermano de
[NESBand](https://github.com/Xalcker/NESBand): las mismas reglas y el mismo generador de charts, pero con
el sonido FM del YM2612 y la música importada de archivos VGM.

**Estado actual (v0.1.0, primera etapa):** título con su música, menú (canción, instrumento, dificultad,
fallo), juego para **1 jugador** con pausa, notas sostenidas, frases de poder estelar, medidor de vida, y
pantalla de resultados con precisión, combo máximo y estrellas. Los charts se generan automáticamente para
guitarra, teclado y bajo en 4 dificultades, y si fallas tu instrumento se calla hasta tu siguiente acierto,
como en Rock Band, y la autopista va en perspectiva.

**Canciones:** las diez originales de NESBand (GPL-2.0-or-later), arregladas para FM: *Primer Ensayo*,
*Tormenta de Neón* (rock, guitarra), *Luz de Luna* (balada, teclado), *Salto Mortal* (funk, bajo), *Marcha
del Cartucho*, *Noche sin Estrellas*, *Carrera de Fuego*, *Brisa de Verano* (surf), *Cumbia del Cartucho* y
*Amanecer Digital* (trance).

![Juego](docs/juego.png)

## Sobre este proyecto

Todo el código de GENBand lo escribió una IA (Claude), igual que el de NESBand.

**Aviso:** GENBand es un proyecto de aficionados, sin relación con Sega, Harmonix ni Activision, ni con
Guitar Hero ni Rock Band. "Genesis" y "Mega Drive" solo indican la plataforma para la que está hecho.

## Instalación (macOS)

```bash
brew install m68k-elf-gcc m68k-elf-binutils uv blastem mame
```

```bash
git clone --depth 1 --branch v2.11 https://github.com/Stephane-D/SGDK.git tools/sgdk
```

- **m68k-elf-gcc**: el compilador para el 68000.
- **SGDK 2.11** en `tools/sgdk/`: la librería para la Genesis (video, controles, DMA). Se usa la librería
  que ya viene compilada (`lib/libmd.a`); no hace falta compilar nada de SGDK ni tener Java.
- **BlastEm**: el emulador para jugar (el más preciso). **MAME**: el de las pruebas automáticas (tiene Lua).
- **uv**: para las herramientas de Python (`uv sync` crea el venv).

`tools/` está en `.gitignore`: cada máquina baja sus propias herramientas.

En **Linux** es lo mismo con los paquetes de la distribución (`gcc-m68k-linux-gnu` no sirve: hace falta
el `m68k-elf`, por ejemplo el de [marsdev](https://github.com/andwn/marsdev)); `PREFIX=` cambia el prefijo
del compilador y `GDK=` la carpeta de SGDK.

## Compilar y jugar

```bash
./build.sh
```

```bash
blastem build/genband.bin
```

El resultado es `build/genband.bin` (y `build/genband.sym`, los símbolos, que usan las pruebas). Compilar
**no** necesita Python más allá del `python3` del sistema (para la suma de verificación de la ROM): las
canciones ya convertidas viven en `src/songs/`.

La ROM es para consolas **NTSC (60 Hz)**: la música y las notas avanzan un paso por cuadro, así que en una
consola PAL irían más lento.

### Controles

**Menú:** ↑/↓ elige el renglón, ←/→ cambia el valor, Start juega y B regresa al título. Mientras eliges,
suena la canción.

**Juego:** funciona con el control de 3 botones y con el de 6.

| Carril   | 3 botones | 6 botones |
|----------|-----------|-----------|
| Verde    | ←         | ← o X     |
| Rojo     | ↓         | ↓ o Y     |
| Amarillo | →         | → o Z     |
| Azul     | B         | B         |
| Naranja  | C         | C         |
| Poder estelar | A    | A         |
| Pausa    | Start     | Start     |

En la pausa, Start sigue y B sale al menú. En BlastEm, por defecto: flechas, A/S/D = A/B/C,
Q/W/E = X/Y/Z, Enter = Start.

Con el control de 6 botones, la mano derecha puede tocar los 5 carriles con X, Y, Z, B y C. Los charts no
piden verde + amarillo a la vez (← y → no se pueden apretar juntos en la cruz), para que sirvan con los dos
controles.

### Reglas

Son las de NESBand:

- Fácil usa 3 carriles, medio 4, difícil y experto los 5. A más dificultad, las notas bajan más rápido
  (6, 5, 4 y 3 cuadros por cada 8 píxeles).
- Tolerancia de ±6 cuadros (~100 ms). Presionar un carril sin nota cerca rompe el combo y calla tu
  instrumento.
- Cada nota vale 50 por el multiplicador (x1, x2 desde 10 de combo, x3 desde 20, x4 desde 30). Cada botón
  de un acorde cuenta como una nota.
- **Notas sostenidas:** acierta la gema y mantén el botón mientras pasa la cola: 10 puntos cada 8 cuadros.
- **Poder estelar:** las gemas en forma de diamante son frases de 4 notas; si las aciertas todas, la barra
  de abajo sube 25%. Con la mitad o más, **A** lo activa: todo vale el doble y la autopista se pone azul.
- **Vida:** el medidor junto a la autopista. Cada acierto sube 1; perder una nota baja 2 (1 en fácil) y un
  golpe al aire 1. Si llega a 0, pierdes (tu instrumento calla y la franja dice FALLASTE). En el menú,
  **SIN FALLO** quita el medidor.
- **Golpe al aire:** suena uno de tres efectos (nunca el mismo dos veces seguidas) y la autopista tiembla
  y se pone roja unos cuadros; en una racha de fallos, a lo más 3 veces por segundo. Una nota que se pasó
  sin tocarla solo calla tu instrumento. Un acorde suma la vida de una sola nota.
- **Estrellas:** salen del puntaje (sin el poder estelar ni las colas) contra el puntaje perfecto: 20, 40,
  60, 80 y 95%.

## Importar canciones

La música de Genesis se guarda en **VGM** (`.vgm`, o `.vgz` si está comprimido): son las escrituras a los
registros del YM2612 y del PSG tal como las hizo el juego. Hay colecciones completas en
[vgmrips.net](https://vgmrips.net/). Pon los tuyos en `songs_src/` (está en `.gitignore`: la música de
juegos comerciales tiene copyright y no se sube a git).

Primero mira qué tiene cada canal:

```bash
uv run genband channels "songs_src/Sonic/02 Green Hill Zone.vgz"
```

Muestra cuántas notas y qué altura tiene cada canal (`fm1`…`fm6`, `psg1`…`psg3`, `ruido`) y sugiere cuál
es la guitarra (la melodía), el teclado y el bajo. Después importa:

```bash
uv run genband import-song "songs_src/Sonic/02 Green Hill Zone.vgz" --name ghz --duration 90 --guitarra fm1 --teclado fm2 --bajo fm3
```

| Opción | Para qué |
|---|---|
| `--name` | Carpeta en `src/songs/` (minúsculas) |
| `--title` / `--game` | Lo que se muestra en el menú (si no, sale del VGM) |
| `--duration S` | Segundos que se graban, si el VGM tiene bucle (si no, 120) |
| `--guitarra`, `--teclado`, `--bajo` | Canal(es) de cada instrumento, separados por comas (`fm1,fm4`); sin esto se usa la sugerencia |
| `--beat-frames N` | Cuadros por tiempo, si el tempo detectado sale mal (las líneas de compás no cuadran) |

Deja `src/songs/<nombre>/song.c` (la música, los 12 charts y la ficha de la canción) e `import.json` (las
opciones). `./build.sh` incluye todas las canciones que haya en `src/songs/`, en orden alfabético.
`uv run genband reimport` las vuelve a importar con las mismas opciones (tras mejorar el generador) y
`uv run genband list-songs` las lista.

Qué hace, paso a paso:

1. **Lee el VGM** y repite el bucle hasta la duración pedida.
2. **La música** se convierte a un flujo por cuadro (`vgm.frame_stream`): las escrituras de cada 1/60 s
   juntas, sin las que repiten el valor de un registro. El juego lo toca con su propio reproductor
   (`src/music.c`) en el 68000.
3. **Las notas** de cada canal salen de las escrituras: en el FM, cada *key-on* es una nota y su altura sale
   del bloque y el F-number; un cambio de altura de más de 3/4 de semitono con la tecla presionada es otra
   nota (legato), y uno menor es vibrato. En el PSG, la nota empieza cuando el volumen se enciende (o sube de
   golpe).
4. **El tempo** se estima de los ataques y **los charts** se generan con el mismo generador de NESBand
   (`chart.py`): adornos juntados, notas reducidas por dificultad, carriles que siguen el contorno de la
   melodía, colas, acordes y frases estelares. `check_playable` revisa que nada pida verde + amarillo.

**Silencio al fallar:** el reproductor no corta las notas; pone al mínimo el volumen de los operadores
*portadores* del canal FM (los que suenan según su algoritmo) o la atenuación del PSG, y recuerda lo que
pide la canción. Al acertar se restaura en el acto, así que la nota que estaba sonando se vuelve a oír.

**Lo que aún no suena:** el **DAC** (los samples de batería de muchos juegos). Alimentarlo necesita un driver
en el Z80, que es la siguiente etapa; mientras, esas canciones suenan sin su batería sampleada.

## Canciones originales

Se componen en Python con `audio/compose.py`, con la misma notación de NESBand (16 filas por compás,
`nota:filas`, `@Instrumento`, batería con `K.H.S.H.`), pero los instrumentos son **parches FM** (algoritmo,
retroalimentación y los 4 operadores) o envolventes del PSG. El bombo es un seno FM que baja de tono y la
tarola y los platillos van en el ruido del PSG. El resultado es un VGM normal, que se importa como
cualquier otro (y se puede escuchar en cualquier reproductor de VGM):

```bash
uv run python audio/tormenta.py
```

```bash
uv run genband import-song audio/tormenta.vgm --name tormenta --guitarra fm1 --teclado fm2 --bajo fm3
```

Las otras nueve canciones de NESBand no se reescribieron: `audio/nesband_fm.py` convierte sus proyectos de
FamiStudio (copiados en `audio/nesband/`) a VGM. Cada canal del NES va al FM con el mismo papel (pulso 1 →
FM 1 guitarra, pulso 2 → FM 2 teclado, triángulo → FM 3 bajo; ruido y samples DPCM → batería) y cada
instrumento toma un sonido de `audio/sonidos.py` según su nombre, con su volumen traducido a atenuación:

```bash
uv run python audio/nesband_fm.py
```

```bash
uv run genband import-song audio/luna.vgm --name luna --guitarra fm1 --teclado fm2 --bajo fm3
```

*Cumbia del Cartucho* necesita `--beat-frames 36` (el estimador le adivina el doble de tempo).

Los efectos de sonido (mover, aceptar, volver y los tres de fallo) también son los de NESBand
(`audio/nesband/efectos.txt`): `build-audio` los pasa a `src/sfx_data.c` y suenan en el tercer tono del PSG.
Mientras suena uno, lo que la canción le pide a ese canal se guarda y se restaura al terminar.

La música del título es la de NESBand (`audio/nesband/titulo.txt`): `audio/titulo.py` la pasa a FM con
`nesband_fm.py`, en bucle, y `uv run genband build-audio` la convierte a `src/titulo_music.c`.

## Pruebas

```bash
tests/run_tests.sh
```

```bash
uv run pytest
```

`run_tests.sh` compila y juega cada caso en MAME, sin ventana y a toda velocidad, con un bot
(`tests/autoplay.lua`) que pasa el título, elige en el menú con el control como un jugador, toca leyendo
las notas de la RAM y anota los resultados. Comprueba que el juego perfecto acierte todo con 5 estrellas,
que sin tocar se pierda, que SIN FALLO llegue al final y que el audio suene. Cada caso deja en
`build/test-<nombre>/` las capturas, el audio (`audio.wav`) y el registro. `tests/run_tests.sh '*-nada'`
corre solo los casos que coinciden; `--no-build` usa la ROM que ya está.

`pytest` prueba el lector y escritor de VGM, la extracción de notas y el generador de charts.

## Cómo está hecho

- **C con SGDK**, compilado con `build.sh` (no con el makefile de SGDK, que pide herramientas de Windows o
  Java). Los gráficos no son imágenes: `src/gfx.c` dibuja las gemas, los aros, las llamaradas y las colas
  píxel por píxel al arrancar.
- **La autopista en perspectiva** (`src/perspective.c`): la Genesis no escala por hardware, así que el
  fondo (plano B) es un trapecio ya dibujado, con prioridad alta afuera para tapar lo demás; las líneas de
  tiempo (plano A) usan una **interrupción por línea** (`src/hint.s`) que cambia el scroll vertical en cada
  línea de pantalla, como las carreteras de los juegos de carreras; y las gemas (en 7 tamaños) y las colas
  (sprites de 8x16 en 3 anchos) se ponen donde caen. Mientras se juega, nada escribe en el VDP fuera de la
  vblank (todo va por la cola de DMA) para no chocar con la interrupción. La franja de abajo es la ventana
  del VDP.
- **Las notas** se leen del chart poco antes de entrar a la pantalla y viven en una cola de 64; de ahí se
  juzgan y se dibujan. El formato del chart es el de NESBand: pares (cuadros desde la anterior, carriles).
- **La música:** `src/music.c` aplica una vez por cuadro las escrituras del flujo; el Z80 se queda detenido
  con el bus pedido para que el 68000 pueda escribir en el YM2612.

## Hoja de ruta

Lo que ya tiene NESBand y falta aquí, más o menos en orden:

1. Driver de sonido en el Z80 para el **DAC** (batería sampleada de los VGM) y para que la música no dependa
   del 68000.
2. **2 jugadores** (VS y Co-Op), con el segundo control.
3. **Batería** como instrumento (con el editor de asignación de golpes).
4. **Récords** en la SRAM del cartucho, con iniciales.
5. **Opciones** (espejo, velocidad, caída de notas, práctica).
6. Generar los gráficos al compilar (en Python) en vez de al arrancar: hoy el arranque tarda ~2 s.
7. **Editor de charts** en el navegador, con un reproductor del YM2612.
8. Probar en hardware (flash cart y MiSTer).

## Licencia

GPL-2.0-or-later (ver `LICENSE`). SGDK tiene su propia licencia (MIT) y no se incluye en el repositorio.
