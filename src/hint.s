| Interrupción de cada línea (HInt) de la autopista en perspectiva: escribe el scroll vertical del plano A
| para la siguiente línea. Tiene que ser lo más corta posible: corre en cada una de las 224 líneas (se
| lleva buena parte del 68000) y, si la escritura llega cuando el VDP ya empezó a dibujar la línea, la
| línea sale partida. Por eso no fija la dirección de la VSRAM (la deja puesta perspective.c, con
| autoincremento 0) ni calcula nada: solo copia el siguiente valor de la tabla.
|
| Vive en la RAM (sección .data, que SGDK copia al arrancar) para modificarse a sí misma: la dirección del
| siguiente valor va dentro de la propia instrucción que lo copia (hint_src), y la instrucción siguiente
| la avanza. Así no gasta un registro (guardarlo y restaurarlo) ni lee un puntero aparte: ~132 ciclos por
| línea con la entrada a la interrupción, en vez de ~186.
|
| Para apagarla, perspective.c apunta la interrupción a hint_idle (un rte) en vez de a hint_handler.

    .section .data
    .align  2
    .globl  hint_handler, hint_src, hint_idle
hint_handler:
    .short  0x33F9                  | move.w (hint_src).l,(0xC00000).l
hint_src:
    .long   0                       | (la dirección del siguiente valor de la tabla: la pone perspective.c)
    .long   0xC00000                | el puerto de datos del VDP
    addq.l  #2,hint_src
hint_idle:
    rte
