"""Proveedores falsos deterministas: todo funciona sin red, sin claves y sin GPU.

Transversal. Sirven para tests, para desarrollar los tres carriles en paralelo y como
"red de seguridad" en la demo (``BRIEFER_FALLBACK_TO_MOCK=true``).

- ``MockLLM``: con ``response_model`` devuelve una instancia válida (contenido de ejemplo
  realista para ``Analysis`` y ``PodcastScript``; relleno genérico para el resto). Sin él,
  devuelve un texto fijo.
- ``MockVision`` / ``MockSTT``: textos fijos.
- ``MockTTS``: escribe un WAV de silencio corto (stdlib ``wave``).
- ``MockImageGen``: escribe un PNG de color liso (stdlib ``zlib``/``struct``).
- ``MockImageClassifier``: distribución fija sobre las etiquetas.
"""

from __future__ import annotations

import hashlib
import struct
import types
import typing
import wave
import zlib
from datetime import date, datetime
from pathlib import Path

from pydantic import BaseModel

from briefer.costs import estimate_tokens
from briefer.providers.base import (
    ImageClassifier,
    ImageGenProvider,
    LLMProvider,
    STTProvider,
    TTSProvider,
    VisionProvider,
)
from briefer.schemas import DISCLAIMER_ES, Analysis, KeyPoint, PodcastScript, ScriptLine

FIXED_DATE = date(2026, 10, 5)
FIXED_DATETIME = datetime(2026, 10, 5, 9, 0, 0)


# ── Utilidades de ficheros (reutilizables en tests de otros módulos) ───────────────


def write_silence_wav(path: Path, duration_s: float = 0.5, sample_rate: int = 16_000) -> Path:
    """Escribe un WAV mono 16 bits de silencio."""
    path.parent.mkdir(parents=True, exist_ok=True)
    n_frames = max(1, int(duration_s * sample_rate))
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(b"\x00\x00" * n_frames)
    return path


def write_solid_png(path: Path, rgb: tuple[int, int, int] = (30, 60, 120), size: int = 64) -> Path:
    """Escribe un PNG RGB de color liso sin dependencias externas."""

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    raw = b"".join(b"\x00" + bytes(rgb) * size for _ in range(size))
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png)
    return path


# ── Generador genérico de instancias válidas ──────────────────────────────────────


def _fake_value(annotation: typing.Any, field_name: str = "campo") -> typing.Any:
    """Valor válido y determinista para una anotación de tipo."""
    origin = typing.get_origin(annotation)
    args = typing.get_args(annotation)
    if annotation is type(None):
        return None
    if origin is typing.Literal:
        return args[0]
    if origin is typing.Annotated:
        return _fake_value(args[0], field_name)
    if origin in (typing.Union, types.UnionType):
        non_none = [a for a in args if a is not type(None)]
        return _fake_value(non_none[0], field_name) if non_none else None
    if origin in (list, set, frozenset):
        return [_fake_value(args[0], field_name)] if args else []
    if origin is tuple:
        if len(args) == 2 and args[1] is Ellipsis:
            return (_fake_value(args[0], field_name),)
        return tuple(_fake_value(a, field_name) for a in args)
    if origin is dict:
        if len(args) == 2:
            return {_fake_value(args[0], "clave"): _fake_value(args[1], "valor")}
        return {}
    if isinstance(annotation, type):
        if issubclass(annotation, BaseModel):
            return fake_instance(annotation)
        if annotation is bool:
            return False
        if annotation is int:
            return 1
        if annotation is float:
            return 1.0
        if annotation is str:
            return f"{field_name} (mock)"
        if annotation is datetime:
            return FIXED_DATETIME
        if annotation is date:
            return FIXED_DATE
        if issubclass(annotation, Path):
            return Path("mock")
    return None


_M = typing.TypeVar("_M", bound=BaseModel)


def fake_instance(model: type[_M]) -> _M:
    """Instancia válida de cualquier modelo Pydantic (campos opcionales con su default)."""
    data = {
        name: _fake_value(info.annotation, name)
        for name, info in model.model_fields.items()
        if info.is_required()
    }
    return model.model_validate(data)


def sample_analysis() -> Analysis:
    """Análisis de ejemplo (contenido ficticio) para demos sin red."""
    return Analysis(
        date=FIXED_DATE,
        headline="[MOCK] Mercados mixtos: la banca sube y la tecnología se toma un respiro",
        key_points=[
            KeyPoint(
                title="La banca española, al alza",
                explanation="Noticia de ejemplo: los bancos suben tras unos resultados ficticios.",
                tickers=["SAN.MC", "BBVA.MC"],
                sentiment="positivo",
                sources=["ejemplo-001"],
            ),
            KeyPoint(
                title="Tecnología estadounidense, recogida de beneficios",
                explanation="Noticia de ejemplo: ligera caída de las grandes tecnológicas.",
                tickers=["AAPL", "NVDA"],
                sentiment="negativo",
                sources=["ejemplo-002"],
            ),
        ],
        market_mood="Neutral con sesgo prudente (datos simulados).",
        disclaimer=DISCLAIMER_ES,
    )


def sample_script() -> PodcastScript:
    """Guion de ejemplo a 2 voces."""
    lines = [
        ScriptLine(speaker="A", text="Buenos días, esto es Market Briefer, versión de pruebas."),
        ScriptLine(speaker="B", text="Hoy la banca española sube y la tecnología americana descansa."),
        ScriptLine(speaker="A", text="Recordad que todo esto son datos simulados."),
        ScriptLine(speaker="B", text="Y que no es asesoramiento financiero. ¡Hasta mañana!"),
    ]
    words = sum(len(line.text.split()) for line in lines)
    return PodcastScript(
        title="[MOCK] Market Briefer del día", lines=lines, est_duration_s=round(words / 2.5, 1)
    )


_CANNED: dict[type[BaseModel], typing.Callable[[], BaseModel]] = {
    Analysis: sample_analysis,
    PodcastScript: sample_script,
}


# ── Proveedores ───────────────────────────────────────────────────────────────────


class MockLLM(LLMProvider):
    provider_name = "mock"

    def __init__(self, settings: object | None = None, model: str = "mock-llm") -> None:
        super().__init__()
        self.model = model

    def complete(
        self,
        system: str,
        messages: list[dict],
        response_model: type[BaseModel] | None = None,
    ) -> str | BaseModel:
        prompt_text = system + "".join(str(m.get("content", "")) for m in messages)
        if response_model is None:
            last = str(messages[-1].get("content", "")) if messages else ""
            result: str | BaseModel = (
                "Respuesta simulada (mock). Pregunta recibida: "
                f"{last[:200]}. Esto no es asesoramiento financiero."
            )
            output_text = str(result)
        else:
            factory = _CANNED.get(response_model)
            result = factory() if factory else fake_instance(response_model)
            output_text = result.model_dump_json()
        self.last_usage = {
            "input_tokens": estimate_tokens(prompt_text),
            "output_tokens": estimate_tokens(output_text),
        }
        return result


class MockVision(VisionProvider):
    provider_name = "mock"

    def __init__(self, settings: object | None = None, model: str = "mock-vision") -> None:
        super().__init__()
        self.model = model

    def describe(self, image: bytes, prompt: str) -> str:
        self.last_usage = {"input_tokens": estimate_tokens(prompt) + 100, "output_tokens": 40}
        return (
            "[MOCK] Gráfico de velas diarias con tendencia alcista moderada; "
            f"imagen de {len(image)} bytes. Cifras clave: máximo 10,5; mínimo 9,8."
        )


class MockSTT(STTProvider):
    provider_name = "mock"

    def __init__(self, settings: object | None = None, model: str = "mock-stt") -> None:
        self.model = model

    def transcribe(self, audio_path: Path, language: str = "es") -> str:
        return "¿Por qué ha subido hoy el Santander?"


class MockTTS(TTSProvider):
    provider_name = "mock"
    audio_extension = ".wav"

    def __init__(self, settings: object | None = None, model: str = "mock-tts") -> None:
        self.model = model

    def synthesize(self, text: str, voice: str, out_path: Path) -> Path:
        # Duración proporcional al texto pero corta (máx. 3 s) para tests rápidos.
        duration = min(3.0, max(0.3, len(text) * 0.02))
        return write_silence_wav(Path(out_path).with_suffix(self.audio_extension), duration)


class MockImageGen(ImageGenProvider):
    provider_name = "mock"

    def __init__(self, settings: object | None = None, model: str = "mock-image") -> None:
        self.model = model

    def generate(self, prompt: str, out_path: Path) -> Path:
        digest = hashlib.md5(prompt.encode("utf-8")).digest()
        return write_solid_png(Path(out_path).with_suffix(".png"), (digest[0], digest[1], digest[2]))


class MockImageClassifier(ImageClassifier):
    provider_name = "mock"

    def __init__(self, settings: object | None = None, model: str = "mock-classifier") -> None:
        self.model = model

    def classify(self, image: bytes, labels: list[str]) -> dict[str, float]:
        if not labels:
            return {}
        if len(labels) == 1:
            return {labels[0]: 1.0}
        rest = 0.3 / (len(labels) - 1)
        return {label: (0.7 if i == 0 else rest) for i, label in enumerate(labels)}


__all__ = [
    "MockImageClassifier",
    "MockImageGen",
    "MockLLM",
    "MockSTT",
    "MockTTS",
    "MockVision",
    "fake_instance",
    "sample_analysis",
    "sample_script",
    "write_silence_wav",
    "write_solid_png",
]
