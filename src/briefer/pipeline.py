"""Orquestación de extremo a extremo: entradas -> agentes -> salidas -> entrega.

Carril B. Es la única pieza que conoce a todos los módulos; la UI (``app/``) y el CLI
(``scripts/demo.py``) solo llaman a ``run_briefing`` y ``answer_question``.

Pasos de ``run_briefing`` (cada uno registra un ``StepMetric`` con latencia y coste):
1. ``ingest.news`` + ``ingest.prices`` + ``ingest.tickers.filter_by_tickers``
2. ``ingest.pdf_reader`` / ``ingest.chart_reader`` / ``ingest.voice`` -> ``DocumentInsight``
3. ``MarketContext`` -> ``agents.analyst`` -> ``Analysis``
4. ``agents.scriptwriter`` -> ``PodcastScript``
5. ``media.podcast`` -> ``AudioAsset``; ``media.transcript`` -> ``Transcript`` (+SRT)
6. ``media.charts`` -> ``ChartAsset``; ``media.cover`` (opcional)
7. ``media.video`` (opcional) -> ``VideoAsset``
8. ``delivery.*`` (opcional) -> ``DeliveryResult``; ``storage.save_briefing``

Con ``use_mock=True`` todos los proveedores de IA son mocks y las noticias/precios salen de
``data/samples`` / datos sintéticos (sin red ni claves). Mientras los módulos estén sin
implementar, las llamadas lanzan ``NotImplementedError`` (la UI lo muestra como "Pendiente").
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from briefer import costs, storage
from briefer.agents import analyst, qa, scriptwriter
from briefer.config import Settings, get_settings
from briefer.delivery import email_sender, telegram_sender
from briefer.ingest import chart_reader, news as news_mod, pdf_reader, prices as prices_mod
from briefer.ingest import tickers as tickers_mod, voice
from briefer.logging_utils import get_logger, track_step
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

ProgressFn = Callable[[str], None]


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


def _llm_cost(llm: LLMProvider) -> float:
    return costs.estimate_cost_eur(llm.provider_name, llm.model, **llm.last_usage)


def _notify(progress: ProgressFn | None, message: str) -> None:
    log.info(message)
    if progress:
        progress(message)


def process_upload(
    path: Path, providers: Providers, metrics: list[StepMetric], language: str = "es"
) -> DocumentInsight:
    """Enruta un fichero subido al lector adecuado según su extensión."""
    ext = path.suffix.lower()
    if ext in PDF_EXTS:
        with track_step("ingest.pdf", providers.vision.provider_name, providers.vision.model, metrics) as step:
            insight = pdf_reader.read_pdf(path, llm=providers.llm_cheap, vision=providers.vision)
            step.est_cost_eur = _llm_cost(providers.llm_cheap)
        return insight
    if ext in IMAGE_EXTS:
        with track_step("ingest.chart", providers.vision.provider_name, providers.vision.model, metrics) as step:
            insight = chart_reader.read_chart(
                path.read_bytes(),
                source_name=path.name,
                vision=providers.vision,
                llm=providers.llm_cheap,
                classifier=providers.classifier,
            )
            step.est_cost_eur = costs.estimate_cost_eur(
                providers.vision.provider_name, providers.vision.model, **providers.vision.last_usage
            )
        return insight
    if ext in AUDIO_EXTS:
        with track_step("ingest.voice", providers.stt.provider_name, providers.stt.model, metrics):
            return voice.voice_to_insight(path, providers.stt, language)
    raise ValueError(f"Tipo de fichero no soportado: {path.name}")


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
        deliver: canales extra de entrega: ``"email"``, ``"telegram"``.
        make_cover: generar portada con texto a imagen (si hay proveedor configurado).
        use_mock: forzar proveedores mock y datos de ejemplo (sin red ni claves).
        settings: configuración (por defecto ``get_settings()``).
        progress: callback opcional para mostrar el avance en la UI.
    """
    s = settings or get_settings()
    providers = get_providers(s, use_mock=use_mock)
    metrics: list[StepMetric] = []
    briefing_id = new_briefing_id()
    out_dir = s.output_path / briefing_id
    out_dir.mkdir(parents=True, exist_ok=True)

    all_tickers = list(dict.fromkeys([t.upper() for t in tickers]))
    if portfolio:
        all_tickers += [p.ticker for p in portfolio.positions if p.ticker not in all_tickers]

    # 1. Noticias y precios
    _notify(progress, "Recopilando noticias y precios…")
    with track_step("ingest.news", "samples" if use_mock else "yfinance+rss", "-", metrics):
        if use_mock:
            raw_news = news_mod.load_sample_news()
        else:
            raw_news = news_mod.fetch_news(all_tickers, max_items=s.briefer_news_max_items, rss_feeds=s.rss_feeds)
    with track_step("ingest.tickers", "local", "-", metrics):
        relevant_news = tickers_mod.filter_by_tickers(raw_news, all_tickers)
    with track_step("ingest.prices", "synthetic" if use_mock else "yfinance", "-", metrics):
        if use_mock:
            prices = prices_mod.synthetic_snapshots(all_tickers)
        else:
            prices = prices_mod.get_price_snapshots(all_tickers)

    # 2. Documentos del usuario
    insights: list[DocumentInsight] = []
    for upload in uploads or []:
        _notify(progress, f"Leyendo {Path(upload).name}…")
        insights.append(process_upload(Path(upload), providers, metrics, s.briefer_language))

    # 3. Agente Analista
    context = MarketContext(
        date=date.today(),
        tickers=all_tickers,
        news=relevant_news,
        prices=prices,
        insights=insights,
        portfolio=portfolio,
    )
    _notify(progress, "Analizando el mercado…")
    with track_step("agents.analyst", providers.llm.provider_name, providers.llm.model, metrics) as step:
        analysis = analyst.analyze(context, providers.llm)
        step.est_cost_eur = _llm_cost(providers.llm)

    # 4. Agente Guionista
    _notify(progress, "Escribiendo el guion del podcast…")
    with track_step("agents.scriptwriter", providers.llm.provider_name, providers.llm.model, metrics) as step:
        script = scriptwriter.write_script(
            analysis,
            providers.llm,
            target_minutes=s.briefer_podcast_target_minutes,
            speaker_names=(s.briefer_speaker_a_name, s.briefer_speaker_b_name),
        )
        step.est_cost_eur = _llm_cost(providers.llm)

    # 5. Audio a 2 voces + transcripción
    _notify(progress, "Grabando el podcast a dos voces…")
    with track_step("media.podcast", providers.tts.provider_name, providers.tts.model, metrics) as step:
        audio = podcast.synthesize_podcast(
            script, providers.tts, out_dir, voice_a=s.briefer_voice_a, voice_b=s.briefer_voice_b
        )
        step.est_cost_eur = costs.estimate_cost_eur(
            providers.tts.provider_name, providers.tts.model, n_chars=sum(len(l.text) for l in script.lines)
        )
    with track_step("media.transcript", "local", "-", metrics):
        transcript = transcript_mod.build_transcript(
            script,
            audio.segments,
            out_dir,
            speaker_names={"A": s.briefer_speaker_a_name, "B": s.briefer_speaker_b_name},
        )

    # 6. Gráficos y portada
    _notify(progress, "Dibujando los gráficos del día…")
    with track_step("media.charts", "matplotlib", "-", metrics):
        chart_assets = charts_mod.make_charts(prices, out_dir / "charts", portfolio=portfolio)
    cover_path = None
    if make_cover and providers.image_gen is not None:
        with track_step("media.cover", providers.image_gen.provider_name, providers.image_gen.model, metrics):
            cover_path = cover_mod.make_cover(analysis, providers.image_gen, out_dir)

    # 7. Vídeo (opcional)
    video_asset = None
    if make_video:
        _notify(progress, "Montando el vídeo…")
        images = ([cover_path] if cover_path else []) + [c.path for c in chart_assets]
        with track_step("media.video", "moviepy", "-", metrics):
            video_asset = video_mod.make_video(audio, images, out_dir / "briefing.mp4", transcript)

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
        metrics=metrics,
    )

    # 8. Entrega + persistencia
    deliveries: list[DeliveryResult] = [DeliveryResult(channel="web", ok=True, detail="Disponible en la app")]
    for channel in deliver or []:
        _notify(progress, f"Enviando por {channel}…")
        with track_step(f"delivery.{channel}", channel, "-", metrics):
            if channel == "email":
                deliveries.append(email_sender.send_briefing_email(briefing, settings=s))
            elif channel == "telegram":
                deliveries.append(telegram_sender.send_briefing_telegram(briefing, settings=s))
            else:
                deliveries.append(DeliveryResult(channel="web", ok=False, detail=f"Canal desconocido: {channel}"))
    briefing.deliveries = deliveries
    briefing.metrics = metrics

    with track_step("storage.save", "local", "-", metrics):
        storage.save_briefing(briefing, base_dir=s.output_path)
    _notify(progress, "Briefing listo.")
    return briefing


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
        speak: sintetizar también la respuesta en audio.
        history: turnos previos de la conversación (``[{"role", "content"}]``).
    """
    s = settings or get_settings()
    providers = get_providers(s, use_mock=use_mock)
    metrics: list[StepMetric] = []
    qa_dir = s.output_path / (briefing.id if briefing else "sin_briefing") / "qa"
    qa_dir.mkdir(parents=True, exist_ok=True)

    if isinstance(question, Path):
        with track_step("qa.stt", providers.stt.provider_name, providers.stt.model, metrics):
            question_text = voice.transcribe_question(question, providers.stt, s.briefer_language)
    else:
        question_text = question.strip()

    with track_step("agents.qa", providers.llm_cheap.provider_name, providers.llm_cheap.model, metrics) as step:
        result = qa.answer(question_text, briefing, providers.llm_cheap, history=history)
        step.est_cost_eur = _llm_cost(providers.llm_cheap)

    if speak:
        with track_step("qa.tts", providers.tts.provider_name, providers.tts.model, metrics):
            audio_path = providers.tts.synthesize(
                result.answer_text, s.briefer_voice_b, qa_dir / f"respuesta_{new_briefing_id()}"
            )
        result = result.model_copy(update={"audio_path": audio_path})
    log.info("Q&A: %s", costs.summarize_metrics(metrics))
    return result
