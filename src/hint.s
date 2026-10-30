| Interrupción de cada línea (HInt) de la autopista en perspectiva: escribe el scroll vertical del plano A
| para la siguiente línea. Tiene que ser lo más corta posible: si la escritura llega cuando el VDP ya
| empezó a dibujar la línea, la línea sale partida. Por eso no fija la dirección de la VSRAM (la deja
| puesta perspective.c, con autoincremento 0) ni calcula nada: solo copia el siguiente valor de la tabla.

    .section .text
    .globl  hint_handler
hint_handler:
    tst.b   hint_enabled
    beq.s   1f
    move.l  %a0,-(%sp)
    movea.l hint_ptr,%a0
    move.w  (%a0)+,(0xC00000).l
    move.l  %a0,hint_ptr
    movea.l (%sp)+,%a0
1:  rte
