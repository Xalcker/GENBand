"""Arreglo para la Genesis de una canción de otra consola: sus notas (JSON) a un VGM con sonidos FM.

Las notas salen de GBBand (`gbband export-notes`, de un NSF, un VGM de Game Boy o un GBS): tres canales tonales y la
batería ya clasificada por papeles. Como en nesband_fm.py, cada canal tonal va a un canal FM con el mismo papel del que
salen los charts, y el volumen de cada nota (0-15) se vuelve atenuación de los operadores portadores:

    pulso 1   -> FM 1 (guitarra)        pulso 2 -> FM 2 (teclado)        triángulo -> FM 3 (bajo)
    batería   -> el bombo al FM 6; la tarola, los toms y los platillos al ruido del PSG

Hay varios timbres (TIMBRES) porque cada uno le queda mejor a distintas canciones; --timbre todos saca uno por cada
uno (el A con el nombre tal cual, los demás con _b, _c...), para comparar en el editor.

Uso (desde la raíz del repositorio):

    uv run gbband export-notes "songs_src/Juego.nsf" --track 2 --out notas.json      (en ../GBBand)
    uv run python audio/arreglo_fm.py notas.json --nombre juego_area1 [--timbre A|B|todos] [--importar]

Deja songs_src/arreglos/<nombre>.vgm (songs_src/ no va a git: es música de otros) y, con --importar, lo importa con
genband import-song (cada instrumento en su canal FM y la batería en el FM 6 y el ruido).
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

import sonidos
from compose import PORTADORES, Cancion, escribir_linea, nombre, nueva_linea, tocar_bateria, tocar_fm

AQUI = Path(__file__).parent
RAIZ = AQUI.parent

# Sonido de pulso 1, pulso 2 y triángulo (nombres de sonidos.py)
TIMBRES = {
    "A": ("GUITARRA", "PIANO", "BAJO"),  # más "banda": guitarra distorsionada y piano
    "B": ("SIERRA", "PULSADA", "BAJO"),  # más cerca del pulso del NES
}
CANALES = ("Square1", "Square2", "Triangle")  # canal de origen -> FM 1, 2 y 3

VOLUMEN_REFERENCIA = 13  # el volumen de origen (0-15) que suena sin atenuar
TL_POR_PASO = 1.5  # atenuación (en pasos de TL, 0.75 dB) por cada paso de volumen
GOLPE = {"snare": "Tarola", "tom1": "Platillo", "tom2": "Abierto", "tom3": "Abierto"}  # papel -> sonido del ruido
PRIORIDAD = {"Tarola": 0, "Abierto": 1, "Platillo": 2}  # un golpe por cuadro en el ruido: gana el que más se oye


def atenuado(sonido, extra: int):
    """El mismo sonido con los portadores más bajos."""
    ops = tuple(replace(op, tl=min(127, op.tl + extra)) if i in PORTADORES[sonido.alg] else op
                for i, op in enumerate(sonido.ops))
    return replace(sonido, ops=ops)


def arreglar(datos: dict, timbre: str, ruta: Path) -> None:
    instrumentos = dict(sonidos.BATERIA)
    linea = nueva_linea()
    notas_por_canal = []
    for canal, base in zip(CANALES, TIMBRES[timbre]):
        sonido = getattr(sonidos, base)
        notas = []
        for cuadro, cuadros, altura, volumen in datos["channels"].get(canal, []):
            if volumen <= 0:
                continue
            extra = max(0, round((VOLUMEN_REFERENCIA - volumen) * TL_POR_PASO))
            clave = f"{canal}_{extra}"
            if clave not in instrumentos:
                instrumentos[clave] = atenuado(sonido, extra)
            # La tecla se suelta un cuadro antes del final: una nota necesita al menos 2 cuadros para sonar
            notas.append((cuadro, max(2, cuadros), nombre(altura), clave))
        notas_por_canal.append(notas)
    autor = f"arreglo de {datos['game']}" if datos.get("game") else "arreglo"
    cancion = Cancion(datos["title"], 6, instrumentos, mezcla={"fm2": 2}, autor=autor)
    for ch, notas in enumerate(notas_por_canal):
        tocar_fm(linea, cancion, ch, notas)
    bombos, ruido = [], {}
    for cuadro, papel, platillo in datos["drums"]:
        if papel == "kick":
            bombos.append((cuadro, "Bombo"))
            continue
        golpe = "Platillo" if platillo else GOLPE.get(papel, "Tarola")
        if cuadro not in ruido or PRIORIDAD[golpe] < PRIORIDAD[ruido[cuadro]]:
            ruido[cuadro] = golpe
    tocar_bateria(linea, cancion, sorted(set(bombos)), sorted(ruido.items()))
    ruta.parent.mkdir(parents=True, exist_ok=True)
    escribir_linea(linea, cancion, datos["frames"], ruta)


def importar(ruta: Path, nombre_cancion: str, titulo: str, juego: str) -> None:
    sys.path.insert(0, str(RAIZ / "pctools"))
    from genband_tools import cli

    cli.import_song({"name": nombre_cancion, "source": ruta.relative_to(RAIZ).as_posix(), "title": titulo, "game": juego,
                     "guitarra": "fm1", "teclado": "fm2", "bajo": "fm3", cli.DRUMS: "fm6,ruido"})


def main() -> None:
    p = argparse.ArgumentParser(description="arreglo FM de las notas de otra consola (de gbband export-notes)")
    p.add_argument("notas", type=Path)
    p.add_argument("--nombre", required=True, help="identificador de la canción (minúsculas, números y _)")
    p.add_argument("--timbre", default="A", choices=[*TIMBRES, "todos"])
    p.add_argument("--importar", action="store_true", help="importarla con genband import-song")
    args = p.parse_args()
    datos = json.loads(args.notas.read_text(encoding="utf-8"))
    timbres = list(TIMBRES) if args.timbre == "todos" else [args.timbre]
    for timbre in timbres:
        sufijo = "" if timbre == "A" else f"_{timbre.lower()}"
        titulo = datos["title"] + ("" if timbre == "A" else f" ({timbre})")
        ruta = RAIZ / "songs_src" / "arreglos" / f"{args.nombre}{sufijo}.vgm"
        arreglar(datos, timbre, ruta)
        print(f"  timbre {timbre}: {', '.join(TIMBRES[timbre])}")
        if args.importar:
            importar(ruta, args.nombre + sufijo, titulo, datos.get("game") or "")


if __name__ == "__main__":
    main()
