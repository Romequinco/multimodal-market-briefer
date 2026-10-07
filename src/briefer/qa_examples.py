"""Conversación preparada y audios incluidos para explorar Q&A sin red ni claves."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict

from briefer.config import get_settings
from briefer.schemas import Briefing, QAAnswer


class RecordedQAExample(BaseModel):
    """El contexto del ejemplo es independiente del briefing activo de la sesión."""

    model_config = ConfigDict(extra="forbid")
    briefing: Briefing
    answers: list[QAAnswer]


def load_qa_example(samples_dir: Path | None = None) -> RecordedQAExample | None:
    """Carga texto y rutas portables. Nunca llama a proveedores ni genera voz.

    Un audio ausente deja disponible el texto; rutas fuera de la carpeta se rechazan.
    """
    folder = (samples_dir or get_settings().samples_path) / "qa_example"
    manifest = folder / "conversation.json"
    if not manifest.is_file():
        return None
    example = RecordedQAExample.model_validate_json(manifest.read_text(encoding="utf-8-sig"))
    for answer in example.answers:
        if answer.audio_path is not None:
            path = (folder / answer.audio_path).resolve()
            if not path.is_relative_to(folder.resolve()):
                raise ValueError("El audio del ejemplo debe estar dentro de su carpeta.")
            answer.audio_path = path if path.is_file() else None
    return example
