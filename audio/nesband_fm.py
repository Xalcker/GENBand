"""Convierte las canciones originales de NESBand a VGM para GENBand, con sonidos FM.

Las canciones de NESBand (GPL-2.0-or-later, como GENBand) estan en audio/nesband/ como proyectos de texto de
FamiStudio, con todas sus notas. Aqui cada canal del NES pasa a uno de la Genesis, con el mismo papel que
tenia en NESBand (y del que salen los mismos charts):

    pulso 1   -> FM 1 (guitarra)        pulso 2 -> FM 2 (teclado)        triangulo -> FM 3 (bajo)
    ruido     -> bateria: el bombo al FM 6 y la tarola y los platillos al ruido del PSG
    DPCM      -> bateria: los samples de bombo (C1) y tarola (C#1)

Cada instrumento de NESBand toma un sonido de sonidos.py segun su nombre, y su volumen (el maximo de su
envolvente) se traduce a atenuacion de los portadores, para que la mezcla quede como en el original.

Uso (desde la raiz del repositorio):

    uv run python audio/nesband_fm.py            todas las de audio/nesband/
    uv run python audio/nesband_fm.py luna       solo esa

Deja audio/<nombre>.vgm; despues se importa con genband import-song (ver el README). La musica del titulo
(audio/nesband/titulo.txt) tambien sale de aqui, pero en bucle y sin importarla: la convierte genband build-audio.
"""

from __future__ import annotations

import re
import sys
from dataclasses import replace
from pathlib import Path

import sonidos
from compose import FM, PORTADORES, Cancion, escribir_linea, nueva_linea, tocar_bateria, tocar_fm

AQUI = Path(__file__).parent

CANALES = {"Square1": 0, "Square2": 1, "Triangle": 2}  # canal del NES -> canal FM

SONIDOS = {
    "Guitarra": sonidos.GUITARRA,
    "Melodia": sonidos.GUITARRA,
    "Surf": sonidos.LIMPIA,
    "Chop": sonidos.APAGADA,
    "Sintetizador": sonidos.SIERRA,
    "Trompeta": sonidos.METAL,
    "Flauta": sonidos.FLAUTA,
    "Lamento": sonidos.FLAUTA,
    "Acordeon": sonidos.ACORDEON,
    "Piano": sonidos.PIANO,
    "Organo": sonidos.ORGANO,
    "Teclado": sonidos.ORGANO,
    "Coro": sonidos.CORO,
    "Pluck": sonidos.PULSADA,
    "Arpegio": sonidos.PULSADA,
    "Bajo": sonidos.BAJO,
}
DPCM = {"C1": "Bombo", "C#1": "Tarola"}  # notas del instrumento de samples de NESBand

VOLUMEN_REFERENCIA = 13  # el volumen del NES (0-15) que suena sin atenuar
TL_POR_PASO = 1.5  # atenuacion (en pasos de TL, 0.75 dB) por cada paso de volumen del NES


def atenuar(sonido: FM, extra: int) -> FM:
    """El mismo sonido con los portadores mas bajos."""
    ops = tuple(replace(op, tl=min(127, op.tl + extra)) if i in PORTADORES[sonido.alg] else op
                for i, op in enumerate(sonido.ops))
    return replace(sonido, ops=ops)


def leer(ruta: Path) -> dict:
    """Lo que hace falta de un proyecto de texto de FamiStudio: instrumentos, tempo y notas por canal."""
    attrs = lambda linea: dict(re.findall(r'(\w+)="([^"]*)"', linea))  # noqa: E731
    instrumentos: dict[str, int] = {}  # nombre -> volumen maximo
    canales: dict[str, list[tuple[int, int, str, str]]] = {}
    titulo, fila, filas = "", 6, 16
    canal = patron = instrumento = None
    patrones: dict[str, list[tuple[int, int, str, str]]] = {}
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        a = attrs(linea)
        tipo = linea.strip().split(" ", 1)[0]
        if tipo == "Instrument":
            instrumento = a["Name"]
            instrumentos[instrumento] = 15
        elif tipo == "Envelope" and a.get("Type") == "Volume" and instrumento:
            instrumentos[instrumento] = max(int(v) for v in a["Values"].split(","))
        elif tipo == "Song":
            titulo, fila, filas = a["Name"], int(a["NoteLength"]), int(a["PatternLength"])
        elif tipo == "Channel":
            canal, patrones = a["Type"], {}
            canales[canal] = []
        elif tipo == "Pattern":
            patron = a["Name"]
            patrones[patron] = []
        elif tipo == "Note" and "Value" in a and patron is not None:
            patrones[patron].append((int(a["Time"]), int(a["Duration"]) + 1, a["Value"], a.get("Instrument", "")))
        elif tipo == "PatternInstance":
            inicio = int(a["Time"]) * filas * fila
            canales[canal] += [(inicio + t, d, n, i) for t, d, n, i in patrones[a["Pattern"]]]
    compases = max((int(a) for a in re.findall(r'PatternInstance Time="(\d+)"', ruta.read_text())), default=0) + 1
    return {"titulo": titulo, "fila": fila, "total": compases * filas * fila, "instrumentos": instrumentos,
            "canales": canales}


def convertir(nombre: str, bucle: bool = False) -> None:
    datos = leer(AQUI / "nesband" / f"{nombre}.txt")
    instrumentos = {}
    for ins, volumen in datos["instrumentos"].items():
        if ins in SONIDOS:
            extra = max(0, round((VOLUMEN_REFERENCIA - volumen) * TL_POR_PASO))
            instrumentos[ins] = atenuar(SONIDOS[ins], extra)
    instrumentos.update(sonidos.BATERIA)
    cancion = Cancion(datos["titulo"], datos["fila"], instrumentos, mezcla={"fm2": 2})

    linea = nueva_linea()
    for canal, ch in CANALES.items():
        notas = sorted(datos["canales"].get(canal, []))
        faltan = {i for _, _, _, i in notas} - set(SONIDOS)
        if faltan:
            raise SystemExit(f"{nombre}: sin sonido FM para {', '.join(sorted(faltan))} (agregalo a SONIDOS)")
        tocar_fm(linea, cancion, ch, notas)
    bombos, ruido = [], []
    for cuadro, _, _, ins in datos["canales"].get("Noise", []):
        (bombos if ins == "Bombo" else ruido).append((cuadro, ins if ins in sonidos.BATERIA else "Platillo"))
    for cuadro, _, nota, _ in datos["canales"].get("DPCM", []):
        golpe = DPCM.get(nota)
        if golpe:
            (bombos if golpe == "Bombo" else ruido).append((cuadro, golpe))
    # Un golpe por cuadro en el ruido (si coinciden, gana el que mas se oye: tarola, abierto, platillo)
    prioridad = {"Tarola": 0, "Abierto": 1, "Platillo": 2}
    unicos: dict[int, str] = {}
    for cuadro, ins in ruido:
        if cuadro not in unicos or prioridad[ins] < prioridad[unicos[cuadro]]:
            unicos[cuadro] = ins
    tocar_bateria(linea, cancion, sorted(set(bombos)), sorted(unicos.items()))
    escribir_linea(linea, cancion, datos["total"], AQUI / f"{nombre}.vgm", bucle)


if __name__ == "__main__":
    nombres = sys.argv[1:] or sorted(p.stem for p in (AQUI / "nesband").glob("*.txt"))
    for n in nombres:
        convertir(n, bucle=n == "titulo")
