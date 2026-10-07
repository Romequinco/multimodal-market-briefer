"""Registro de proveedores: elige la implementación según ``.env`` (ver ADR-002).

Transversal. ``mock`` siempre está disponible. Las implementaciones reales se importan de
forma **perezosa** (``importlib``) para que no haga falta instalar ``torch``, ``anthropic``…
si no se usan.

Si falta una clave o una librería y ``BRIEFER_FALLBACK_TO_MOCK=true``, se devuelve el mock
con un aviso en el log; si es ``false``, se lanza ``ProviderConfigError``.

Solo se registran proveedores **implementados** (v0.3.9: fuera los *stubs* ``openai`` LLM,
``qwen_local``, ``whisper_local`` y ``elevenlabs``; ver ``config.RETIRED_PROVIDERS``).

Uso::

    from briefer.providers import registry
    llm = registry.get_llm()                # según BRIEFER_LLM_PROVIDER
    cheap = registry.get_llm(cheap=True)    # modelo barato (Haiku) si el proveedor lo admite
    tts = registry.get_tts(force_mock=True) # mock explícito (tests / modo demo offline)
"""

from __future__ import annotations

import importlib
from collections.abc import Callable
from typing import Any, TypeVar

from briefer.config import Settings, get_settings
from briefer.logging_utils import get_logger
from briefer.providers import mock
from briefer.providers.base import (
    ImageClassifier,
    ImageGenProvider,
    LLMProvider,
    STTProvider,
    TTSProvider,
    VisionProvider,
)

log = get_logger("providers.registry")

T = TypeVar("T")

# nombre -> (módulo, clase, campo de Settings con la clave requerida o None)
_Spec = tuple[str, str, str | None]

LLM_IMPLS: dict[str, _Spec] = {
    "anthropic": ("briefer.providers.llm.anthropic_llm", "AnthropicLLM", "anthropic_api_key"),
    "gemini": ("briefer.providers.llm.gemini_llm", "GeminiLLM", "gemini_api_key"),
}
VISION_IMPLS: dict[str, _Spec] = {
    "claude": ("briefer.providers.vision.claude_vision", "ClaudeVision", "anthropic_api_key"),
}
STT_IMPLS: dict[str, _Spec] = {
    "whisper_api": ("briefer.providers.stt.whisper_api", "WhisperAPI", "openai_api_key"),
}
TTS_IMPLS: dict[str, _Spec] = {
    "edge": ("briefer.providers.tts.edge_tts_provider", "EdgeTTS", None),
    "gemini": ("briefer.providers.tts.gemini_tts", "GeminiTTS", "gemini_api_key"),
}
IMAGE_GEN_IMPLS: dict[str, _Spec] = {
    "gemini": ("briefer.providers.image.gemini_image", "GeminiImage", "gemini_api_key"),
    "local": ("briefer.providers.image.sdxl_turbo", "SDXLTurbo", None),
    "sdxl_turbo": ("briefer.providers.image.sdxl_turbo", "SDXLTurbo", None),  # alias antiguo
}
IMAGE_CLASSIFIER_IMPLS: dict[str, _Spec] = {
    "clip": ("briefer.providers.image.clip_classifier", "CLIPClassifier", None),
}


class ProviderConfigError(RuntimeError):
    """Proveedor desconocido, sin clave o con dependencias no instaladas."""


def _build(
    kind: str,
    name: str,
    table: dict[str, _Spec],
    mock_factory: Callable[[], T],
    settings: Settings,
    **kwargs: Any,
) -> T:
    if name == "mock":
        return mock_factory()
    if name not in table:
        raise ProviderConfigError(f"Proveedor de {kind} desconocido: {name!r}")
    module_path, class_name, secret_field = table[name]
    try:
        if secret_field and not settings.has_secret(secret_field):
            raise ProviderConfigError(
                f"Falta {secret_field.upper()} en .env para {kind}={name!r}"
            )
        module = importlib.import_module(module_path)
        cls = getattr(module, class_name)
        return cls(settings, **kwargs)
    except (ProviderConfigError, ImportError) as exc:
        if settings.briefer_fallback_to_mock:
            log.warning("%s: usando mock en lugar de %r (%s)", kind, name, exc)
            return mock_factory()
        if isinstance(exc, ProviderConfigError):
            raise
        raise ProviderConfigError(f"No se pudo cargar {kind}={name!r}: {exc}") from exc


def get_llm(
    settings: Settings | None = None, *, cheap: bool = False, force_mock: bool = False
) -> LLMProvider:
    """LLM según ``BRIEFER_LLM_PROVIDER``. ``cheap=True`` pide el modelo barato."""
    s = settings or get_settings()
    name = "mock" if force_mock else s.briefer_llm_provider
    return _build(
        "llm",
        name,
        LLM_IMPLS,
        lambda: mock.MockLLM(model="mock-llm-cheap" if cheap else "mock-llm"),
        s,
        cheap=cheap,
    )


def get_vision(settings: Settings | None = None, *, force_mock: bool = False) -> VisionProvider:
    """Visión según ``BRIEFER_VISION_PROVIDER``."""
    s = settings or get_settings()
    name = "mock" if force_mock else s.briefer_vision_provider
    return _build("vision", name, VISION_IMPLS, mock.MockVision, s)


def get_stt(settings: Settings | None = None, *, force_mock: bool = False) -> STTProvider:
    """Voz a texto según ``BRIEFER_STT_PROVIDER``."""
    s = settings or get_settings()
    name = "mock" if force_mock else s.briefer_stt_provider
    return _build("stt", name, STT_IMPLS, mock.MockSTT, s)


def get_tts(settings: Settings | None = None, *, force_mock: bool = False) -> TTSProvider:
    """Texto a voz según ``BRIEFER_TTS_PROVIDER``."""
    s = settings or get_settings()
    name = "mock" if force_mock else s.briefer_tts_provider
    return _build("tts", name, TTS_IMPLS, mock.MockTTS, s)


def get_image_gen(
    settings: Settings | None = None, *, force_mock: bool = False
) -> ImageGenProvider | None:
    """Texto a imagen según ``BRIEFER_IMAGE_GEN_PROVIDER``; ``None`` si es ``none``."""
    s = settings or get_settings()
    name = "mock" if force_mock else s.briefer_image_gen_provider
    if name == "none":
        return None
    return _build("image_gen", name, IMAGE_GEN_IMPLS, mock.MockImageGen, s)


def get_image_classifier(
    settings: Settings | None = None, *, force_mock: bool = False
) -> ImageClassifier | None:
    """Clasificador zero-shot según ``BRIEFER_IMAGE_CLASSIFIER_PROVIDER``; ``None`` si es ``none``."""
    s = settings or get_settings()
    name = "mock" if force_mock else s.briefer_image_classifier_provider
    if name == "none":
        return None
    return _build("image_classifier", name, IMAGE_CLASSIFIER_IMPLS, mock.MockImageClassifier, s)


def describe_providers(settings: Settings | None = None) -> dict[str, str]:
    """Resumen de la configuración activa (para el chip del modo de la UI)."""
    s = settings or get_settings()
    return {
        "LLM": f"{s.briefer_llm_provider} ({s.briefer_llm_model})",
        "Visión": s.briefer_vision_provider,
        "Voz a texto": s.briefer_stt_provider,
        "Texto a voz": s.briefer_tts_provider,
        "Imagen": s.briefer_image_gen_provider,
        "Clasificador": s.briefer_image_classifier_provider,
        "Fallback a mock": "sí" if s.briefer_fallback_to_mock else "no",
    }


__all__ = [
    "ProviderConfigError",
    "describe_providers",
    "get_image_classifier",
    "get_image_gen",
    "get_llm",
    "get_stt",
    "get_tts",
    "get_vision",
]
