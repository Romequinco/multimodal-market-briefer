"""Orquestación de extremo a extremo: entradas -> agentes -> salidas -> entrega.

Carril B. Es la única pieza que conoce a todos los módulos; la UI (``app/``) y el CLI
(``scripts/demo.py``) solo llaman a ``run_briefing`` y ``answer_question``.

Pasos de ``run_briefing`` (cada uno registra un ``StepMetric`` con latencia y coste):
1. ``ingest.news`` + ``ingest.tickers.filter_by_tickers`` + ``ingest.prices``      [núcleo]
2. ``ingest.pdf`` / ``ingest.chart`` / ``ingest.voice`` -> ``DocumentInsight``      [opcional, uno por subida]
3. ``MarketContext`` -> ``agents.analyst`` -> ``Analysis``                          [núcleo]
4. ``agents.scriptwriter`` -> ``PodcastScript``                                     [núcleo]
5. ``media.podcast`` -> ``AudioAsset``; ``media.transcript`` -> ``Transcript``      [núcleo]
   ``media.verify``: STT del MP3 final y WER frente al guion (solo modo real, en paralelo
   con 6-7; ``BRIEFER_VERIFY_PODCAST``)                                          [opcional]
6. ``media.charts`` -> ``ChartAsset`` [núcleo]; ``media.cover``                     [opcional]
7. ``media.video`` -> ``VideoAsset``                                                [opcional]
8. ``delivery.<canal>`` -> ``DeliveryResult``; ``storage.save``                     [opcionales]

Tolerancia a fallos:
- Un paso **opcional** que falla no rompe el briefing: su ``StepMetric`` queda marcado como
  fallido (campo ``StepMetric.error``, ver ``logging_utils.step_failed``), se registra en el log y se sigue. En la
  entrega, además, el canal aparece en ``Briefing.deliveries`` con ``ok=False``.
- Un paso **núcleo** con proveedor real que falla (tras los reintentos del SDK) se repite con
  un **sustituto** si ``BRIEFER_FALLBACK_TO_MOCK=true``: LLM/TTS mock, noticias de
  ``data/samples`` o precios sintéticos. El ``StepMetric`` queda con ``provider`` = sustituto y
  ``error = "Fallback a <sustituto> tras <Tipo>: <mensaje>"`` (``logging_utils.step_fell_back``)
  para que la UI avise de que ese paso usó datos simulados. El Guionista tiene además su propio
  respaldo determinista (``fallback_script``), marcado igual. Si el podcast usa **Gemini TTS**
  (``BRIEFER_TTS_PROVIDER=gemini``, de pago) y falla, el sustituto es **edge-tts** (opción «B»,
  gratis; ``podcast_tts_fallback``), y el Q&A hablado usa siempre edge-tts (``qa_tts``).
- Si no hay sustituto (pasos locales, modo mock o fallback desactivado), el paso núcleo lanza
  ``PipelineStepError`` (o ``StepNotImplementedError``, que además es ``NotImplementedError``
  para que la UI lo muestre como «Pendiente») con el nombre del paso y la causa encadenada.

Concurrencia: noticias, precios y las subidas del usuario (PDF, gráfico, voz) se procesan en
paralelo (``ThreadPoolExecutor``); la latencia de la ingesta es ≈ la del más lento y se ve en la
traza (``StepMetric`` de cada uno). El podcast sintetiza ``PODCAST_TTS_WORKERS`` líneas a la vez.
El Guionista y el Q&A usan el LLM barato (``providers.llm_cheap``, Haiku).

Modos de ejecución (``mode``; ``use_mock=True`` equivale a ``mode="mock"``):

- ``"real"``: proveedores de ``.env``, noticias y precios reales (con caché diaria; ``use_cache=False``
  la ignora y la refresca).
- ``"mock"``: todos los proveedores de IA son mocks y las noticias/precios salen de ``data/samples``
  / datos sintéticos (sin red ni claves). El audio es un WAV mudo.
- ``"demo_voices"``: como ``"mock"`` pero el podcast y la respuesta del Q&A se sintetizan con
  **edge-tts real** (gratis, sin clave; necesita red). Si edge-tts no responde, cae al TTS mock
  (marcado como fallback). Es la demo «sin claves» que no suena a silencio.

Índices de contexto (``settings.context_tickers``, por defecto ``^IBEX`` y ``^GSPC``): se piden sus
precios y noticias junto a los del usuario, pero no cuentan como tickers del usuario
(``MarketContext.tickers``); salen en el gráfico de variación del día, no con gráfico propio.
"""

from __future__ import annotations

import functools
import importlib
import json
import time
from collections.abc import Callable, Iterator, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from typing import Literal, TypeVar, cast, get_args

from pydantic import BaseModel, ValidationError

from briefer import costs, storage
from briefer.agents import analyst, qa, scriptwriter
from briefer.config import Settings, get_settings
from briefer.delivery import telegram_sender
from briefer.ingest import chart_reader, pdf_reader, voice
from briefer.ingest import news as news_mod
from briefer.ingest import portfolio as portfolio_mod
from briefer.ingest import prices as prices_mod
from briefer.ingest import sentiment as sentiment_mod
from briefer.ingest import tickers as tickers_mod
from briefer.logging_utils import StepHandle, error_text, fallback_error, get_logger, step_error, track_step
from briefer.media import charts as charts_mod
from briefer.media import cover as cover_mod
from briefer.media import podcast
from briefer.media import transcript as transcript_mod
from briefer.media import video as video_mod
from briefer.media.speech import normalize_for_speech
from briefer.providers import registry
from briefer.providers.base import (
    ImageClassifier,
    ImageGenProvider,
    LLMProvider,
    STTProvider,
    TTSProvider,
    VisionProvider,
)
from briefer.schemas import (
    Analysis,
    AudioAsset,
    Briefing,
    DeliveryResult,
    DocumentInsight,
    MarketContext,
    PodcastScript,
    Portfolio,
    QAAnswer,
    StepMetric,
    new_briefing_id,
)

log = get_logger("pipeline")

PDF_EXTS = {".pdf"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
AUDIO_EXTS = {".wav", ".mp3", ".m4a", ".ogg", ".webm", ".flac"}

#: Canales de entrega extra admitidos en ``run_briefing(deliver=...)`` ("web" siempre va incluido).
DELIVERY_CHANNELS: tuple[str, ...] = ("telegram",)

ProgressFn = Callable[[str], None]
T = TypeVar("T")

#: Modo de ejecución del pipeline (ver docstring del módulo).
RunMode = Literal["real", "mock", "demo_voices"]
RUN_MODES: tuple[str, ...] = get_args(RunMode)
#: Hilos de síntesis del podcast (edge-tts es I/O: 6 líneas a la vez bajan la latencia sin saturar).
PODCAST_TTS_WORKERS = 6
#: Subidas (PDF, gráfico, voz) procesadas a la vez, en paralelo también con noticias y precios.
UPLOAD_WORKERS = 4


def resolve_mode(mode: str | None = None, use_mock: bool = False) -> str:
    """Normaliza ``mode``/``use_mock``: ``mode`` manda si se indica; si no, ``use_mock`` -> ``"mock"``.

    Raises:
        ValueError: modo desconocido.
    """
    if mode is None:
        return "mock" if use_mock else "real"
    value = str(mode).strip().lower()
    if value not in RUN_MODES:
        raise ValueError(f"Modo desconocido: {mode!r}. Válidos: {', '.join(RUN_MODES)}.")
    return value


# ── Errores ───────────────────────────────────────────────────────────────────────


class PipelineStepError(RuntimeError):
    """Fallo de un paso núcleo del pipeline. ``step`` es el nombre del paso; la causa
    original queda en ``__cause__``."""

    def __init__(self, step: str, cause: BaseException) -> None:
        self.step = step
        #: Pasos ejecutados hasta el fallo (latencia y coste ya gastado); lo rellenan
        #: ``run_briefing`` / ``answer_question`` antes de propagar el error.
        self.metrics: list[StepMetric] = []
        # Mensaje redactado (``logging_utils.error_text``): nunca claves ni tokens en la UI.
        super().__init__(f"Falló el paso «{step}»: {error_text(cause, 300)}")


class StepNotImplementedError(PipelineStepError, NotImplementedError):
    """Paso núcleo aún sin implementar (la UI lo trata como «Pendiente»)."""


# ── Proveedores ───────────────────────────────────────────────────────────────────


@dataclass
class Providers:
    """Proveedores resueltos para una ejecución."""

    llm: LLMProvider
    llm_cheap: LLMProvider
    vision: VisionProvider
    stt: STTProvider
    tts: TTSProvider
    image_gen: ImageGenProvider | None
    classifier: ImageClassifier | None


def demo_voice_tts(settings: Settings) -> TTSProvider:
    """TTS del modo ``demo_voices``: edge-tts real (no necesita clave), con rate/pitch de ``settings``."""
    return registry.get_tts(settings.model_copy(update={"briefer_tts_provider": "edge"}))


#: TTS que sintetizan el podcast en tramos de diálogo largos (de pago, lentos por petición): el
#: Q&A hablado no los usa (objetivo < 10 s) y, si fallan, el podcast cae a edge-tts.
DIALOGUE_TTS_PROVIDERS = frozenset({"gemini"})


def qa_tts(settings: Settings, tts: TTSProvider) -> TTSProvider:
    """TTS de la respuesta hablada del Q&A.

    Con Gemini como TTS del podcast, la respuesta sigue saliendo por **edge-tts** (opción «B»,
    voz B = Osa, la misma que en el resto de modos): una petición a Gemini TTS tarda varios
    segundos más y rompería el objetivo de < 10 s; además es gratis. Resto: el mismo ``tts``.
    """
    if tts.provider_name in DIALOGUE_TTS_PROVIDERS:
        return demo_voice_tts(settings)
    return tts


def podcast_tts_retries(tts: TTSProvider) -> int:
    """Reintentos por línea/tramo en ``synthesize_podcast``: 0 con edge-tts (ya reintenta dentro;
    sin anidar 3×3 intentos el paso cae antes al sustituto), 1 con Gemini (el SDK ya reintenta
    429/5xx; el reintento cubre audios cortados) y 2 en el resto."""
    if tts.provider_name == "edge":
        return 0
    if tts.provider_name in DIALOGUE_TTS_PROVIDERS:
        return 1
    return 2


def tts_cost_eur(tts: TTSProvider, n_chars: int, usage_before: dict[str, int] | None = None) -> tuple[float, str | None]:
    """Coste estimado del podcast y nota para ``StepMetric.detail``.

    Si el proveedor factura por tokens (Gemini TTS: ``last_usage`` con tokens de texto de entrada
    y de audio de salida) se usa la diferencia de ``last_usage`` desde ``usage_before``; si no,
    los caracteres del guion (``n_chars``).
    """
    usage = getattr(tts, "last_usage", None)
    if isinstance(usage, dict) and tts.provider_name in DIALOGUE_TTS_PROVIDERS:
        before = usage_before or {}
        delta = {k: int(usage.get(k, 0)) - int(before.get(k, 0)) for k in ("input_tokens", "output_tokens")}
        cost = costs.estimate_cost_eur(tts.provider_name, tts.model, **delta)
        note = (f"{tts.provider_name} TTS: {delta['input_tokens']} tokens de texto, "
                f"{delta['output_tokens']} tokens de audio (coste estimado)")
        return cost, note
    return costs.estimate_cost_eur(tts.provider_name, tts.model, n_chars=n_chars), None


def podcast_tts_fallback(
    settings: Settings,
    tts: TTSProvider,
    podcast_with: Callable[[TTSProvider], Callable[[StepHandle], AudioAsset]],
) -> _Fallback | None:
    """Sustituto del paso ``media.podcast``.

    - TTS de diálogo (Gemini): **edge-tts** opción «B» (siempre, es gratis y real); si edge-tts
      tampoco responde y ``BRIEFER_FALLBACK_TO_MOCK=true``, ``MockTTS`` (anotado en ``detail``).
    - Otro TTS real: ``MockTTS`` si ``BRIEFER_FALLBACK_TO_MOCK=true``.
    """
    mock_tts = registry.get_tts(settings, force_mock=True) if settings.briefer_fallback_to_mock else None
    if tts.provider_name in DIALOGUE_TTS_PROVIDERS:
        edge = demo_voice_tts(settings)
        edge_run = podcast_with(edge)
        mock_run = podcast_with(mock_tts) if mock_tts is not None and edge.provider_name != "mock" else None

        def run(step: StepHandle) -> AudioAsset:
            try:
                return edge_run(step)
            except Exception as exc:
                if mock_run is None or mock_tts is None:
                    raise
                log.warning("media.podcast: edge-tts tampoco respondió (%s); se usa el TTS mock", error_text(exc))
                step.provider, step.model = mock_tts.provider_name, mock_tts.model
                step.detail = _join_details(step.detail, f"edge-tts tampoco respondió ({error_text(exc)}); TTS mock")
                return mock_run(step)

        return _Fallback(edge.provider_name, edge.model, run, "edge-tts" if edge.provider_name == "edge" else "mock")
    if mock_tts is not None and tts.provider_name != "mock":
        return _Fallback(mock_tts.provider_name, mock_tts.model, podcast_with(mock_tts), "mock")
    return None


def _providers_for_mode(settings: Settings, mode: str) -> Providers:
    """Proveedores de un modo: mocks fuera de ``"real"``; en ``"demo_voices"`` el TTS es edge-tts."""
    providers = get_providers(settings, use_mock=mode != "real")
    if mode == "demo_voices":
        providers.tts = demo_voice_tts(settings)
    return providers


def get_providers(settings: Settings, use_mock: bool = False) -> Providers:
    """Resuelve todos los proveedores vía ``registry`` (``use_mock`` fuerza mocks)."""
    return Providers(
        llm=registry.get_llm(settings, force_mock=use_mock),
        llm_cheap=registry.get_llm(settings, cheap=True, force_mock=use_mock),
        vision=registry.get_vision(settings, force_mock=use_mock),
        stt=registry.get_stt(settings, force_mock=use_mock),
        tts=registry.get_tts(settings, force_mock=use_mock),
        image_gen=registry.get_image_gen(settings, force_mock=use_mock),
        classifier=registry.get_image_classifier(settings, force_mock=use_mock),
    )


def scriptwriter_llm(settings: Settings, providers: Providers) -> LLMProvider:
    """LLM del Guionista: el barato salvo que ``BRIEFER_SCRIPTWRITER_MODEL`` indique otro modelo
    (p. ej. ``claude-sonnet-5-5``). En mock no cambia nada.

    Decisión del 05-oct-2026 (2 guiones Haiku frente a 2 Sonnet sobre el mismo análisis real):
    Haiku 4.5 ≈ 0,009 € y Sonnet 5.5 ≈ 0,024-0,026 € por guion con latencias parecidas
    (15-20 s); con las puertas de calidad (cobertura de puntos clave, cifras trazables,
    gramática, recomendaciones) Haiku cumple, así que se mantiene por defecto.
    """
    model = (settings.briefer_scriptwriter_model or "").strip()
    cheap = providers.llm_cheap
    if not model or cheap.provider_name == "mock" or model == cheap.model:
        return cheap
    return registry.get_llm(settings.model_copy(update={"briefer_llm_model_cheap": model}), cheap=True)


class _UsageMeter:
    """Acumula el uso de tokens de TODAS las llamadas de un paso (reintentos incluidos).

    ``last_usage`` de los proveedores solo refleja la última llamada; un agente que reintenta
    o un lector de PDF que llama varias veces a visión se quedaría corto en coste.
    """

    def __init__(self) -> None:
        #: Tokens acumulados por clave (``input_tokens``, ``output_tokens`` y, si hay caché de
        #: prompt, ``cache_read_input_tokens`` / ``cache_creation_input_tokens``).
        self.usage: dict[str, int] = {"input_tokens": 0, "output_tokens": 0}
        self.calls = 0

    @property
    def input_tokens(self) -> int:
        return self.usage.get("input_tokens", 0)

    @property
    def output_tokens(self) -> int:
        return self.usage.get("output_tokens", 0)

    def add(self, usage: dict[str, int]) -> None:
        self.calls += 1
        for key, value in usage.items():
            self.usage[key] = self.usage.get(key, 0) + int(value or 0)

    def cost_eur(self, provider: str, model: str) -> float:
        return costs.estimate_cost_eur(provider, model, **self.usage)


class _MeteredLLM(LLMProvider):
    """Envoltorio transparente de un ``LLMProvider`` que acumula el uso en un ``_UsageMeter``."""

    def __init__(self, inner: LLMProvider) -> None:
        super().__init__()
        self.inner = inner
        self.provider_name = inner.provider_name
        self.model = inner.model
        self.meter = _UsageMeter()
        #: Excepciones lanzadas por el proveedor (aunque el agente las haya absorbido).
        self.errors: list[BaseException] = []

    def complete(
        self, system: str, messages: list[dict], response_model: type[BaseModel] | None = None
    ) -> str | BaseModel:
        # Se pone a cero ANTES de llamar: un proveedor que falla antes de rellenar last_usage
        # dejaría el uso de la llamada anterior y se contaría dos veces.
        self.inner.last_usage = {"input_tokens": 0, "output_tokens": 0}
        try:
            return self.inner.complete(system, messages, response_model=response_model)
        except Exception as exc:
            self.errors.append(exc)
            raise
        finally:
            self.last_usage = dict(self.inner.last_usage)
            self.meter.add(self.last_usage)

    def cost_eur(self) -> float:
        return self.meter.cost_eur(self.provider_name, self.model)


class _MeteredVision(VisionProvider):
    """Igual que ``_MeteredLLM`` para ``VisionProvider``."""

    def __init__(self, inner: VisionProvider) -> None:
        super().__init__()
        self.inner = inner
        self.provider_name = inner.provider_name
        self.model = inner.model
        self.meter = _UsageMeter()

    def describe(self, image: bytes, prompt: str) -> str:
        self.inner.last_usage = {"input_tokens": 0, "output_tokens": 0}  # ver _MeteredLLM.complete
        try:
            return self.inner.describe(image, prompt)
        finally:
            self.last_usage = dict(self.inner.last_usage)
            self.meter.add(self.last_usage)

    def cost_eur(self) -> float:
        return self.meter.cost_eur(self.provider_name, self.model)


class _MeteredImageGen(ImageGenProvider):
    """Envoltorio de un ``ImageGenProvider`` que cuenta las imágenes generadas (las que se cobran).

    El coste se anota aunque un paso posterior falle (p. ej. ``cover.overlay_title``): la imagen
    ya está facturada. Un ``generate`` que lanza no cuenta (no hubo imagen).
    """

    def __init__(self, inner: ImageGenProvider) -> None:
        super().__init__()
        self.inner = inner
        self.provider_name = inner.provider_name
        self.model = inner.model
        self.images = 0

    def generate(self, prompt: str, out_path: Path) -> Path:
        path = self.inner.generate(prompt, out_path)
        self.images += 1
        return path

    def cost_eur(self) -> float:
        if not self.images:
            return 0.0
        return costs.estimate_cost_eur(self.provider_name, self.model, n_images=self.images)


def _llm_cost(llm: LLMProvider) -> float:
    """Coste de la última llamada de ``llm`` (o de todas, si es un ``_MeteredLLM``)."""
    if isinstance(llm, _MeteredLLM):
        return llm.cost_eur()
    return costs.estimate_cost_eur(llm.provider_name, llm.model, **llm.last_usage)


# ── Utilidades de pasos ───────────────────────────────────────────────────────────


@contextmanager
def _core_step(
    step: str, provider: str, model: str, metrics: list[StepMetric]
) -> Iterator[StepHandle]:
    """Paso núcleo: mide y, si falla, lanza ``PipelineStepError`` con el nombre del paso."""
    try:
        with track_step(step, provider, model, metrics) as handle:
            yield handle
    except PipelineStepError:
        raise
    except NotImplementedError as exc:
        raise StepNotImplementedError(step, exc) from exc
    except Exception as exc:
        raise PipelineStepError(step, exc) from exc


def _send_via(sender: Callable[[Briefing], DeliveryResult], briefing: Briefing, _step: StepHandle) -> DeliveryResult:
    """Envía ``briefing`` por un canal (``functools.partial`` en vez de lambda: tipado)."""
    return sender(briefing)


@dataclass
class _Fallback:
    """Sustituto de un paso núcleo cuando su proveedor real falla."""

    provider: str
    model: str
    fn: Callable[[StepHandle], object]
    label: str  # cómo se nombra en StepMetric.error: "mock", "data/samples"…


def _llm_fallback(
    settings: Settings, *, cheap: bool, fn_factory: Callable[[LLMProvider], Callable[[StepHandle], T]]
) -> _Fallback:
    """Sustituto de un paso de agente: el mismo trabajo con el ``MockLLM``."""
    mock_llm = registry.get_llm(settings, cheap=cheap, force_mock=True)
    return _Fallback(mock_llm.provider_name, mock_llm.model, fn_factory(mock_llm), "mock")


def _join_details(*details: str | None) -> str | None:
    text = " · ".join(d for d in details if d)
    return text or None


def _run_core(
    step: str,
    provider: str,
    model: str,
    metrics: list[StepMetric],
    fn: Callable[[StepHandle], T],
    fallback: _Fallback | None = None,
) -> T:
    """Paso núcleo con caída a sustituto.

    Ejecuta ``fn``; si lanza y hay ``fallback``, ejecuta el sustituto y registra **un**
    ``StepMetric`` con el proveedor sustituto, la latencia total, el coste de ambos intentos y
    ``error = "Fallback a <label> tras <causa>"``. Sin ``fallback`` (o si el sustituto también
    falla) lanza ``PipelineStepError`` / ``StepNotImplementedError`` como ``_core_step``.
    """
    start = time.perf_counter()
    first: list[StepMetric] = []
    try:
        with track_step(step, provider, model, first) as handle:
            result = fn(handle)
        metrics.extend(first)
        return result
    except Exception as exc:
        if fallback is None:
            metrics.extend(first)
            if isinstance(exc, NotImplementedError):
                raise StepNotImplementedError(step, exc) from exc
            raise PipelineStepError(step, exc) from exc
        cause = exc
    log.warning("Paso núcleo «%s»: %s falló (%s); se usa %s", step, provider, cause, fallback.label)
    second: list[StepMetric] = []
    try:
        with track_step(step, fallback.provider, fallback.model, second) as handle:
            result = cast(T, fallback.fn(handle))
    except Exception as exc:
        metrics.extend(first + second)
        raise PipelineStepError(step, exc) from exc
    failed, used = first[-1], second[-1]
    metrics.append(
        used.model_copy(
            update={
                "latency_s": round(time.perf_counter() - start, 4),
                "est_cost_eur": round(failed.est_cost_eur + used.est_cost_eur, 6),
                "error": fallback_error(fallback.label, cause),
                "detail": _join_details(failed.detail, used.detail),
            }
        )
    )
    return result


#: Fuente rotulada en los gráficos cuando los precios son sintéticos (demo o fallback).
SYNTHETIC_PRICES_SOURCE = "precios sintéticos (demo)"


#: Horas que se conserva el gráfico temporal de una cartera (lo que dura una sesión de la app).
PORTFOLIO_CHART_TTL_H = 12


def _portfolio_chart_dir(briefing_id: str) -> Path:
    """Carpeta temporal del sistema (fuera de ``data/``) para el gráfico de la cartera.

    Vive en ``<tmp>/briefer_cartera/`` y, en cada uso, se borran las de más de
    ``PORTFOLIO_CHART_TTL_H`` horas: los pesos de una cartera no se acumulan en disco.
    """
    import shutil
    import tempfile

    base = Path(tempfile.gettempdir()) / "briefer_cartera"
    base.mkdir(parents=True, exist_ok=True)
    limit = time.time() - PORTFOLIO_CHART_TTL_H * 3600
    for old in base.iterdir():
        try:
            if old.stat().st_mtime < limit:
                shutil.rmtree(old, ignore_errors=True)
        except OSError:
            continue
    return Path(tempfile.mkdtemp(prefix=f"{briefing_id}_", dir=base))


def _optional_step(
    step: str,
    provider: str,
    model: str,
    metrics: list[StepMetric],
    fn: Callable[[StepHandle], T],
) -> T | None:
    """Paso opcional: mide, y si falla lo registra (métrica marcada + log) y devuelve ``None``."""
    try:
        with track_step(step, provider, model, metrics) as handle:
            return fn(handle)
    except NotImplementedError as exc:
        log.warning("Paso opcional «%s» pendiente de implementar (%s); se omite", step, exc)
        return None
    except Exception:
        log.exception("Paso opcional «%s» fallido; el briefing continúa sin él", step)
        return None


def _start_podcast_verification(
    s: Settings,
    run_mode: str,
    stt: STTProvider,
    audio: AudioAsset,
    script: PodcastScript,
    metrics: list[StepMetric],
) -> Future[list[StepMetric]] | None:
    """Lanza en un hilo la verificación del podcast (``transcript.verify_podcast``) y devuelve el
    *future* con su ``StepMetric`` (``media.verify``), o ``None`` si no procede.

    Solo en modo real, con ``BRIEFER_VERIFY_PODCAST`` activo, STT real y audio real (si el
    podcast cayó a ``MockTTS`` no hay voz que transcribir). Es opcional: si falla, el
    ``StepMetric`` lleva el error y el briefing sigue igual.
    """
    podcast_metric = next((m for m in reversed(metrics) if m.step == "media.podcast"), None)
    if not (
        s.briefer_verify_podcast
        and run_mode == "real"
        and stt.provider_name != "mock"
        and podcast_metric is not None
        and podcast_metric.provider != "mock"
    ):
        return None
    own: list[StepMetric] = []

    def _verify(step: StepHandle) -> transcript_mod.PodcastVerification:
        try:
            result = transcript_mod.verify_podcast(audio.path, script, stt, language=s.briefer_language)
        finally:
            duration = float(getattr(stt, "last_duration_s", 0.0) or 0.0)
            step.est_cost_eur = costs.estimate_cost_eur(stt.provider_name, stt.model, duration_s=duration)
        step.detail = result.summary()
        return result

    def _job() -> list[StepMetric]:
        _optional_step("media.verify", stt.provider_name, stt.model, own, _verify)
        return own

    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="verify")
    try:
        return pool.submit(_job)
    finally:
        pool.shutdown(wait=False)  # el hilo termina solo; el future sigue siendo válido


class _Progress:
    """Notifica el avance a la UI con el formato ``"(n/N) mensaje"``."""

    def __init__(self, callback: ProgressFn | None, total: int) -> None:
        self.callback = callback
        self.total = max(1, total)
        self.current = 0

    def __call__(self, message: str, *, advance: bool = True) -> None:
        if advance:
            self.current = min(self.current + 1, self.total)
        text = f"({self.current}/{self.total}) {message}"
        log.info(text)
        if self.callback:
            try:
                self.callback(text)
            except Exception:  # un fallo de la UI nunca debe tumbar el briefing
                log.exception("Error en el callback de progreso")


def _normalize_channels(deliver: Sequence[str] | None) -> list[str]:
    """Valida y normaliza los canales de entrega. "web" se ignora (va siempre incluido).

    Raises:
        ValueError: si hay algún canal desconocido (antes de gastar nada en el briefing).
    """
    channels: list[str] = []
    unknown: list[str] = []
    for raw in deliver or []:
        channel = str(raw).strip().lower()
        if channel == "web" or channel in channels:
            continue
        if channel in DELIVERY_CHANNELS:
            channels.append(channel)
        else:
            unknown.append(str(raw))
    if unknown:
        raise ValueError(
            f"Canal de entrega desconocido: {', '.join(unknown)}. "
            f"Válidos: {', '.join(DELIVERY_CHANNELS)}."
        )
    return channels


def _normalize_tickers(tickers: Sequence[str], portfolio: Portfolio | None) -> list[str]:
    """Tickers del usuario + los de la cartera, normalizados a formato Yahoo, sin duplicados ni vacíos.

    Usa ``ingest.tickers.normalize_ticker``: acepta nombres o alias (``"santander"`` ->
    ``"SAN.MC"``, ``"telefonica"`` -> ``"TEF.MC"``) y deja en mayúsculas lo que no reconoce.
    """
    raw = [str(t) for t in tickers if t and str(t).strip()]
    if portfolio:
        raw += [p.ticker for p in portfolio.positions if p.ticker.strip()]
    return list(dict.fromkeys(tickers_mod.normalize_ticker(t) for t in raw))


# ── Subidas del usuario ───────────────────────────────────────────────────────────


def process_upload(
    path: Path, providers: Providers, metrics: list[StepMetric], language: str = "es"
) -> DocumentInsight:
    """Enruta un fichero subido al lector adecuado según su extensión.

    Registra un ``StepMetric`` (``ingest.pdf``, ``ingest.chart``, ``ingest.voice`` o
    ``ingest.upload`` si el tipo no está soportado) y propaga los errores: es
    ``run_briefing`` quien decide que una subida fallida no rompa el briefing.
    """
    ext = path.suffix.lower()
    if ext in PDF_EXTS:
        llm, vision = _MeteredLLM(providers.llm_cheap), _MeteredVision(providers.vision)
        with track_step("ingest.pdf", vision.provider_name, vision.model, metrics) as step:
            pdf_stats: dict = {}
            try:
                insight = pdf_reader.read_pdf(path, llm=llm, vision=vision, stats_out=pdf_stats)
            finally:
                step.detail = pdf_reader.format_pdf_stats(pdf_stats)
            step.est_cost_eur = llm.cost_eur() + vision.cost_eur()
        return insight
    if ext in IMAGE_EXTS:
        llm, vision = _MeteredLLM(providers.llm_cheap), _MeteredVision(providers.vision)
        with track_step("ingest.chart", vision.provider_name, vision.model, metrics) as step:
            image = path.read_bytes()
            route_stats: dict = {}
            try:
                chart_reader.validate_image(image)
                # Router (CLIP): nunca lanza; sin clasificador, la imagen va a visión sin pista.
                route = chart_reader.route_image(image, providers.classifier, stats_out=route_stats)
                if route is not None and route.is_portfolio:
                    # Los tickers del briefing ya están fijados cuando llegan las subidas: una
                    # cartera leída aquí no tendría noticias ni precios. Se desvía sin gastar visión.
                    # Sin router, la propia visión la clasifica y read_chart la desvía (ADR-005).
                    raise ValueError(chart_reader.PORTFOLIO_REDIRECT_MSG)
                insight = chart_reader.read_chart(
                    image, source_name=path.name, vision=vision, llm=llm, route=route, stats_out=route_stats
                )
            finally:
                step.detail = chart_reader.format_route_stats(route_stats)
                step.est_cost_eur = llm.cost_eur() + vision.cost_eur()
        return insight
    if ext in AUDIO_EXTS:
        with track_step("ingest.voice", providers.stt.provider_name, providers.stt.model, metrics):
            return voice.voice_to_insight(path, providers.stt, language)
    with track_step("ingest.upload", "local", "-", metrics):
        raise ValueError(f"Tipo de fichero no soportado: {path.name}")


# ── Cartera desde una captura ─────────────────────────────────────────────────────


def portfolio_from_screenshot(
    image: bytes,
    *,
    name: str = "Mi cartera",
    use_mock: bool = False,
    mode: RunMode | None = None,
    settings: Settings | None = None,
    stats_out: dict | None = None,
) -> tuple[Portfolio, StepMetric]:
    """Lee la captura de posiciones de un broker -> ``Portfolio`` (visión -> LLM barato).

    Paso ``ingest.portfolio_image`` con latencia y coste (visión + LLM). Solo resuelve esos dos
    proveedores. Privacidad (ADR-005): imagen y cartera solo en memoria; el ``StepMetric.detail``
    no lleva nombres ni cifras. ``stats_out`` recibe las filas descartadas.

    Raises:
        ValueError: imagen no válida, sin posiciones reconocibles o salida del LLM inválida
            (mensaje apto para la UI y **sin contenido de la captura**: ni el log ni
            ``StepMetric.error`` llevan nombres ni importes).
    """
    s = settings or get_settings()
    force_mock = resolve_mode(mode, use_mock) != "real"
    llm = _MeteredLLM(registry.get_llm(s, cheap=True, force_mock=force_mock))
    vision = _MeteredVision(registry.get_vision(s, force_mock=force_mock))
    stats: dict = stats_out if stats_out is not None else {}
    with track_step("ingest.portfolio_image", vision.provider_name, vision.model) as step:
        try:
            portfolio = portfolio_mod.portfolio_from_image(image, vision=vision, llm=llm, name=name, stats_out=stats)
        except ValidationError:
            # Red de seguridad (ADR-005): un ValidationError lleva ``input_value`` (nombres,
            # importes). Se registra solo un mensaje genérico; ``from None`` lo quita también del
            # traceback. Los ValueError propios de portfolio.py ya son aptos para la UI y pasan.
            raise ValueError("No se ha podido interpretar la captura de la cartera.") from None
        finally:
            step.detail = portfolio_mod.format_screenshot_stats(stats)
            step.est_cost_eur = round(llm.cost_eur() + vision.cost_eur(), 6)
    assert step.metric is not None
    return portfolio, step.metric


# ── Briefing ──────────────────────────────────────────────────────────────────────


def run_briefing(
    tickers: Sequence[str],
    portfolio: Portfolio | None = None,
    uploads: Sequence[Path] | None = None,
    make_video: bool = False,
    deliver: Sequence[str] | None = None,
    *,
    make_cover: bool = False,
    use_mock: bool = False,
    mode: RunMode | None = None,
    use_cache: bool = True,
    settings: Settings | None = None,
    progress: ProgressFn | None = None,
) -> Briefing:
    """Genera el briefing completo del día.

    Args:
        tickers: tickers elegidos por el usuario (formato Yahoo: ``SAN.MC``, ``AAPL``…).
        portfolio: cartera opcional (sus tickers se añaden al filtro).
        uploads: rutas a PDFs, imágenes o audios aportados por el usuario.
        make_video: generar también el vídeo corto (lento).
        deliver: canales extra de entrega: ``"telegram"`` (``"web"`` se ignora:
            siempre está incluido).
        make_cover: generar portada con texto a imagen (si hay proveedor configurado).
        use_mock: forzar proveedores mock y datos de ejemplo (sin red ni claves). Equivale a
            ``mode="mock"``; se mantiene por compatibilidad.
        mode: ``"real"``, ``"mock"`` o ``"demo_voices"`` (datos de ejemplo + LLM mock + edge-tts
            real). Si se indica, manda sobre ``use_mock``.
        use_cache: ``False`` ignora la caché diaria de noticias y precios (botón «Refrescar datos»).
        settings: configuración (por defecto ``get_settings()``).
        progress: callback opcional; recibe un texto por paso con el formato ``"(n/N) …"``.

    Raises:
        ValueError: sin tickers ni cartera, o canal de entrega desconocido (antes de empezar).
        PipelineStepError: falló un paso núcleo (``StepNotImplementedError`` si está pendiente).
            Su atributo ``metrics`` lleva los pasos ejecutados hasta el fallo (coste ya gastado).
    """
    metrics: list[StepMetric] = []
    try:
        return _run_briefing(
            tickers, portfolio, uploads, make_video, deliver, metrics,
            make_cover=make_cover, use_mock=use_mock, mode=mode, use_cache=use_cache,
            settings=settings, progress=progress,
        )
    except PipelineStepError as exc:
        exc.metrics = list(metrics)
        log.error("Briefing abortado en «%s». %s", exc.step, costs.format_cost_summary(metrics))
        raise


def _run_briefing(
    tickers: Sequence[str],
    portfolio: Portfolio | None,
    uploads: Sequence[Path] | None,
    make_video: bool,
    deliver: Sequence[str] | None,
    metrics: list[StepMetric],
    *,
    make_cover: bool,
    use_mock: bool,
    mode: RunMode | None,
    use_cache: bool,
    settings: Settings | None,
    progress: ProgressFn | None,
) -> Briefing:
    """Cuerpo de ``run_briefing``; va añadiendo un ``StepMetric`` por paso a ``metrics``."""
    s = settings or get_settings()
    run_mode = resolve_mode(mode, use_mock)
    offline_data = run_mode != "real"  # noticias de data/samples y precios sintéticos
    channels = _normalize_channels(deliver)
    all_tickers = _normalize_tickers(tickers, portfolio)
    if not all_tickers:
        raise ValueError("Indica al menos un ticker o una cartera con posiciones.")
    # Índices de contexto: precios y noticias de mercado, sin contar como tickers del usuario.
    context_tickers = [
        t for t in dict.fromkeys(tickers_mod.normalize_ticker(c) for c in s.context_tickers if c.strip())
        if t not in all_tickers
    ]
    fetch_tickers = all_tickers + context_tickers
    upload_paths = [Path(u) for u in uploads or []]

    providers = _providers_for_mode(s, run_mode)
    briefing_id = new_briefing_id()
    out_dir = s.output_path / briefing_id
    out_dir.mkdir(parents=True, exist_ok=True)
    want_cover = make_cover and providers.image_gen is not None
    notify = _Progress(
        progress,
        total=5 + len(upload_paths) + int(want_cover) + int(make_video) + len(channels) + 1,
    )

    # 1. Noticias ∥ precios (núcleo, en paralelo). Con proveedor real caído: data/samples y
    #    precios sintéticos, marcados en el StepMetric.
    notify("Recopilando noticias y precios…")

    # 2 (en paralelo con 1). Documentos del usuario: cada subida en su hilo y con sus propias
    #    instancias de LLM/visión (``last_usage`` es por instancia: el coste no se mezcla).
    upload_pool = (
        ThreadPoolExecutor(max_workers=min(UPLOAD_WORKERS, len(upload_paths)), thread_name_prefix="upload")
        if upload_paths else None
    )
    upload_jobs: list[tuple[Path, list[StepMetric], Future[DocumentInsight]]] = []
    for upload in upload_paths:
        notify(f"Leyendo {upload.name}…")
        own_metrics: list[StepMetric] = []
        own_providers = providers if len(upload_paths) == 1 else replace(
            providers,
            llm_cheap=registry.get_llm(s, cheap=True, force_mock=run_mode != "real"),
            vision=registry.get_vision(s, force_mock=run_mode != "real"),
        )
        assert upload_pool is not None
        future = upload_pool.submit(process_upload, upload, own_providers, own_metrics, s.briefer_language)
        upload_jobs.append((upload, own_metrics, future))
    can_fallback = s.briefer_fallback_to_mock and not offline_data
    news_fallback = _Fallback("samples", "-", lambda _h: news_mod.load_sample_news(), "data/samples")
    prices_fallback = _Fallback(
        "synthetic", "-", lambda _h: prices_mod.synthetic_snapshots(fetch_tickers), "precios sintéticos"
    )

    def _news(handle: StepHandle) -> list:
        if offline_data:
            return news_mod.load_sample_news()
        stats: dict = {}  # estadísticas de ESTA llamada (sin la carrera de los globales de news)
        try:
            return news_mod.fetch_news(
                fetch_tickers, max_items=s.briefer_news_max_items, rss_feeds=s.rss_feeds,
                use_cache=use_cache, stats_out=stats,
            )
        finally:
            handle.detail = news_mod.format_news_stats(stats)

    def _prices(_h: StepHandle) -> list:
        if offline_data:
            return prices_mod.synthetic_snapshots(fetch_tickers)
        return prices_mod.get_price_snapshots(fetch_tickers, use_cache=use_cache)

    news_metrics: list[StepMetric] = []
    prices_metrics: list[StepMetric] = []
    insights: list[DocumentInsight] = []
    uploads_collected = False
    try:
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="ingest") as pool:
            news_future = pool.submit(
                _run_core, "ingest.news", "samples" if offline_data else "yfinance+rss", "-", news_metrics,
                _news, news_fallback if can_fallback else None,
            )
            prices_future = pool.submit(
                _run_core, "ingest.prices", "synthetic" if offline_data else "yfinance", "-", prices_metrics,
                _prices, prices_fallback if can_fallback else None,
            )
            news_exc, prices_exc = news_future.exception(), prices_future.exception()
        metrics.extend(news_metrics + prices_metrics)
        if news_exc or prices_exc:
            raise news_exc or prices_exc  # type: ignore[misc]
        raw_news = news_future.result()
        prices = prices_future.result()
        sample_news = offline_data or any(m.provider == "samples" for m in news_metrics)

        with _core_step("ingest.tickers", "local", "-", metrics) as tickers_step:
            # Noticias de los tickers del usuario + las de los índices de contexto que pasen el filtro.
            relevant_news = tickers_mod.filter_by_tickers(raw_news, fetch_tickers)
            n_index = sum(1 for n in relevant_news if not set(n.tickers) & set(all_tickers))
            priced = {p.ticker.upper() for p in prices}
            no_price = [t for t in all_tickers if t.upper() not in priced]
            tickers_step.detail = _join_details(
                f"{len(relevant_news)} de {len(raw_news)} noticias relevantes"
                + (f" ({n_index} de índices de contexto)" if n_index else ""),
                # Ticker inexistente o sin cotización hoy: se avisa (el Analista también lo ve).
                f"sin precio: {', '.join(no_price)}" if no_price else None,
            )
            if sample_news and not relevant_news:
                # Con noticias de ejemplo (modo demo o fallback), si los tickers elegidos no salen
                # en ellas, se usan todas para que el briefing no quede vacío (son ficticias y lo indican).
                log.info("Noticias de ejemplo: ninguna para %s; se usan todas", all_tickers)
                relevant_news = list(raw_news)

        # 2. Documentos del usuario (opcional: una subida fallida no rompe el briefing). Se recogen
        #    en el orden de subida; sus métricas, también.
        for upload, own_metrics, future in upload_jobs:
            try:
                insights.append(future.result())
            except Exception:
                log.exception("No se pudo procesar la subida %s; se continúa sin ella", upload.name)
            metrics.extend(own_metrics)
        uploads_collected = True
    finally:
        if upload_pool is not None:
            # Si un paso núcleo de la ingesta falla, las subidas que aún no han empezado se
            # cancelan (no se paga visión para un briefing que ya no va a salir); las que están
            # en curso terminan antes de propagar el error (sin hilos huérfanos).
            upload_pool.shutdown(wait=True, cancel_futures=True)
            if not uploads_collected:
                # Lo ya gastado en subidas terminadas también cuenta (PipelineStepError.metrics).
                for _upload, own_metrics, future in upload_jobs:
                    if future.done() and not future.cancelled():
                        metrics.extend(own_metrics)

    # 3. Agente Analista (núcleo; LLM principal). Fallback: LLM mock.
    context = MarketContext(
        date=date.today(),
        tickers=all_tickers,
        news=relevant_news,
        prices=prices,
        insights=insights,
        portfolio=portfolio,
    )
    notify("Analizando el mercado…")

    # 3b. «Impacto de la noticia» con FinBERT (opcional, BRIEFER_FINBERT; solo noticias reales).
    #     Haiku traduce al inglés y FinBERT clasifica. Corre EN PARALELO con el Analista (no lo
    #     necesita), así no alarga el briefing; su métrica se añade al terminar el Analista. El
    #     resultado queda en la traza y en ``news_impact.json`` (fuera del contrato ``Briefing``).
    impact_metrics: list[StepMetric] = []
    impact_pool: ThreadPoolExecutor | None = None
    if s.briefer_finbert and not sample_news and relevant_news:
        impact_news = list(relevant_news)

        def _impact(step: StepHandle) -> dict:
            metered = _MeteredLLM(providers.llm_cheap)
            stats: dict = {}
            try:
                impacts = sentiment_mod.news_impact(impact_news, metered, stats_out=stats)
                if impacts:
                    (out_dir / "news_impact.json").write_text(
                        json.dumps([i.model_dump() for i in impacts.values()], ensure_ascii=False, indent=1),
                        encoding="utf-8",
                    )
                return impacts
            finally:
                step.est_cost_eur = metered.cost_eur()
                step.detail = sentiment_mod.impact_detail(stats)

        impact_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="impact")
        impact_pool.submit(
            _optional_step, "ingest.impact", "finbert+haiku", sentiment_mod.FINBERT_MODEL, impact_metrics, _impact
        )

    def _analyze_with(inner: LLMProvider) -> Callable[[StepHandle], Analysis]:
        def run(step: StepHandle) -> Analysis:
            metered = _MeteredLLM(inner)
            trace: list[str] = []
            try:
                return analyst.analyze(
                    context, metered, check_figures=inner.provider_name != "mock", trace=trace
                )
            finally:
                step.est_cost_eur = metered.cost_eur()
                step.detail = _join_details(*trace)

        return run

    llm_main = providers.llm
    try:
        analysis = _run_core(
            "agents.analyst", llm_main.provider_name, llm_main.model, metrics,
            _analyze_with(llm_main),
            _llm_fallback(s, cheap=False, fn_factory=_analyze_with)
            if s.briefer_fallback_to_mock and llm_main.provider_name != "mock" else None,
        )
    finally:
        if impact_pool is not None:  # espera a FinBERT (3b) y añade su métrica tras la del Analista
            impact_pool.shutdown(wait=True)
            metrics.extend(impact_metrics)

    # 4. Agente Guionista (núcleo; LLM BARATO). Si el LLM falla, write_script usa su guion de
    #    respaldo determinista (marcado como fallback); si aun así lanza, LLM mock.
    notify("Escribiendo el guion del podcast…")

    def _write_with(inner: LLMProvider) -> Callable[[StepHandle], PodcastScript]:
        def run(step: StepHandle) -> PodcastScript:
            metered = _MeteredLLM(inner)
            trace: list[str] = []
            try:
                script = scriptwriter.write_script(
                    analysis,
                    metered,
                    target_minutes=s.briefer_podcast_target_minutes,
                    speaker_names=(s.briefer_speaker_a_name, s.briefer_speaker_b_name),
                    # El MockLLM devuelve un guion fijo corto: no tiene sentido pedirle que lo alargue.
                    length_tolerance=None if inner.provider_name == "mock" else scriptwriter.LENGTH_TOLERANCE,
                    trace=trace,
                    check_figures=inner.provider_name != "mock",
                )
            finally:
                step.est_cost_eur = metered.cost_eur()
                step.detail = _join_details(*trace)
            if scriptwriter.FALLBACK_NOTE in trace and inner.provider_name != "mock":
                # Guion de respaldo: se marca como fallback aunque no haya excepción.
                step.provider, step.model = "local", "fallback_script"
                cause = metered.errors[-1] if metered.errors else RuntimeError("guion no válido")
                step.error = fallback_error("guion de respaldo", cause)
            return script

        return run

    llm_script = scriptwriter_llm(s, providers)
    script = _run_core(
        "agents.scriptwriter", llm_script.provider_name, llm_script.model, metrics,
        _write_with(llm_script),
        _llm_fallback(s, cheap=True, fn_factory=_write_with)
        if s.briefer_fallback_to_mock and llm_script.provider_name != "mock" else None,
    )

    # 5. Audio a 2 voces + transcripción (núcleo). Fallback del TTS: TTS mock (marcado).
    notify("Grabando el podcast a dos voces…")
    n_chars = sum(len(line.text) for line in script.lines)

    def _podcast_with(tts: TTSProvider) -> Callable[[StepHandle], AudioAsset]:
        def run(step: StepHandle) -> AudioAsset:
            usage_before = dict(getattr(tts, "last_usage", None) or {})
            try:
                return podcast.synthesize_podcast(
                    script, tts, out_dir, voice_a=s.briefer_voice_a, voice_b=s.briefer_voice_b,
                    max_workers=PODCAST_TTS_WORKERS,
                    retries=podcast_tts_retries(tts),
                )
            finally:
                # También si falla: los tramos de Gemini ya sintetizados se han facturado.
                step.est_cost_eur, note = tts_cost_eur(tts, n_chars, usage_before)
                step.detail = _join_details(step.detail, note)

        return run

    tts_fallback = podcast_tts_fallback(s, providers.tts, _podcast_with)
    audio = _run_core(
        "media.podcast", providers.tts.provider_name, providers.tts.model, metrics,
        _podcast_with(providers.tts), tts_fallback,
    )
    with _core_step("media.transcript", "local", "-", metrics):
        transcript = transcript_mod.build_transcript(
            script,
            audio.segments,
            out_dir,
            speaker_names={"A": s.briefer_speaker_a_name, "B": s.briefer_speaker_b_name},
        )
    # 5b. Verificación del podcast con STT (opcional, en segundo plano mientras se dibujan los
    #     gráficos): WER del MP3 final frente al guion en ``media.verify``.
    verify_future = _start_podcast_verification(s, run_mode, providers.stt, audio, script, metrics)

    # 6. Gráficos (núcleo) y portada (opcional)
    notify("Dibujando los gráficos del día…")
    # Precios sintéticos (modo demo o caída de yfinance): el pie de los gráficos lo dice.
    synthetic_prices = offline_data or any(m.provider == "synthetic" for m in prices_metrics)
    chart_source = SYNTHETIC_PRICES_SOURCE if synthetic_prices else charts_mod.DEFAULT_SOURCE
    with _core_step("media.charts", "matplotlib", "-", metrics):
        chart_assets = charts_mod.make_charts(
            prices, out_dir / "charts", line_tickers=all_tickers, source=chart_source
        )
        if portfolio is not None and portfolio.positions:
            # RGPD: el reparto de la cartera (pesos) NO va a data/outputs: se dibuja en una carpeta
            # temporal del sistema solo para esta sesión y ``storage`` no lo persiste.
            try:
                chart_assets.append(
                    charts_mod.make_portfolio_chart(portfolio, _portfolio_chart_dir(briefing_id), prices=prices)
                )
            except Exception as exc:
                log.warning("Gráfico de la cartera omitido: %s", exc)
    cover_path: Path | None = None
    if want_cover:
        notify("Generando la portada…")
        image_gen = providers.image_gen
        assert image_gen is not None

        def _cover(step: StepHandle) -> Path | None:
            metered = _MeteredImageGen(image_gen)
            try:
                return cover_mod.make_cover(analysis, metered, out_dir)
            finally:  # la imagen generada se cobra aunque falle el título superpuesto
                step.est_cost_eur = metered.cost_eur()

        cover_path = _optional_step(
            "media.cover", image_gen.provider_name, image_gen.model, metrics, _cover
        )

    # 7. Vídeo (opcional)
    video_asset = None
    if make_video:
        notify("Montando el vídeo…")
        # Nunca el gráfico de la cartera: el vídeo se guarda en data/outputs y se envía (ADR-005).
        images = ([cover_path] if cover_path else []) + [
            c.path for c in chart_assets if c.kind != "portfolio_pie"
        ]
        video_asset = _optional_step(
            "media.video",
            "ffmpeg",
            "libx264",
            metrics,
            lambda _step: video_mod.make_video(
                audio,
                images,
                out_dir / "briefing.mp4",
                transcript,
                size=(720, 1280),
                title=analysis.headline,
            ),
        )

    if verify_future is not None:
        metrics.extend(verify_future.result())  # nunca lanza: _optional_step se traga los fallos

    briefing = Briefing(
        id=briefing_id,
        context=context,
        analysis=analysis,
        script=script,
        audio=audio,
        transcript=transcript,
        charts=chart_assets,
        cover_path=cover_path,
        video=video_asset,
        metrics=list(metrics),
        deliveries=[DeliveryResult(channel="web", ok=True, detail="Disponible en la app")],
    )

    # 8. Entrega (opcional por canal): un canal caído queda como ok=False y se sigue.
    senders: dict[str, Callable[[Briefing], DeliveryResult]] = {
        "telegram": lambda b: telegram_sender.send_briefing_telegram(b, settings=s),
    }
    deliveries = list(briefing.deliveries)
    for channel in channels:
        notify(f"Enviando por {channel}…")
        result = _optional_step(
            f"delivery.{channel}", channel, "-", metrics, functools.partial(_send_via, senders[channel], briefing)
        )
        if result is None:
            error = step_error(metrics[-1]) if metrics else None
            result = DeliveryResult(
                channel=channel,  # type: ignore[arg-type]  # validado en _normalize_channels
                ok=False,
                detail=f"Error al enviar: {error or 'desconocido'}",
            )
        deliveries.append(result)
    briefing.deliveries = deliveries

    # 9. Persistencia (opcional: si falla, el briefing sigue disponible en memoria/UI).
    # Se guarda, se añade la métrica del guardado y se reescribe el JSON para que
    # ``storage.save`` también quede en ``Briefing.metrics`` (la 2.ª escritura no se mide).
    notify("Guardando el briefing…")
    briefing.metrics = list(metrics)
    saved = _optional_step(
        "storage.save",
        "local",
        "-",
        metrics,
        lambda _step: storage.save_briefing(briefing, base_dir=s.output_path),
    )
    briefing.metrics = list(metrics)
    if saved is not None:
        try:
            storage.save_briefing(briefing, base_dir=s.output_path)
        except Exception:
            log.exception("No se pudo reescribir el briefing con la métrica de guardado")

    summary = costs.summarize_metrics(briefing.metrics)
    log.info("Briefing %s listo: %s", briefing.id, summary)
    log.info(costs.format_cost_summary(briefing.metrics))
    notify("Briefing listo.", advance=False)
    return briefing


# ── Preguntas ─────────────────────────────────────────────────────────────────────


def warmup(settings: Settings | None = None, *, mode: RunMode | None = None) -> dict[str, float]:
    """Precalienta lo que hace lenta la **primera** pregunta del proceso (Q&A en frío).

    Medido el 05-oct-2026 en Windows: la 1.ª pregunta tardaba 16-17 s frente a 5-6 s las
    siguientes; ~4,7 s eran importar el SDK ``anthropic``, ~1,4 s importar ``edge_tts`` y el
    resto, crear el cliente y abrir la conexión TLS. Esta función hace todo eso por adelantado:

    - LLM barato (el del Q&A) y visión: ``provider.warmup()`` si existe (Anthropic: importa el
      SDK, crea el cliente **compartido** del proceso y hace una llamada gratuita
      ``models.retrieve``; no consume tokens).
    - TTS: importa el módulo del proveedor (``edge_tts``) para que la síntesis no pague el import.
    - STT: importa el SDK del proveedor (``openai`` para ``whisper_api``). Medido el 05-oct-2026
      con ``scripts/measure_qa_voice.py``: sin esto, el ``qa.stt`` de la 1.ª pregunta por voz
      tardaba 7-15 s en frío frente a ~1 s en caliente (casi todo, importar ``openai``).

    Pensada para que la UI la llame al cargar la página Preguntar (p. ej. en un hilo o con
    ``st.cache_resource``) mientras el usuario escribe o graba. **Nunca lanza**: un fallo se
    registra y la pregunta funcionará igual (solo que en frío). En modo mock no hace nada.

    Returns:
        ``{"llm": s, "vision": s, "stt": s, "tts": s, "total": s}`` (solo las piezas calentadas).
    """
    start = time.perf_counter()
    timings: dict[str, float] = {}
    try:
        s = settings or get_settings()
        providers = _providers_for_mode(s, resolve_mode(mode))
    except Exception as exc:  # configuración inválida: la pregunta dará el error claro
        log.warning("warmup: no se pudieron resolver los proveedores (%s)", exc)
        return {"total": round(time.perf_counter() - start, 3)}
    for name, provider in (("llm", providers.llm_cheap), ("vision", providers.vision)):
        fn = getattr(provider, "warmup", None)
        if fn is None or provider.provider_name == "mock":
            continue
        try:
            t = time.perf_counter()
            fn()
            timings[name] = round(time.perf_counter() - t, 3)
        except Exception as exc:
            log.warning("warmup de %s (%s) fallido: %s", name, provider.provider_name, exc)
    for name, module in (
        ("stt", _STT_MODULES.get(providers.stt.provider_name)),
        ("tts", _TTS_MODULES.get(providers.tts.provider_name)),
    ):
        if not module:
            continue
        try:
            t = time.perf_counter()
            importlib.import_module(module)
            timings[name] = round(time.perf_counter() - t, 3)
        except Exception as exc:
            log.warning("warmup de %s (%s) fallido: %s", name, module, exc)
    timings["total"] = round(time.perf_counter() - start, 3)
    log.info("warmup: %s", timings)
    return timings


#: Módulo del SDK de cada TTS real que ``warmup`` importa por adelantado.
#: Con Gemini en el podcast, el Q&A habla con edge-tts (``qa_tts``): se calienta ``edge_tts``.
_TTS_MODULES = {"edge": "edge_tts", "gemini": "edge_tts", "elevenlabs": "elevenlabs"}
#: Módulo del SDK de cada STT real que ``warmup`` importa por adelantado (``whisper_api``).
_STT_MODULES = {"openai": "openai"}


def answer_question(
    question: str | Path,
    briefing: Briefing | None = None,
    *,
    speak: bool = True,
    history: list[dict] | None = None,
    use_mock: bool = False,
    mode: RunMode | None = None,
    settings: Settings | None = None,
) -> QAAnswer:
    """Responde una pregunta en texto o por voz (``Path`` a un audio): STT -> Q&A -> TTS.

    Args:
        question: texto de la pregunta, o ruta al audio grabado (``st.audio_input``).
        briefing: briefing de referencia (contexto del agente). Puede ser ``None``.
        speak: sintetizar también la respuesta en audio. Si el TTS falla, se devuelve la
            respuesta en texto con ``audio_path=None`` (paso opcional; el fallo queda en
            ``QAAnswer.metrics`` con ``error``). El texto pasa antes por
            ``media.speech.normalize_for_speech`` (cifras, tickers y siglas como las diría un locutor).
            **Para pintar el texto cuanto antes**, la UI puede llamar con ``speak=False``,
            mostrar ``answer_text`` y después llamar a ``speak_answer(answer, briefing)``.
        history: turnos previos de la conversación (``[{"role", "content"}]``).
        use_mock / mode: como en ``run_briefing`` (``"demo_voices"``: LLM mock + edge-tts real).

    Returns:
        ``QAAnswer`` con ``metrics`` (``qa.stt`` si es voz, ``agents.qa``, ``qa.tts``) para medir
        la latencia de extremo a extremo (objetivo < 10 s).

    Raises:
        PipelineStepError: falló la transcripción o el agente Q&A (pasos núcleo); su atributo
            ``metrics`` lleva los pasos ejecutados.
        ValueError: la pregunta está vacía.
    """
    s = settings or get_settings()
    providers = _providers_for_mode(s, resolve_mode(mode, use_mock))
    metrics: list[StepMetric] = []

    try:
        if isinstance(question, Path):
            stt = providers.stt
            with _core_step("qa.stt", stt.provider_name, stt.model, metrics) as stt_step:
                hint = voice.vocabulary_hint(briefing.context.tickers if briefing else None)
                question_text = voice.transcribe_question(question, stt, s.briefer_language, vocabulary=hint)
                stt_step.est_cost_eur = costs.estimate_cost_eur(
                    stt.provider_name, stt.model, duration_s=float(getattr(stt, "last_duration_s", 0.0) or 0.0)
                )
        else:
            question_text = question.strip()
        if not question_text.strip():
            raise ValueError("La pregunta está vacía (o no se ha entendido el audio).")

        def _qa_with(inner: LLMProvider) -> Callable[[StepHandle], QAAnswer]:
            def run(step: StepHandle) -> QAAnswer:
                metered = _MeteredLLM(inner)
                trace: list[str] = []
                try:
                    return qa.answer(question_text, briefing, metered, history=history, trace=trace)
                finally:
                    step.est_cost_eur = metered.cost_eur()
                    step.detail = _join_details(*trace)

            return run

        llm_cheap = providers.llm_cheap
        result = _run_core(
            "agents.qa", llm_cheap.provider_name, llm_cheap.model, metrics, _qa_with(llm_cheap),
            _llm_fallback(s, cheap=True, fn_factory=_qa_with)
            if s.briefer_fallback_to_mock and llm_cheap.provider_name != "mock" else None,
        )
    except PipelineStepError as exc:
        exc.metrics = list(metrics)
        raise

    result = result.model_copy(update={"metrics": list(metrics)})
    if speak:
        result = _speak(result, briefing, providers.tts, s)
    log.info("Q&A: %s", costs.summarize_metrics(result.metrics))
    return result


def _speak(answer: QAAnswer, briefing: Briefing | None, tts: TTSProvider, s: Settings) -> QAAnswer:
    """Paso opcional ``qa.tts``: añade ``audio_path`` y su ``StepMetric`` a ``answer.metrics``.

    El TTS sale de ``qa_tts``: si el podcast usa Gemini, la respuesta va por edge-tts (latencia).
    """
    tts = qa_tts(s, tts)
    metrics = list(answer.metrics)
    qa_dir = s.output_path / (briefing.id if briefing else "sin_briefing") / "qa"

    def _synth(step: StepHandle) -> Path:
        qa_dir.mkdir(parents=True, exist_ok=True)
        spoken = normalize_for_speech(answer.answer_text) or answer.answer_text
        step.est_cost_eur = costs.estimate_cost_eur(tts.provider_name, tts.model, n_chars=len(spoken))
        return tts.synthesize(spoken, s.briefer_voice_b, qa_dir / f"respuesta_{new_briefing_id()}")

    audio_path = _optional_step("qa.tts", tts.provider_name, tts.model, metrics, _synth)
    update: dict[str, object] = {"metrics": metrics}
    if audio_path is not None:
        update["audio_path"] = audio_path
    return answer.model_copy(update=update)


def speak_answer(
    answer: QAAnswer,
    briefing: Briefing | None = None,
    *,
    use_mock: bool = False,
    mode: RunMode | None = None,
    settings: Settings | None = None,
) -> QAAnswer:
    """Sintetiza en audio una respuesta obtenida con ``answer_question(..., speak=False)``.

    Permite a la UI mostrar el texto en cuanto llega (~2-3 s en caliente) y reproducir el
    audio después. Mismo comportamiento que ``speak=True``: paso opcional ``qa.tts`` añadido a
    ``metrics`` (si falla, ``audio_path`` queda ``None`` y el ``StepMetric`` lleva ``error``).
    Si la respuesta ya tiene audio, se devuelve tal cual. ``mode`` debe ser el mismo de la
    pregunta.
    """
    if answer.audio_path is not None:
        return answer
    s = settings or get_settings()
    providers = _providers_for_mode(s, resolve_mode(mode, use_mock))
    result = _speak(answer, briefing, providers.tts, s)
    log.info("Q&A (audio): %s", costs.summarize_metrics(result.metrics))
    return result


__all__ = [
    "DELIVERY_CHANNELS",
    "DIALOGUE_TTS_PROVIDERS",
    "PODCAST_TTS_WORKERS",
    "RUN_MODES",
    "PipelineStepError",
    "ProgressFn",
    "Providers",
    "RunMode",
    "StepNotImplementedError",
    "answer_question",
    "demo_voice_tts",
    "get_providers",
    "podcast_tts_fallback",
    "podcast_tts_retries",
    "portfolio_from_screenshot",
    "process_upload",
    "qa_tts",
    "resolve_mode",
    "run_briefing",
    "scriptwriter_llm",
    "speak_answer",
    "tts_cost_eur",
    "warmup",
]
