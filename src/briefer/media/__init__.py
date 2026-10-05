"""Salidas multimedia (carril C).

- ``charts``     -> ``list[ChartAsset]`` (PNG con matplotlib)
- ``podcast``    -> ``AudioAsset`` (TTS por línea con 2 voces + concatenación)
- ``transcript`` -> ``Transcript`` (+ fichero SRT)
- ``cover``      -> portada PNG opcional (texto a imagen, notebook 4)
- ``video``      -> ``VideoAsset`` (moviepy + ffmpeg: imágenes + audio + subtítulos)

Todas las librerías pesadas (matplotlib, moviepy…) se importan dentro de las funciones.
"""
