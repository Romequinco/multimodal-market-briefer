"""Regenera solo los audios del ejemplo preparado (edge-tts, sin claves de IA).

Uso: python scripts/generar_ejemplo_qa.py
Requiere conexión al regenerar; reproducir los MP3 incluidos funciona sin red.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from briefer.media.podcast import tag_audio
from briefer.media.speech import normalize_for_speech
from briefer.providers.tts.edge_tts_provider import EdgeTTS


def main() -> None:
    folder = ROOT / "data" / "samples" / "qa_example"
    data = json.loads((folder / "conversation.json").read_text(encoding="utf-8"))
    tts = EdgeTTS(retries=1, receive_timeout=30)
    for answer in data["answers"]:
        output = (folder / answer["audio_path"]).resolve()
        if not output.is_relative_to(folder.resolve()):
            raise ValueError("El audio debe permanecer en la carpeta del ejemplo.")
        speech = normalize_for_speech(answer["answer_text"])
        path = tts.synthesize(speech, "es-ES-XimenaNeural", output)
        tag_audio(path)
        print(f"Guardado: {path.name}", flush=True)


if __name__ == "__main__":
    main()
