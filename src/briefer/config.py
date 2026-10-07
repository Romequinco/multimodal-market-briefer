"""Configuración centralizada (pydantic-settings): lee variables de entorno y ``.env``.

Transversal. Todas las variables están documentadas en ``.env.example``. Prioridad:
argumentos explícitos > variables de entorno > ``.env`` en la raíz del repo > valores por defecto.

Los valores por defecto del código son "seguros" (proveedores ``mock``) para que tests y
desarrollo funcionen sin red ni claves; ``.env.example`` propone la configuración real
del MVP (Claude + edge-tts + Whisper API).

Uso::

    from briefer.config import get_settings
    s = get_settings()
    s.briefer_llm_provider, s.default_tickers, s.output_path
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from briefer import brand

ROOT_DIR = Path(__file__).resolve().parents[2]

log = logging.getLogger("briefer.config")

LLMProviderName = Literal["anthropic", "gemini", "mock"]
VisionProviderName = Literal["claude", "mock"]
STTProviderName = Literal["whisper_api", "mock"]
TTSProviderName = Literal["edge", "gemini", "mock"]
ImageGenProviderName = Literal["gemini", "local", "sdxl_turbo", "none", "mock"]
ImageClassifierName = Literal["clip", "none", "mock"]

#: Proveedores retirados en v0.3.9 (eran *stubs* que lanzaban ``NotImplementedError``; quedan como
#: hoja de ruta en ``docs/05_roadmap_TODO.md``). Un ``.env`` antiguo que los nombre no rompe el
#: arranque: el campo cae a ``mock`` con un aviso en el log. Un nombre desconocido sí falla al validar.
RETIRED_PROVIDERS: dict[str, frozenset[str]] = {
    "briefer_llm_provider": frozenset({"openai"}),
    "briefer_vision_provider": frozenset({"qwen_local"}),
    "briefer_stt_provider": frozenset({"whisper_local"}),
    "briefer_tts_provider": frozenset({"elevenlabs"}),
}


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


class Settings(BaseSettings):
    """Variables de configuración. Los nombres coinciden (sin distinguir mayúsculas) con ``.env``."""

    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ── Claves de API (nunca se versionan) ──────────────────────────────────────
    anthropic_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None
    gemini_api_key: SecretStr | None = None

    # ── Acceso (despliegue público) ─────────────────────────────────────────────
    # Si tiene valor, la UI pide esta contraseña antes de activar el modo Real (el que gasta con las
    # claves de API); los modos demo siguen abiertos. Vacío = sin contraseña (uso en local).
    briefer_real_mode_password: SecretStr | None = None

    # ── Entrega ─────────────────────────────────────────────────────────────────
    telegram_bot_token: SecretStr | None = None
    telegram_chat_id: str | None = None

    # ── Selección de proveedores ────────────────────────────────────────────────
    briefer_llm_provider: LLMProviderName = "mock"
    briefer_vision_provider: VisionProviderName = "mock"
    briefer_stt_provider: STTProviderName = "mock"
    briefer_tts_provider: TTSProviderName = "mock"
    briefer_image_gen_provider: ImageGenProviderName = "none"
    briefer_image_classifier_provider: ImageClassifierName = "none"
    # Si falta una clave o una librería, usar el mock (con aviso en log) en vez de fallar.
    briefer_fallback_to_mock: bool = True

    @field_validator(*RETIRED_PROVIDERS, mode="before")
    @classmethod
    def _retired_provider_to_mock(cls, value: object, info: ValidationInfo) -> object:
        """Un proveedor retirado (antiguo *stub*) cae a ``mock`` con aviso, sin romper el arranque."""
        retired = RETIRED_PROVIDERS.get(info.field_name or "", frozenset())
        if isinstance(value, str) and value.strip().lower() in retired:
            log.warning(
                "%s=%s: proveedor retirado en v0.3.9 (no estaba implementado); se usa mock",
                (info.field_name or "").upper(), value.strip(),
            )
            return "mock"
        return value

    # ── Modelos ─────────────────────────────────────────────────────────────────
    briefer_llm_model: str = "claude-sonnet-5-5"
    briefer_llm_model_cheap: str = "claude-haiku-4-5-20251001"
    # Modelo del Agente Guionista (vacío = el barato). Evaluación del 06-oct: Haiku basta con
    # las puertas de calidad; Sonnet 5.5 escribe mejor pero cuesta ~2,7x (ver pipeline).
    briefer_scriptwriter_model: str = ""
    briefer_gemini_model: str = "gemini-2.5-flash"
    briefer_vision_model: str = "claude-sonnet-5-5"
    briefer_whisper_api_model: str = "gpt-4o-mini-transcribe"
    # Portada local y gratuita (BRIEFER_IMAGE_GEN_PROVIDER=local; «sdxl_turbo» es el alias antiguo):
    # modelo de Hugging Face para diffusers en CPU (SDXS, OpenRAIL++, 1 paso, ~1,8 GB). 0 = pasos del preset.
    briefer_sdxl_model: str = "IDKiro/sdxs-512-dreamshaper"
    briefer_sdxl_steps: int = 0
    # Portada con Gemini (BRIEFER_IMAGE_GEN_PROVIDER=gemini): el modelo de imagen más barato de la
    # API de Gemini (0,0336 $ por imagen 1K, precios oficiales consultados el 06-oct-2026).
    briefer_gemini_image_model: str = "gemini-3.1-flash-lite-image"
    briefer_clip_model: str = "openai/clip-vit-base-patch32"
    briefer_local_device: Literal["auto", "cpu", "cuda", "mps"] = "auto"

    # ── Idioma y voces ──────────────────────────────────────────────────────────
    briefer_language: str = "es"
    briefer_voice_a: str = "es-ES-AlvaroNeural"
    # Voz B: Ximena (cata a ciegas del 05-oct-2026, opción «B»: Álvaro + Ximena a +10 %).
    briefer_voice_b: str = "es-ES-XimenaNeural"
    # Locutores (marca Briefly): A = Toro (voz masculina), B = Osa (voz femenina).
    briefer_speaker_a_name: str = brand.SPEAKER_A_NAME
    briefer_speaker_b_name: str = brand.SPEAKER_B_NAME
    # Velocidad y tono de edge-tts: "+0%", "+8%", "-5%" / "+0Hz", "-2Hz". Por defecto +10 %
    # (opción «B» de la cata); vacío en .env = también +10 % (``EdgeTTS.DEFAULT_RATE``).
    briefer_tts_rate: str | None = "+10%"
    briefer_tts_pitch: str | None = None
    # Gemini TTS multi-locutor (opción «D», de pago: demo y pregenerado). Voces precompuestas de
    # Gemini; el Q&A hablado sigue con edge-tts aunque el podcast use Gemini (latencia).
    briefer_gemini_tts_model: str = "gemini-3.8-flash-tts"
    briefer_gemini_voice_a: str = "Puck"
    briefer_gemini_voice_b: str = "Kore"

    # ── Contenido ───────────────────────────────────────────────────────────────
    briefer_default_tickers: str = "SAN.MC,ITX.MC,IBE.MC,AAPL,NVDA"
    # Índices de contexto: se piden sus precios y noticias, pero no cuentan como tickers del usuario.
    briefer_context_tickers: str = "^IBEX,^GSPC"
    briefer_news_rss_feeds: str = ""
    briefer_news_max_items: int = 20
    # «Impacto de la noticia» con FinBERT (Haiku traduce + FinBERT clasifica). Requiere requirements-local.txt.
    briefer_finbert: bool = False
    briefer_podcast_target_minutes: float = 4.0
    # Verificar el podcast final con el STT (WER frente al guion) en modo real
    # (≈0,015 € por episodio de 5 min con gpt-4o-mini-transcribe; 0,03 € con whisper-1).
    briefer_verify_podcast: bool = True
    # Tema de los gráficos PNG: "dark" (a juego con la UI) | "light" (impresión).
    briefer_chart_theme: Literal["dark", "light"] = "dark"

    # ── Rutas (relativas a la raíz del repo si no son absolutas) ────────────────
    briefer_data_dir: Path = Path("data")
    briefer_cache_dir: Path = Path("data/cache")
    briefer_output_dir: Path = Path("data/outputs")
    briefer_samples_dir: Path = Path("data/samples")

    briefer_log_level: str = "INFO"

    # ── Helpers ─────────────────────────────────────────────────────────────────
    def has_secret(self, field_name: str) -> bool:
        """True si el campo existe y tiene un valor no vacío (SecretStr o str)."""
        value = getattr(self, field_name, None)
        if value is None:
            return False
        if isinstance(value, SecretStr):
            value = value.get_secret_value()
        return bool(str(value).strip())

    @staticmethod
    def _resolve(path: Path) -> Path:
        return path if path.is_absolute() else ROOT_DIR / path

    @property
    def default_tickers(self) -> list[str]:
        return [t.upper() for t in _split_csv(self.briefer_default_tickers)]

    @property
    def context_tickers(self) -> list[str]:
        """Índices de referencia (``^IBEX``, ``^GSPC``) que acompañan a todo briefing."""
        return [t.upper() for t in _split_csv(self.briefer_context_tickers)]

    @property
    def rss_feeds(self) -> list[str]:
        return _split_csv(self.briefer_news_rss_feeds)


    @property
    def data_path(self) -> Path:
        return self._resolve(self.briefer_data_dir)

    @property
    def cache_path(self) -> Path:
        return self._resolve(self.briefer_cache_dir)

    @property
    def output_path(self) -> Path:
        return self._resolve(self.briefer_output_dir)

    @property
    def samples_path(self) -> Path:
        return self._resolve(self.briefer_samples_dir)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Settings cacheados (una lectura de ``.env`` por proceso)."""
    return Settings()


def reset_settings_cache() -> None:
    """Fuerza a releer la configuración (útil en tests o tras editar ``.env``)."""
    get_settings.cache_clear()
