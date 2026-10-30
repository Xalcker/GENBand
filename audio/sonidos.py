"""Biblioteca de sonidos FM y PSG para las canciones de GENBand.

Cada sonido es un parche del YM2612 (ver compose.FM) o una envolvente del PSG. Los usa nesband_fm.py para
dar voz FM a los instrumentos de las canciones de NESBand; una cancion nueva tambien puede tomarlos de
aqui en vez de definir los suyos.
"""

from compose import FM, PSG, Op

# --- Melodia -----------------------------------------------------------------------------------------

# Dos pares de operadores (algoritmo 4) con el modulador saturado y los portadores desafinados en
# direcciones opuestas: grueso y con distorsion
GUITARRA = FM(4, 6, (
    Op(mul=1, tl=24, d1r=6, d2r=2, d1l=3, rr=7),
    Op(mul=1, dt=3, tl=8, d1r=4, d2r=2, d1l=2, rr=7),
    Op(mul=2, tl=30, d1r=8, d2r=3, d1l=4, rr=7),
    Op(mul=1, dt=7, tl=10, d1r=3, d2r=2, d1l=2, rr=7),
))

# La misma guitarra apagada con la palma: cae rapido (funk, rasgueos cortos)
APAGADA = FM(4, 6, (
    Op(mul=1, tl=22, d1r=10, d2r=6, d1l=5, rr=9),
    Op(mul=1, dt=3, tl=10, d1r=9, d2r=6, d1l=4, rr=9),
    Op(mul=2, tl=28, d1r=10, d2r=6, d1l=5, rr=9),
    Op(mul=1, dt=7, tl=12, d1r=9, d2r=6, d1l=4, rr=9),
))

# Guitarra limpia y brillante con un poco de cuerda (surf): menos saturada y con el armonico 3
LIMPIA = FM(4, 3, (
    Op(mul=1, tl=32, d1r=8, d2r=3, d1l=4, rr=7),
    Op(mul=1, dt=2, tl=8, d1r=5, d2r=3, d1l=3, rr=7),
    Op(mul=3, tl=40, d1r=10, d2r=4, d1l=5, rr=7),
    Op(mul=1, dt=6, tl=10, d1r=5, d2r=3, d1l=3, rr=7),
))

# Sintetizador de sierra (trance): los cuatro operadores suenan, el primero con retroalimentacion maxima
SIERRA = FM(7, 7, (
    Op(mul=1, tl=22, rr=6),
    Op(mul=1, dt=3, tl=30, rr=6),
    Op(mul=2, tl=38, rr=6),
    Op(mul=1, dt=7, tl=30, rr=6),
))

# Metal (trompeta): ataque un poco lento y el modulador que se abre con la nota
METAL = FM(4, 5, (
    Op(mul=1, tl=26, ar=22, d1r=4, d1l=2, rr=7),
    Op(mul=1, dt=2, tl=8, ar=24, d1r=2, d1l=1, rr=7),
    Op(mul=1, tl=34, ar=20, d1r=4, d1l=2, rr=7),
    Op(mul=1, dt=6, tl=12, ar=24, d1r=2, d1l=1, rr=7),
))

# Flauta: casi un seno, con ataque suave
FLAUTA = FM(4, 0, (
    Op(mul=1, tl=44, ar=18, rr=6),
    Op(mul=1, tl=8, ar=18, rr=6),
    Op(mul=2, tl=60, ar=18, rr=6),
    Op(mul=1, dt=3, tl=14, ar=18, rr=6),
))

# Acordeon: dos pares con el modulador una octava arriba y los portadores desafinados (el "tremolo" de
# las lengüetas)
ACORDEON = FM(4, 4, (
    Op(mul=2, tl=32, ar=26, rr=6),
    Op(mul=1, dt=2, tl=10, ar=26, rr=6),
    Op(mul=2, tl=34, ar=26, rr=6),
    Op(mul=1, dt=6, tl=12, ar=26, rr=6),
))

# --- Acompañamiento ----------------------------------------------------------------------------------

# Organo: los 4 operadores suenan (algoritmo 7), cada uno en un armonico
ORGANO = FM(7, 3, (
    Op(mul=1, tl=26, rr=7),
    Op(mul=2, tl=34, rr=7),
    Op(mul=4, tl=42, rr=7),
    Op(mul=1, dt=3, tl=30, rr=7),
))

# Piano electrico: el cuerpo (multiplicador 1) y una "lengüeta" metalica (multiplicador 14) que se apaga rapido
PIANO = FM(4, 2, (
    Op(mul=1, tl=34, d1r=8, d2r=3, d1l=5, rr=6),
    Op(mul=1, tl=8, d1r=5, d2r=3, d1l=4, rr=6),
    Op(mul=14, tl=52, d1r=14, d2r=8, d1l=8, rr=8),
    Op(mul=1, dt=3, tl=12, d1r=5, d2r=3, d1l=5, rr=6),
))

# Cuerda pulsada corta (arpegios): cae rapido y sin sostenido
PULSADA = FM(4, 3, (
    Op(mul=1, tl=30, d1r=12, d2r=8, d1l=6, rr=9),
    Op(mul=1, tl=8, d1r=9, d2r=7, d1l=5, rr=9),
    Op(mul=3, tl=42, d1r=14, d2r=9, d1l=7, rr=9),
    Op(mul=1, dt=3, tl=12, d1r=9, d2r=7, d1l=5, rr=9),
))

# Coro: ataque lento y un modulador suave sobre tres portadores
CORO = FM(5, 2, (
    Op(mul=1, tl=36, ar=20, rr=5),
    Op(mul=1, dt=2, tl=24, ar=14, rr=5),
    Op(mul=2, tl=32, ar=14, rr=5),
    Op(mul=1, dt=6, tl=24, ar=14, rr=5),
))

# --- Bajo y bateria ----------------------------------------------------------------------------------

# Bajo: una cadena de operadores (algoritmo 0) con ataque seco
BAJO = FM(0, 4, (
    Op(mul=0, tl=30, d1r=10, d1l=6, rr=8),
    Op(mul=1, tl=40, d1r=12, d1l=6, rr=8),
    Op(mul=1, tl=32, d1r=8, d1l=4, rr=8),
    Op(mul=1, tl=4, d1r=5, d2r=4, d1l=2, rr=9),
))

# Bombo: un seno (solo suena el operador 4) que baja de tono en 6 cuadros
BOMBO = FM(7, 0, (
    Op(tl=127), Op(tl=127), Op(tl=127),
    Op(mul=1, tl=0, d1r=13, d2r=10, d1l=3, rr=12),
), barrido=[19, 12, 7, 3, 1, 0])

TAROLA = PSG([15, 14, 12, 10, 8, 7, 6, 5, 4, 3, 2, 1, 0], ruido=0xE5)
PLATILLO = PSG([10, 7, 4, 2, 0], ruido=0xE4)
ABIERTO = PSG([11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1, 0], ruido=0xE4)

BATERIA = {"Bombo": BOMBO, "Tarola": TAROLA, "Platillo": PLATILLO, "Abierto": ABIERTO}
