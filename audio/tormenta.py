"""Tormenta de Neon: rock rapido en La menor (180 BPM). Luce la guitarra (FM 1).

Es la misma composicion que en NESBand, arreglada para el YM2612: guitarra con distorsion, organo y
coro en el teclado, bajo FM, una guitarra ritmica en quintas (FM 4 y 5) y bateria (bombo FM y ruido).

Uso (desde la raiz del repositorio):  uv run python audio/tormenta.py
"""

from pathlib import Path

from compose import FM, PSG, Cancion, Escala, Op, armonizar, arpegio, escribir, midi, nombre

AQUI = Path(__file__).parent
LA_MENOR = Escala(["A", "B", "C", "D", "E", "F", "G"])

instrumentos = {
    # Dos pares de operadores (algoritmo 4) con el modulador saturado (retroalimentacion 6) y los
    # portadores desafinados en direcciones opuestas: suena grueso y con distorsion
    "Guitarra": FM(4, 6, (
        Op(mul=1, tl=24, d1r=6, d2r=2, d1l=3, rr=7),
        Op(mul=1, dt=3, tl=8, d1r=4, d2r=2, d1l=2, rr=7),
        Op(mul=2, tl=30, d1r=8, d2r=3, d1l=4, rr=7),
        Op(mul=1, dt=7, tl=10, d1r=3, d2r=2, d1l=2, rr=7),
    )),
    # La misma guitarra apagada con la palma: cae rapido
    "Ritmo": FM(4, 6, (
        Op(mul=1, tl=22, d1r=10, d2r=6, d1l=5, rr=9),
        Op(mul=1, dt=3, tl=10, d1r=9, d2r=6, d1l=4, rr=9),
        Op(mul=2, tl=28, d1r=10, d2r=6, d1l=5, rr=9),
        Op(mul=1, dt=7, tl=12, d1r=9, d2r=6, d1l=4, rr=9),
    )),
    # Organo: los 4 operadores suenan (algoritmo 7), cada uno en un armonico
    "Teclado": FM(7, 3, (
        Op(mul=1, tl=26, rr=7),
        Op(mul=2, tl=34, rr=7),
        Op(mul=4, tl=42, rr=7),
        Op(mul=1, dt=3, tl=30, rr=7),
    )),
    # Coro: ataque lento y un modulador suave sobre tres portadores
    "Coro": FM(5, 2, (
        Op(mul=1, tl=36, ar=20, rr=5),
        Op(mul=1, dt=2, tl=24, ar=14, rr=5),
        Op(mul=2, tl=32, ar=14, rr=5),
        Op(mul=1, dt=6, tl=24, ar=14, rr=5),
    )),
    # Bajo: una cadena de operadores (algoritmo 0) con ataque seco
    "Bajo": FM(0, 4, (
        Op(mul=0, tl=30, d1r=10, d1l=6, rr=8),
        Op(mul=1, tl=40, d1r=12, d1l=6, rr=8),
        Op(mul=1, tl=32, d1r=8, d1l=4, rr=8),
        Op(mul=1, tl=4, d1r=5, d2r=4, d1l=2, rr=9),
    )),
    # Bombo: un seno (solo suena el operador 4) que baja de tono en 6 cuadros
    "Bombo": FM(7, 0, (
        Op(tl=127), Op(tl=127), Op(tl=127),
        Op(mul=1, tl=0, d1r=13, d2r=10, d1l=3, rr=12),
    ), barrido=[19, 12, 7, 3, 1, 0]),
    "Tarola": PSG([15, 14, 12, 10, 8, 7, 6, 5, 4, 3, 2, 1, 0], ruido=0xE5),
    "Platillo": PSG([10, 7, 4, 2, 0], ruido=0xE4),
    "Abierto": PSG([11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1, 0], ruido=0xE4),
}

# --- Melodia (guitarra, FM 1), un compas por cadena: 16 filas cada uno ---------------------------------
estrofa = [
    "A4:2 C5:2 E5:4 r:2 E5:2 D5:2 C5:2",  # La menor
    "F5:4 E5:2 C5:2 A4:4 r:2 C5:2",  # Fa
    "G4:2 C5:2 E5:4 G5:4 E5:2 C5:2",  # Do
    "D5:4 B4:2 D5:2 G5:6 r:2",  # Sol
    "E5:2 E5:2 A5:4 G5:2 E5:2 C5:4",  # La menor
    "A5:4 G5:2 F5:2 E5:4 C5:4",  # Fa
    "D5:2 G5:2 B5:4 A5:2 G5:2 D5:4",  # Sol
    "E5:8 r:4 G5:2 B5:2",  # Mi menor
]
coro = [
    "C6:4 A5:4 F5:4 A5:4",  # Fa
    "D6:4 B5:4 G5:4 B5:4",  # Sol
    "E6:6 C6:2 A5:4 C6:4",  # La menor
    "B5:6 G5:2 E5:8",  # Mi menor
    "C6:2 C6:2 A5:4 F5:2 A5:2 C6:4",  # Fa
    "D6:2 D6:2 B5:4 G5:2 B5:2 D6:4",  # Sol
    "E6:4 D6:2 C6:2 A5:8",  # La menor
    "A5:8 E5:2 A5:2 C6:4",  # La menor (vuelve a la estrofa)
]
puente = [
    "D5:8 F5:4 A5:4",  # Re menor
    "E5:8 C5:4 E5:4",  # La menor
    "F5:6 A5:2 C6:8",  # Fa
    "B5:4 A5:4 G5:4 D5:4",  # Sol
]
intro = [
    "A4:2 A4:2 r:2 A4:2 A4:2 r:2 C5:2 r:2",  # riff de calentamiento sobre La menor
    "F4:2 F4:2 r:2 F4:2 F4:2 r:2 A4:2 r:2",  # y sobre Fa
    estrofa[0],
    estrofa[1],
]
final = [
    "A5:4 E5:4 C5:4 A4:4",
    "G5:4 D5:4 B4:4 G4:4",
    "A5:4 C6:4 E6:4 A5:4",
    "A5:16",
]
guitarra = ["@Guitarra " + intro[0]] + intro[1:] + estrofa + coro + estrofa + puente + puente + coro + coro + final

# --- Acordes por compas (raiz del bajo): de aqui salen el bajo y el acompanamiento ---------------
raices_intro = ["A2", "F2", "A2", "F2"]
raices_estrofa = ["A2", "F2", "C3", "G2", "A2", "F2", "G2", "E2"]
raices_coro = ["F2", "G2", "A2", "E2", "F2", "G2", "A2", "A2"]
raices_puente = ["D3", "A2", "F2", "G2"]
raices_final = ["A2", "G2", "A2", "A2"]
raices = (
    raices_intro + raices_estrofa + raices_coro + raices_estrofa + raices_puente * 2
    + raices_coro * 2 + raices_final
)

# --- Teclado (FM 2): arpegios en la estrofa, terceras bajo la melodia en el coro, acordes largos en el puente
ARPEGIO = [0, 1, 2, 1, 0, 1, 2, 1]
LENTO = [0, 1, 2, 3]
def acomp(r, orden=ARPEGIO, filas=2):
    return arpegio(r, LA_MENOR, orden, filas)

teclado = ["@Teclado " + acomp(raices_intro[0])] + [acomp(r) for r in raices_intro[1:]]
teclado += [acomp(r) for r in raices_estrofa]
teclado += ["@Coro " + armonizar(coro[0], LA_MENOR, -2)] + [armonizar(c, LA_MENOR, -2) for c in coro[1:]]
teclado += ["@Teclado " + acomp(raices_estrofa[0])] + [acomp(r) for r in raices_estrofa[1:]]
teclado += ["@Coro " + acomp(r, LENTO, 4) for r in raices_puente] * 2
teclado += ["@Coro " + armonizar(coro[0], LA_MENOR, -2)] + [armonizar(c, LA_MENOR, -2) for c in coro[1:]]
teclado += [armonizar(c, LA_MENOR, -2) for c in coro]
teclado += ["@Teclado " + acomp(r) for r in raices_final]

# --- Bajo (FM 3): corcheas en la estrofa, galope en el coro, notas largas en el puente ----------------
def bajo_corcheas(r):
    alta = r[0] + str(int(r[1:]) + 1)
    return f"{r}:2 {r}:2 {alta}:2 {r}:2 {r}:2 {r}:2 {alta}:2 {r}:2"

def bajo_galope(r):
    return f"{r}:2 {r}:1 {r}:1 {r}:2 {r}:2 {r}:2 {r}:1 {r}:1 {r}:2 {r}:2"

def bajo_largo(r):
    alta = r[0] + str(int(r[1:]) + 1)
    return f"{r}:8 {alta}:4 {r}:4"

# Las raices con sostenido no existen en esta tonalidad, asi que la octava es solo cambiar el numero.
bajo = [bajo_corcheas(r) for r in raices_intro + raices_estrofa]
bajo += [bajo_galope(r) for r in raices_coro]
bajo += [bajo_corcheas(r) for r in raices_estrofa]
bajo += [bajo_largo(r) for r in raices_puente] * 2
bajo += [bajo_galope(r) for r in raices_coro * 2]
bajo += [bajo_corcheas(r) for r in raices_final[:3]] + [f"{raices_final[3]}:16"]

# --- Bateria (16 caracteres por compas) -------------------------------------------------------------
RITMO = "K.H.S.H.K.H.S.H."
RELLENO = "K.H.S.H.SSKKSSSS"
CORO = "K.O.S.O.K.K.S.O."
PUENTE = "K...S...K.K.S..."
SOLO_HAT = "H.H.H.H.H.H.H.H."
def con_relleno(base, n):
    return [base] * (n - 1) + [RELLENO]

bateria = [SOLO_HAT, SOLO_HAT, RITMO, RELLENO]
bateria += con_relleno(RITMO, 8)
bateria += con_relleno(CORO, 8)
bateria += con_relleno(RITMO, 8)
bateria += [PUENTE] * 3 + [RELLENO] + [PUENTE] * 3 + [RELLENO]
bateria += con_relleno(CORO, 8) * 2
bateria += [RITMO, RITMO, RITMO, "K..............."]


# --- Guitarra ritmica (FM 4 la raiz y FM 5 la quinta): quintas apagadas con la palma -------------------
def quinta(r, semitonos):
    return nombre(midi(r) + semitonos)

def ritmo_corcheas(r, s):
    n = quinta(r, s)
    return f"{n}:2 {n}:2 r:2 {n}:2 {n}:2 r:2 {n}:2 {n}:2"

def ritmo_coro(r, s):
    n = quinta(r, s)
    return f"{n}:6 {n}:2 {n}:4 {n}:4"

def ritmo_largo(r, s):
    return f"{quinta(r, s)}:16"

def ritmo(s):
    partes = [ritmo_corcheas(r, s) for r in raices_intro + raices_estrofa]
    partes += [ritmo_coro(r, s) for r in raices_coro]
    partes += [ritmo_corcheas(r, s) for r in raices_estrofa]
    partes += [ritmo_largo(r, s) for r in raices_puente] * 2
    partes += [ritmo_coro(r, s) for r in raices_coro * 2]
    partes += [ritmo_corcheas(r, s) for r in raices_final[:3]] + [ritmo_largo(raices_final[3], s)]
    return partes

cancion = Cancion(
    "Tormenta de Neon", 5, instrumentos,
    {"fm1": guitarra, "fm2": teclado, "fm3": bajo, "fm4": ritmo(12), "fm5": ritmo(19), "bateria": bateria},
    {"fm1": "Guitarra", "fm2": "Teclado", "fm3": "Bajo", "fm4": "Ritmo", "fm5": "Ritmo"},
    mezcla={"fm4": 10, "fm5": 14, "fm2": 4},
)
escribir(cancion, AQUI / "tormenta.vgm")
