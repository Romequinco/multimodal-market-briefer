"""Voces v0.3.4 (sin red): Gemini TTS multi-locutor con cliente falso, troceo del diálogo, tiempos
proporcionales, pausas variables, caída del podcast a edge-tts y Q&A hablado con edge-tts.
"""

from __future__ import annotations

import threading
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("google.genai")

from briefer import costs, pipeline  # noqa: E402
from briefer.config import Settings  # noqa: E402
from briefer.logging_utils import step_fell_back  # noqa: E402
from briefer.media import podcast, transcript  # noqa: E402
from briefer.providers import registry  # noqa: E402
from briefer.providers.mock import MockTTS  # noqa: E402
from briefer.providers.tts import gemini_tts  # noqa: E402
from briefer.providers.tts.gemini_tts import GeminiTTS  # noqa: E402
from briefer.schemas import Briefing, PodcastScript, ScriptLine  # noqa: E402

RATE = 24_000
SECONDS_PER_WORD = 0.4  # ~150 ppm: por encima del umbral de audio «cortado»


def _texts(contents) -> list[str]:
    if isinstance(contents, str):
        return [contents]
    return [part.text for part in contents.parts]


class FakeModels:
    """Doble de ``client.models``: devuelve PCM de silencio proporcional a las palabras."""

    def __init__(self, *, seconds_per_word: float = SECONDS_PER_WORD, fail: BaseException | None = None,
                 no_audio: bool = False) -> None:
        self.calls: list[dict] = []
        self.seconds_per_word = seconds_per_word
        self.fail = fail
        self.no_audio = no_audio
        self.lock = threading.Lock()

    def generate_content(self, *, model, contents, config):
        with self.lock:
            self.calls.append({"model": model, "contents": contents, "config": config})
        if self.fail is not None:
            raise self.fail
        words = sum(len(t.split()) for t in _texts(contents))
        pcm = b"\x00\x00" * int(words * self.seconds_per_word * RATE)
        part = SimpleNamespace(inline_data=None if self.no_audio else SimpleNamespace(
            data=pcm, mime_type=f"audio/L16;codec=pcm;rate={RATE}"))
        return SimpleNamespace(
            candidates=[SimpleNamespace(content=SimpleNamespace(parts=[part]))],
            usage_metadata=SimpleNamespace(prompt_token_count=10 * len(_texts(contents)),
                                           candidates_token_count=int(25 * words * self.seconds_per_word)),
        )


def _settings(tmp_path: Path, **kw) -> Settings:
    base = {
        "_env_file": None,
        "briefer_llm_provider": "mock",
        "briefer_vision_provider": "mock",
        "briefer_stt_provider": "mock",
        "briefer_tts_provider": "gemini",
        "gemini_api_key": "test-no-real",
        "briefer_image_gen_provider": "none",
        "briefer_image_classifier_provider": "none",
        "briefer_output_dir": tmp_path / "outputs",
        "briefer_cache_dir": tmp_path / "cache",
    }
    base.update(kw)
    return Settings(**base)


def _gemini(tmp_path: Path, models: FakeModels | None = None) -> tuple[GeminiTTS, FakeModels]:
    models = models or FakeModels()
    return GeminiTTS(_settings(tmp_path), client=SimpleNamespace(models=models)), models


def _script(n: int = 6) -> PodcastScript:
    texts = [
        "Buenas noches, esto es Briefly con el cierre del día.",
        "Vamos con el IBEX, que hoy ha subido con fuerza.",
        "¿Y qué ha movido a los bancos?",
        "Los resultados del trimestre y el tono del supervisor.",
        "Por otro lado, Inditex cierra plano tras su informe.",
        "Y antes de despedirnos, recordad que esto no es asesoramiento.",
    ]
    lines = [ScriptLine(speaker="A" if i % 2 == 0 else "B", text=texts[i % len(texts)]) for i in range(n)]
    return PodcastScript(title="Prueba", lines=lines)


# ── Proveedor ─────────────────────────────────────────────────────────────────────


def test_dialogue_request_shape_and_proportional_durations(tmp_path: Path) -> None:
    tts, models = _gemini(tmp_path)
    lines = [("A", "Hola Osa, ¿qué tal el día?"), ("B", "Bien, Toro: el mercado ha cerrado tranquilo y sin sustos.")]
    path, durations = tts.synthesize_dialogue(lines, tmp_path / "tramo")
    assert path.suffix == ".wav" and path.exists()
    with wave.open(str(path), "rb") as wav:
        assert (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) == (RATE, 1, 2)
        total = wav.getnframes() / RATE
    assert sum(durations) == pytest.approx(total)
    weights = [gemini_tts.spoken_weight(t) for _, t in lines]
    assert durations[1] / durations[0] == pytest.approx(weights[1] / weights[0])

    call = models.calls[0]
    assert call["model"] == "gemini-3.8-flash-tts"
    parts = call["contents"].parts
    # Cada parte lleva su locutor (obligatorio en multi-locutor) y el estilo de la cata.
    assert [p.speech_metadata.speaker for p in parts] == ["Toro", "Osa"]
    assert parts[0].speech_metadata.style == gemini_tts.STYLE_A and parts[1].speech_metadata.style == gemini_tts.STYLE_B
    speech = call["config"].speech_config
    assert speech.language_code == "es-ES" and call["config"].response_modalities == ["AUDIO"]
    voices = {c.speaker: c.voice_config.prebuilt_voice_config.voice_name
              for c in speech.multi_speaker_voice_config.speaker_voice_configs}
    assert voices == {"Toro": "Puck", "Osa": "Kore"}
    assert tts.last_usage["output_tokens"] > 0 and tts.calls == 1


def test_single_voice_synthesize_maps_edge_voice_to_gemini(tmp_path: Path) -> None:
    tts, models = _gemini(tmp_path)
    out = tts.synthesize("La respuesta corta del día.", "es-ES-XimenaNeural", tmp_path / "qa.mp3")
    assert out.suffix == ".wav" and out.exists()
    speech = models.calls[0]["config"].speech_config
    assert speech.voice_config.prebuilt_voice_config.voice_name == "Kore"
    tts.synthesize("Otra frase.", "es-ES-AlvaroNeural", tmp_path / "a")
    assert models.calls[1]["config"].speech_config.voice_config.prebuilt_voice_config.voice_name == "Puck"


def test_truncated_or_missing_audio_is_an_error(tmp_path: Path) -> None:
    tts, _ = _gemini(tmp_path, FakeModels(seconds_per_word=0.05))
    with pytest.raises(RuntimeError, match="demasiado corto"):
        tts.synthesize_dialogue([("A", "una frase con bastantes palabras para el umbral")], tmp_path / "x")
    tts, _ = _gemini(tmp_path, FakeModels(no_audio=True))
    with pytest.raises(RuntimeError, match="no devolvió audio"):
        tts.synthesize_dialogue([("B", "hola")], tmp_path / "y")
    with pytest.raises(ValueError):
        tts.synthesize_dialogue([("C", "locutor raro")], tmp_path / "z")


def test_registry_gemini_needs_key(tmp_path: Path) -> None:
    assert isinstance(registry.get_tts(_settings(tmp_path)), GeminiTTS)  # perezoso: sin llamadas
    no_key = _settings(tmp_path, gemini_api_key=None)
    assert registry.get_tts(no_key).provider_name == "mock"  # BRIEFER_FALLBACK_TO_MOCK=true
    with pytest.raises(registry.ProviderConfigError):
        registry.get_tts(_settings(tmp_path, gemini_api_key=None, briefer_fallback_to_mock=False))


def test_gemini_tts_cost_uses_tokens() -> None:
    assert costs.llm_price_usd_per_mtok("gemini-3.8-flash-tts") == (0.50, 10.00)  # no la del LLM
    cost = costs.estimate_cost_eur("gemini", "gemini-3.8-flash-tts", input_tokens=1000, output_tokens=6000)
    assert cost == pytest.approx((1000 * 0.5 + 6000 * 10) / 1e6 * costs.USD_TO_EUR, abs=1e-6)


# ── Troceo, tiempos y pausas ──────────────────────────────────────────────────────


def test_chunk_dialogue_limits_and_order() -> None:
    texts = ["x" * 100] * 30
    chunks = podcast.chunk_dialogue(texts, max_lines=12, max_chars=10_000)
    assert chunks == [(0, 12), (12, 24), (24, 30)]
    by_chars = podcast.chunk_dialogue(["a" * 600] * 5, max_lines=12, max_chars=1300)
    assert by_chars == [(0, 2), (2, 4), (4, 5)]
    assert podcast.chunk_dialogue(["b" * 5000, "c"], max_chars=2000) == [(0, 1), (1, 2)]  # larga, sola
    assert podcast.chunk_dialogue([]) == []


def test_proportional_durations() -> None:
    assert gemini_tts.proportional_durations(["ab", "abcd", ""], 7.0) == pytest.approx([2.0, 4.0, 1.0])
    assert gemini_tts.proportional_durations([], 3.0) == []


def test_variable_pauses_rule() -> None:
    lines = _script().lines
    # 0→1 tras la apertura (y «Vamos con»): tema; 2 acaba en «?»: respuesta; 4 «Por otro lado»: tema.
    assert podcast.line_pauses(lines) == [
        podcast.PAUSE_TOPIC_S, podcast.PAUSE_NORMAL_S, podcast.PAUSE_ANSWER_S,
        podcast.PAUSE_TOPIC_S, podcast.PAUSE_TOPIC_S,
    ]
    q = ScriptLine(speaker="A", text="¿Seguro?»")
    assert podcast.pause_between(q, ScriptLine(speaker="B", text="Vamos con otra cosa")) == podcast.PAUSE_ANSWER_S


def test_default_podcast_uses_variable_pauses(tmp_path: Path) -> None:
    script = _script()
    asset = podcast.synthesize_podcast(script, MockTTS(), tmp_path, "va", "vb", max_workers=1)
    gaps = [round(b.start_s - a.end_s, 3) for a, b in zip(asset.segments, asset.segments[1:], strict=False)]
    assert gaps == pytest.approx(podcast.line_pauses(script.lines), abs=2e-3)
    assert asset.duration_s == pytest.approx(asset.segments[-1].end_s, abs=0.02)


def test_concat_audio_rejects_wrong_number_of_pauses(tmp_path: Path) -> None:
    a = MockTTS().synthesize("hola", "v", tmp_path / "a")
    with pytest.raises(ValueError, match="pausas"):
        podcast.concat_audio([a, a], tmp_path / "out.wav", pauses=[0.1, 0.2])


def test_podcast_with_gemini_chunks_and_monotonic_srt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(podcast, "DIALOGUE_MAX_LINES", 4)
    tts, models = _gemini(tmp_path)
    script = _script(10)
    asset = podcast.synthesize_podcast(script, tts, tmp_path / "ep", "va", "vb", max_workers=3, retries=0)
    assert len(models.calls) == 3  # 10 líneas en tramos de 4: 4 + 4 + 2
    assert all(p.speech_metadata.speaker for call in models.calls for p in call["contents"].parts)
    assert asset.path.suffix == ".mp3" and asset.path.exists()  # WAV de Gemini -> MP3 con loudnorm e ID3
    assert not (tmp_path / "ep" / "parts").exists()
    segs = asset.segments
    assert [s.text for s in segs] == [line.text for line in script.lines]
    assert all(a.start_s <= a.end_s <= b.start_s for a, b in zip(segs, segs[1:], strict=False))
    # Dentro de un tramo las líneas van seguidas; entre tramos, la pausa variable de la frontera.
    pauses = podcast.line_pauses(script.lines)
    assert segs[1].start_s == pytest.approx(segs[0].end_s, abs=2e-3)
    assert segs[4].start_s - segs[3].end_s == pytest.approx(pauses[3], abs=2e-3)
    assert asset.duration_s == pytest.approx(segs[-1].end_s, abs=0.15)
    srt = transcript.build_transcript(script, segs, tmp_path / "ep", speaker_names={"A": "Toro", "B": "Osa"})
    assert srt.srt_path is not None and "Toro:" in srt.srt_path.read_text(encoding="utf-8")


# ── Pipeline: caída a edge-tts y Q&A con edge-tts ─────────────────────────────────


class FakeEdge(MockTTS):
    """Hace de edge-tts (sin red): WAV de silencio con ``provider_name = "edge"``."""

    provider_name = "edge"

    def __init__(self, *a, fail: bool = False, **k) -> None:
        super().__init__(model="edge-tts")
        self.fail = fail
        self.texts: list[str] = []

    def synthesize(self, text, voice, out_path):
        if self.fail:
            raise ConnectionError("edge-tts 403")
        self.texts.append(voice)
        return super().synthesize(text, voice, out_path)


def _run_with(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, gemini: GeminiTTS, edge: FakeEdge) -> Briefing:
    real_get_providers = pipeline.get_providers

    def providers(settings, use_mock=False):
        prov = real_get_providers(settings, use_mock=use_mock)
        prov.tts = gemini
        return prov

    monkeypatch.setattr(pipeline, "get_providers", providers)
    monkeypatch.setattr(pipeline, "demo_voice_tts", lambda _s: edge)
    monkeypatch.setattr(pipeline.news_mod, "fetch_news", lambda *a, **k: pipeline.news_mod.load_sample_news())
    monkeypatch.setattr(pipeline.prices_mod, "get_price_snapshots",
                        lambda *a, **k: (_ for _ in ()).throw(ConnectionError("sin red")))
    return pipeline.run_briefing(["SAN.MC"], settings=_settings(tmp_path), use_cache=False)


def test_gemini_podcast_cost_in_metric(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    gemini, models = _gemini(tmp_path)
    briefing = _run_with(tmp_path, monkeypatch, gemini, FakeEdge())
    m = {x.step: x for x in briefing.metrics}["media.podcast"]
    assert m.provider == "gemini" and m.error is None and models.calls
    assert m.est_cost_eur > 0 and m.detail and "tokens de audio" in m.detail
    assert briefing.audio is not None and Path(briefing.audio.path).suffix == ".mp3"


def test_gemini_failure_falls_back_to_edge(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    gemini, _ = _gemini(tmp_path, FakeModels(fail=ConnectionError("503 UNAVAILABLE")))
    edge = FakeEdge()
    briefing = _run_with(tmp_path, monkeypatch, gemini, edge)
    m = {x.step: x for x in briefing.metrics}["media.podcast"]
    assert m.provider == "edge" and step_fell_back(m)
    assert m.error.startswith("Fallback a edge-tts tras ConnectionError")
    assert edge.texts and set(edge.texts) <= {"es-ES-AlvaroNeural", "es-ES-XimenaNeural"}
    assert briefing.audio is not None and Path(briefing.audio.path).exists()


def test_gemini_and_edge_failure_ends_in_mock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    gemini, _ = _gemini(tmp_path, FakeModels(fail=ConnectionError("503")))
    briefing = _run_with(tmp_path, monkeypatch, gemini, FakeEdge(fail=True))
    m = {x.step: x for x in briefing.metrics}["media.podcast"]
    assert m.provider == "mock" and step_fell_back(m) and "edge-tts tampoco" in (m.detail or "")
    assert briefing.audio is not None


def test_qa_answer_speaks_with_edge_when_podcast_is_gemini(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sample_briefing: Briefing
) -> None:
    gemini, models = _gemini(tmp_path)
    edge = FakeEdge()
    monkeypatch.setattr(pipeline, "demo_voice_tts", lambda _s: edge)
    real_get_providers = pipeline.get_providers

    def providers(settings, use_mock=False):
        prov = real_get_providers(settings, use_mock=use_mock)
        prov.tts = gemini
        return prov

    monkeypatch.setattr(pipeline, "get_providers", providers)
    answer = pipeline.answer_question("¿Qué ha pasado hoy?", sample_briefing, settings=_settings(tmp_path))
    qa_tts = answer.metrics[-1]
    assert qa_tts.step == "qa.tts" and qa_tts.provider == "edge" and qa_tts.error is None
    assert answer.audio_path is not None and not models.calls  # Gemini no se usa en el Q&A
    assert edge.texts == ["es-ES-XimenaNeural"]  # voz B (Osa), como en el resto de modos
    assert pipeline.qa_tts(_settings(tmp_path), MockTTS()).provider_name == "mock"


def test_retries_per_provider(tmp_path: Path) -> None:
    gemini, _ = _gemini(tmp_path)
    assert pipeline.podcast_tts_retries(gemini) == 1
    assert pipeline.podcast_tts_retries(FakeEdge()) == 0
    assert pipeline.podcast_tts_retries(MockTTS()) == 2
