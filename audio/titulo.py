"""Musica del titulo de GENBand: la misma de NESBand (y GBBand), 8 compases en La menor (150 BPM) que se repiten.

El proyecto de FamiStudio de NESBand esta en audio/nesband/titulo.txt; nesband_fm.py lo pasa a FM como las
canciones, pero en bucle.

Uso (desde la raiz del repositorio):  uv run genband build-audio
(corre este archivo, que deja audio/titulo.vgm, y lo convierte a src/titulo_music.c)
"""

from nesband_fm import convertir

convertir("titulo", bucle=True)
