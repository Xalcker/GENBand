"""Musica del titulo de GENBand: un riff de 8 compases en La menor (150 BPM) que se repite.

Uso (desde la raiz del repositorio):  uv run genband build-audio
(corre este archivo, que deja audio/titulo.vgm, y lo convierte a src/titulo_music.c)
"""

from pathlib import Path

from compose import FM, PSG, Cancion, Op, escribir

AQUI = Path(__file__).parent

instrumentos = {
    "Lead": FM(4, 5, (
        Op(mul=1, tl=26, d1r=5, d2r=2, d1l=3, rr=7),
        Op(mul=1, dt=3, tl=10, d1r=4, d2r=2, d1l=2, rr=7),
        Op(mul=3, tl=34, d1r=8, d2r=3, d1l=4, rr=7),
        Op(mul=1, dt=7, tl=12, d1r=3, d2r=2, d1l=2, rr=7),
    )),
    "Bajo": FM(0, 4, (
        Op(mul=0, tl=30, d1r=10, d1l=6, rr=8),
        Op(mul=1, tl=40, d1r=12, d1l=6, rr=8),
        Op(mul=1, tl=32, d1r=8, d1l=4, rr=8),
        Op(mul=1, tl=6, d1r=5, d2r=4, d1l=2, rr=9),
    )),
    "Arpa": PSG([12, 10, 8, 7, 6, 5, 4, 3, 2]),
    "Bombo": FM(7, 0, (
        Op(tl=127), Op(tl=127), Op(tl=127),
        Op(mul=1, tl=0, d1r=13, d2r=10, d1l=3, rr=12),
    ), barrido=[19, 12, 7, 3, 1, 0]),
    "Tarola": PSG([15, 14, 12, 10, 8, 7, 6, 5, 4, 3, 2, 1, 0], ruido=0xE5),
    "Platillo": PSG([10, 7, 4, 2, 0], ruido=0xE4),
    "Abierto": PSG([11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1, 0], ruido=0xE4),
}

melodia = [
    "A4:4 C5:2 E5:2 A5:4 G5:2 E5:2",
    "F5:4 E5:2 D5:2 C5:6 r:2",
    "G4:4 B4:2 D5:2 G5:4 F5:2 D5:2",
    "E5:8 G#4:4 B4:4",
    "A4:4 C5:2 E5:2 A5:4 B5:2 C6:2",
    "D6:4 C6:2 B5:2 A5:6 r:2",
    "F5:2 G5:2 A5:2 F5:2 E5:4 D5:4",
    "E5:8 r:4 E4:4",
]
raices = ["A2", "F2", "G2", "E2", "A2", "D2", "F2", "E2"]
bajo = [f"{r}:2 {r}:2 {r[0]}{int(r[1]) + 1}:2 {r}:2 {r}:2 {r}:2 {r[0]}{int(r[1]) + 1}:2 {r}:2" for r in raices]
arpegios = {
    "A2": "A4 C5 E5", "F2": "F4 A4 C5", "G2": "G4 B4 D5", "E2": "E4 G#4 B4", "D2": "D4 F4 A4",
}
psg = []
for r in raices:
    a, b, c = arpegios[r].split()
    psg.append(f"{a}:2 {b}:2 {c}:2 {b}:2 {a}:2 {b}:2 {c}:2 {b}:2")
bateria = ["K.H.S.H.K.H.S.H."] * 7 + ["K.H.S.H.K.SSSSSS"]

cancion = Cancion(
    "GENBand", 6, instrumentos,
    {"fm1": melodia, "fm3": bajo, "psg1": psg, "bateria": bateria},
    {"fm1": "Lead", "fm3": "Bajo", "psg1": "Arpa"},
    mezcla={"fm1": 4},
)
escribir(cancion, AQUI / "titulo.vgm", bucle=True)
