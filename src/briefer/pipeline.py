"""Orquestación de extremo a extremo: entradas -> agentes -> salidas -> entrega.

Carril B. Es la única pieza que conoce a todos los módulos; la UI (``app/``) y el CLI
(``scripts/demo.py``) solo llaman a ``run_briefing`` y ``answer_question``.

Pasos de ``run_briefing`` (cada uno registra un ``StepMetric`` con latencia y coste):
1. ``ingest.news`` + ``ingest.tickers.filter_by_tickers`` + ``ingest.prices``      [núcleo]
2. ``ingest.pdf`` / ``ingest.chart`` / ``ingest.voice`` -> ``DocumentInsight``      [opcional, uno por subida]
3. ``MarketContext`` -> ``agents.analyst`` -> ``Analysis``                          [núcleo]
4. ``agents.scriptwriter`` -> ``PodcastScript``                                     [núcleo]
5. ``media.podcast`` -> ``AudioAsset``; ``media.transcript`` -> ``Transcript``      [núcleo]
6. ``media.charts`` -> ``ChartAsset`` [núcleo]; ``media.cover``                     [opcional]
7. ``media.video`` -> ``VideoAsset``                                                [opcional]
8. ``delivery.<canal>`` -> ``DeliveryResult``; ``storage.save``                     [opcionales]

Tolerancia a fallos:
- Un paso **opcional** que falla no rompe el briefing: su ``StepMetric`` queda marcado como
  fallido (campo ``StepMetric.error``, ver ``logging_utils.step_failed``), se registra en el log y se sigue. En la
  entrega, además, el canal aparece en ``Briefing.deliveries`` con ``ok=False``.
- Un paso **núcleo** que falla lanza ``PipelineStepError`` (o ``StepNotImplementedError``,
  que además es ``NotImplementedError`` para que la UI lo muestre como «Pendiente») con el
  nombre del paso y la causa encadenada.

Con ``use_mock=True`` todos los proveedores de IA son mocks y las noticias/precios salen de
``data/samples`` / datos sintéticos (sin red ni claves).
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from briefer import costs, storage
from briefer.agents import analyst, qa, scriptwriter
from briefer.config import Settings, get_settings
from briefer.delivery import email_sender, telegram_sender
from briefer.ingest import chart_reader, news as news_mod, pdf_reader, prices as prices_mod
from briefer.ingest import tickers as tickers_mod, voice
from briefer.logging_utils import StepHandle, get_logger, step_error, track_step
from briefer.media import charts as charts_mod, cover as cover_mod, podcast, transcript as transcript_mod
from briefer.media import video as video_mod
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
    Briefing,
    DeliveryResult,
    DocumentInsight,
    MarketContext,
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
DELIVERY_CHANNELS: tuple[str, ...] = ("email", "telegram")

ProgressFn = Callable[[str], None]
T = TypeVar("T")


# ── Errores ───────────────────────────────────────────────────────────────────────


class PipelineStepError(RuntimeError):
    """Fallo de un paso núcleo del pipeline. ``step`` es el nombre del paso; la causa
    original queda en ``__cause__``."""

    def __init__(self, step: str, cause: BaseException) -> None:
        self.step = step
        super().__init__(f"Falló el paso «{step}»: {type(cause).__name__}: {cause}")


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


class _UsageMeter:
    """Acumula el uso de tokens de TODAS las llamadas de un paso (reintentos incluidos).

    ``last_usage`` de los proveedores solo refleja la última llamada; un agente que reintenta
    o un lector de PDF que llama varias veces a visión se quedaría corto en coste.
    """

    def __init__(self) -> None:
        self.input_tokens = 0
        self.output_tokens = 0

    def add(self, usage: dict[str, int]) -> None:
        self.input_tokens += int(usage.get("input_tokens", 0))
        self.output_tokens += int(usage.get("output_tokens", 0))

    def cost_eur(self, provider: str, model: str) -> float:
        return costs.estimate_cost_eur(
            provider, model, input_tokens=self.input_tokens, output_tokens=self.output_tokens
        )


class _MeteredLLM(LLMProvider):
    """Envoltorio transparente de un ``LLMProvider`` que acumula el uso en un ``_UsageMeter``."""

    def __init__(self, inner: LLMProvider) -> None:
        super().__init__()
        self.inner = inner
        self.provider_name = inner.provider_name
        self.model = inner.model
        self.meter = _UsageMeter()

    def complete(
        self, system: str, messages: list[dict], response_model: type[BaseModel] | None = None
    ) -> str | BaseModel:
        try:
            return self.inner.complete(system, messages, response_model=response_model)
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
        try:
            return self.inner.describe(image, prompt)
        finally:
            self.last_usage = dict(self.inner.last_usage)
            self.meter.add(self.last_usage)

    def cost_eur(self) -> float:
        return self.meter.cost_eur(self.provider_name, self.model)


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
            insight = pdf_reader.read_pdf(path, llm=llm, vision=vision)
            step.est_cost_eur = llm.cost_eur() + vision.cost_eur()
        return insight
    if ext in IMAGE_EXTS:
        llm, vision = _MeteredLLM(providers.llm_cheap), _MeteredVision(providers.vision)
        with track_step("ingest.chart", vision.provider_name, vision.model, metrics) as step:
            insight = chart_reader.read_chart(
                path.read_bytes(),
                source_name=path.name,
                vision=vision,
                llm=llm,
                classifier=providers.classifier,
            )
            step.est_cost_eur = llm.cost_eur() + vision.cost_eur()
        return insight
    if ext in AUDIO_EXTS:
        with track_step("ingest.voice", providers.stt.provider_name, providers.stt.model, metrics):
            return voice.voice_to_insight(path, providers.stt, language)
    with track_step("ingest.upload", "local", "-", metrics):
        raise ValueError(f"Tipo de fichero no soportado: {path.name}")


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
    settings: Settings | None = None,
    progress: ProgressFn | None = None,
) -> Briefing:
    """Genera el briefing completo del día.

    Args:
        tickers: tickers elegidos por el usuario (formato Yahoo: ``SAN.MC``, ``AAPL``…).
        portfolio: cartera opcional (sus tickers se añaden al filtro).
        uploads: rutas a PDFs, imágenes o audios aportados por el usuario.
        make_video: generar también el vídeo corto (lento).
        deliver: canales extra de entrega: ``"email"``, ``"telegram"`` (``"web"`` se ignora:
            siempre está incluido).
        make_cover: generar portada con texto a imagen (si hay proveedor configurado).
        use_mock: forzar proveedores mock y datos de ejemplo (sin red ni claves).
        settings: configuración (por defecto ``get_settings()``).
        progress: callback opcional; recibe un texto por paso con el formato ``"(n/N) …"``.

    Raises:
        ValueError: sin tickers ni cartera, o canal de entrega desconocido (antes de empezar).
        PipelineStepError: falló un paso núcleo (``StepNotImplementedError`` si está pendiente).
    """
    s = settings or get_settings()
    channels = _normalize_channels(deliver)
    all_tickers = _normalize_tickers(tickers, portfolio)
    if not all_tickers:
        raise ValueError("Indica al menos un ticker o una cartera con posiciones.")
    upload_paths = [Path(u) for u in uploads or []]

    providers = get_providers(s, use_mock=use_mock)
    metrics: list[StepMetric] = []
    briefing_id = new_briefing_id()
    out_dir = s.output_path / briefing_id
    out_dir.mkdir(parents=True, exist_ok=True)
    want_cover = make_cover and providers.image_gen is not None
    notify = _Progress(
        progress,
        total=5 + len(upload_paths) + int(want_cover) + int(make_video) + len(channels) + 1,
    )

    # 1. Noticias y precios (núcleo)
    notify("Recopilando noticias y precios…")
    with _core_step("ingest.news", "samples" if use_mock else "yfinance+rss", "-", metrics):
        if use_mock:
            raw_news = news_mod.load_sample_news()
        else:
            raw_news = news_mod.fetch_news(
                all_tickers, max_items=s.briefer_news_max_items, rss_feeds=s.rss_feeds
            )
    with _core_step("ingest.tickers", "local", "-", metrics):
        relevant_news = tickers_mod.filter_by_tickers(raw_news, all_tickers)
        if use_mock and not relevant_news:
            # En modo demo, si los tickers elegidos no salen en las noticias de ejemplo,
            # se usan todas para que el briefing no quede vacío (son ficticias y lo indican).
            log.info("Modo mock: ninguna noticia de ejemplo para %s; se usan todas", all_tickers)
            relevant_news = list(raw_news)
    with _core_step("ingest.prices", "synthetic" if use_mock else "yfinance", "-", metrics):
        if use_mock:
            prices = prices_mod.synthetic_snapshots(all_tickers)
        else:
            prices = prices_mod.get_price_snapshots(all_tickers)

    # 2. Documentos del usuario (opcional: una subida fallida no rompe el briefing)
    insights: list[DocumentInsight] = []
    for upload in upload_paths:
        notify(f"Leyendo {upload.name}…")
        try:
            insights.append(process_upload(upload, providers, metrics, s.briefer_language))
        except Exception:
            log.exception("No se pudo procesar la subida %s; se continúa sin ella", upload.name)

    # 3. Agente Analista (núcleo)
    context = MarketContext(
        date=date.today(),
        tickers=all_tickers,
        news=relevant_news,
        prices=prices,
        insights=insights,
        portfolio=portfolio,
    )
    notify("Analizando el mercado…")
    llm = _MeteredLLM(providers.llm)
    with _core_step("agents.analyst", llm.provider_name, llm.model, metrics) as step:
        try:
            analysis = analyst.analyze(context, llm)
        finally:
            step.est_cost_eur = llm.cost_eur()

    # 4. Agente Guionista (núcleo)
    notify("Escribiendo el guion del podcast…")
    llm = _MeteredLLM(providers.llm)
    with _core_step("agents.scriptwriter", llm.provider_name, llm.model, metrics) as step:
        try:
            script = scriptwriter.write_script(
                analysis,
                llm,
                target_minutes=s.briefer_podcast_target_minutes,
                speaker_names=(s.briefer_speaker_a_name, s.briefer_speaker_b_name),
                # El MockLLM devuelve un guion fijo corto: no tiene sentido pedirle que lo alargue.
                length_tolerance=None if llm.provider_name == "mock" else scriptwriter.LENGTH_TOLERANCE,
            )
        finally:
            step.est_cost_eur = llm.cost_eur()

    # 5. Audio a 2 voces + transcripción (núcleo)
    notify("Grabando el podcast a dos voces…")
    with _core_step("media.podcast", providers.tts.provider_name, providers.tts.model, metrics) as step:
        audio = podcast.synthesize_podcast(
            script, providers.tts, out_dir, voice_a=s.briefer_voice_a, voice_b=s.briefer_voice_b
        )
        step.est_cost_eur = costs.estimate_cost_eur(
            providers.tts.provider_name,
            providers.tts.model,
            n_chars=sum(len(line.text) for line in script.lines),
        )
    with _core_step("media.transcript", "local", "-", metrics):
        transcript = transcript_mod.build_transcript(
            script,
            audio.segments,
            out_dir,
            speaker_names={"A": s.briefer_speaker_a_name, "B": s.briefer_speaker_b_name},
        )

    # 6. Gráficos (núcleo) y portada (opcional)
    notify("Dibujando los gráficos del día…")
    with _core_step("media.charts", "matplotlib", "-", metrics):
        chart_assets = charts_mod.make_charts(prices, out_dir / "charts", portfolio=portfolio)
    cover_path: Path | None = None
    if want_cover:
        notify("Generando la portada…")
        image_gen = providers.image_gen
        assert image_gen is not None

        def _cover(step: StepHandle) -> Path | None:
            path = cover_mod.make_cover(analysis, image_gen, out_dir)
            step.est_cost_eur = costs.estimate_cost_eur(
                image_gen.provider_name, image_gen.model, n_images=1
            )
            return path

        cover_path = _optional_step(
            "media.cover", image_gen.provider_name, image_gen.model, metrics, _cover
        )

    # 7. Vídeo (opcional)
    video_asset = None
    if make_video:
        notify("Montando el vídeo…")
        images = ([cover_path] if cover_path else []) + [c.path for c in chart_assets]
        video_asset = _optional_step(
            "media.video",
            "moviepy",
            "-",
            metrics,
            lambda _step: video_mod.make_video(audio, images, out_dir / "briefing.mp4", transcript),
        )

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
        "email": lambda b: email_sender.send_briefing_email(b, settings=s),
        "telegram": lambda b: telegram_sender.send_briefing_telegram(b, settings=s),
    }
    deliveries = list(briefing.deliveries)
    for channel in channels:
        notify(f"Enviando por {channel}…")
        result = _optional_step(
            f"delivery.{channel}", channel, "-", metrics, lambda _step, c=channel: senders[c](briefing)
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
    notify("Briefing listo.", advance=False)
    return briefing


# ── Preguntas ─────────────────────────────────────────────────────────────────────


def answer_question(
    question: str | Path,
    briefing: Briefing | None = None,
    *,
    speak: bool = True,
    history: list[dict] | None = None,
    use_mock: bool = False,
    settings: Settings | None = None,
) -> QAAnswer:
    """Responde una pregunta en texto o por voz (``Path`` a un audio): STT -> Q&A -> TTS.

    Args:
        question: texto de la pregunta, o ruta al audio grabado (``st.audio_input``).
        briefing: briefing de referencia (contexto del agente). Puede ser ``None``.
        speak: sintetizar también la respuesta en audio. Si el TTS falla, se devuelve la
            respuesta en texto con ``audio_path=None`` (paso opcional; el fallo queda en
            ``QAAnswer.metrics`` con ``error``).

    Returns:
        ``QAAnswer`` con ``metrics`` (``qa.stt`` si es voz, ``agents.qa``, ``qa.tts``) para medir
        la latencia de extremo a extremo (objetivo < 10 s).
        history: turnos previos de la conversación (``[{"role", "content"}]``).

    Raises:
        PipelineStepError: falló la transcripción o el agente Q&A (pasos núcleo).
        ValueError: la pregunta está vacía.
    """
    s = settings or get_settings()
    providers = get_providers(s, use_mock=use_mock)
    metrics: list[StepMetric] = []

    if isinstance(question, Path):
        with _core_step("qa.stt", providers.stt.provider_name, providers.stt.model, metrics):
            question_text = voice.transcribe_question(question, providers.stt, s.briefer_language)
    else:
        question_text = question.strip()
    if not question_text.strip():
        raise ValueError("La pregunta está vacía (o no se ha entendido el audio).")

    llm = _MeteredLLM(providers.llm_cheap)
    with _core_step("agents.qa", llm.provider_name, llm.model, metrics) as step:
        try:
            result = qa.answer(question_text, briefing, llm, history=history)
        finally:
            step.est_cost_eur = llm.cost_eur()

    if speak:
        qa_dir = s.output_path / (briefing.id if briefing else "sin_briefing") / "qa"

        def _speak(step: StepHandle) -> Path:
            qa_dir.mkdir(parents=True, exist_ok=True)
            step.est_cost_eur = costs.estimate_cost_eur(
                providers.tts.provider_name, providers.tts.model, n_chars=len(result.answer_text)
            )
            return providers.tts.synthesize(
                result.answer_text, s.briefer_voice_b, qa_dir / f"respuesta_{new_briefing_id()}"
            )

        audio_path = _optional_step(
            "qa.tts", providers.tts.provider_name, providers.tts.model, metrics, _speak
        )
        if audio_path is not None:
            result = result.model_copy(update={"audio_path": audio_path})
    result = result.model_copy(update={"metrics": list(metrics)})
    log.info("Q&A: %s", costs.summarize_metrics(metrics))
    return result


__all__ = [
    "DELIVERY_CHANNELS",
    "PipelineStepError",
    "ProgressFn",
    "Providers",
    "StepNotImplementedError",
    "answer_question",
    "get_providers",
    "process_upload",
    "run_briefing",
]
