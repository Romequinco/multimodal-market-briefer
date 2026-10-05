"""Regresiones de la auditoría F0+F1 (MUST M1-M7) y de las peticiones cruzadas de la tanda.

Sin red ni claves: proveedores mock (``conftest._mock_env``) y dobles de los SDK.
"""

from __future__ import annotations

import json
import struct
import sys
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest

from briefer import brand, pipeline, storage
from briefer.config import Settings, reset_settings_cache
from briefer.logging_utils import error_text, fallback_error, redact_secrets, track_step
from briefer.media import charts as charts_mod
from briefer.providers import mock
from briefer.schemas import Briefing, Portfolio, Position, StepMetric

APP_DIR = Path(__file__).resolve().parents[1] / "app"
SAMPLES = Path(__file__).resolve().parents[1] / "data" / "samples"


def _portfolio() -> Portfolio:
    return Portfolio(name="Mía", positions=[Position(ticker="SAN.MC", weight=0.6, quantity=120),
                                            Position(ticker="ITX.MC", weight=0.4, quantity=30)])


# ── M1: la cartera no se persiste ─────────────────────────────────────────────────


def test_m1_portfolio_not_persisted_in_briefing_json(tmp_path: Path) -> None:
    briefing = pipeline.run_briefing([], portfolio=_portfolio(), use_mock=True)
    # En memoria (la sesión que lo generó) sí está la cartera y su gráfico.
    assert briefing.context.portfolio is not None
    pie = [c for c in briefing.charts if c.kind == "portfolio_pie"]
    assert pie and Path(pie[0].path).is_file()
    # El gráfico de pesos NO se escribe en data/outputs.
    outputs = Path(storage._base(None))
    assert not list(outputs.rglob("portfolio_weights.png"))
    # En disco: sin cartera (ni pesos ni cantidades) y sin gráfico de reparto.
    raw = (outputs / briefing.id / storage.BRIEFING_FILE).read_text(encoding="utf-8")
    data = json.loads(raw)
    assert data["context"]["portfolio"] is None
    assert "quantity" not in raw and '"weight"' not in raw
    assert all(c["kind"] != "portfolio_pie" for c in data["charts"])
    assert set(data["context"]["tickers"]) >= {"SAN.MC", "ITX.MC"}  # los tickers sí (filtro)
    # Histórico: lo que se carga tampoco la lleva.
    loaded = storage.load_briefing(briefing.id)
    assert loaded.context.portfolio is None


def test_m1_export_drops_portfolio(sample_briefing: Briefing, tmp_path: Path) -> None:
    assert sample_briefing.context.portfolio is not None
    path = storage.export_briefing(sample_briefing, tmp_path / "demo")
    assert json.loads(path.read_text(encoding="utf-8"))["context"]["portfolio"] is None
    assert sample_briefing.context.portfolio is not None  # el original no se toca


# ── M2: subidas y grabaciones temporales ──────────────────────────────────────────


def test_m2_voice_uploads_have_unique_names(tmp_path: Path) -> None:
    from briefer.ingest.voice import save_audio_upload

    a = save_audio_upload(b"RIFF....", tmp_path, ".wav")
    b = save_audio_upload(b"RIFF....", tmp_path, ".wav")
    assert a != b and a.parent == b.parent == tmp_path


@pytest.mark.parametrize("fail", [False, True])
def test_m2_briefing_page_deletes_uploads(monkeypatch: pytest.MonkeyPatch, fail: bool) -> None:
    """Las subidas van a una carpeta única por ejecución y se borran al terminar (también si falla)."""
    import streamlit as st
    from streamlit.testing.v1 import AppTest

    if str(APP_DIR) not in sys.path:
        sys.path.insert(0, str(APP_DIR))
    files = [SimpleNamespace(name="resultados.pdf", getvalue=lambda: b"%PDF-1.4 fake"),
             SimpleNamespace(name="../../nota.wav", getvalue=lambda: b"RIFF")]
    monkeypatch.setattr(st, "file_uploader", lambda *a, **k: files)  # AppTest no simula subidas
    seen: list[list[Path]] = []
    real_run = pipeline.run_briefing

    def fake_run(tickers, *, uploads=None, **kw):
        paths = [Path(u) for u in uploads or []]
        assert [p.name for p in paths] == ["resultados.pdf", "nota.wav"]  # sin rutas del usuario
        assert all(p.is_file() for p in paths)
        seen.append(paths)
        if fail:
            raise pipeline.PipelineStepError("agents.analyst", RuntimeError("boom"))
        return real_run(tickers, **kw)

    monkeypatch.setattr(pipeline, "run_briefing", fake_run)
    at = AppTest.from_file(str(APP_DIR / "pages" / "1_Briefing.py"), default_timeout=60).run()
    at.button[0].click().run()
    at.button[0].click().run()
    assert not at.exception
    assert len(seen) == 2 and seen[0][0].parent != seen[1][0].parent  # carpeta única por ejecución
    assert not any(p.exists() or p.parent.exists() for run in seen for p in run)  # borradas


# ── M3: el audio viejo no se reenvía al preguntar por texto ───────────────────────


def test_m3_pick_question_rules() -> None:
    if str(APP_DIR) not in sys.path:
        sys.path.insert(0, str(APP_DIR))
    from components.players import pick_question

    assert pick_question("¿Sugerencia?", "texto", True, "audio") == "suggestion"
    assert pick_question(None, "¿Inditex?", True, None) == "text"      # audio viejo: gana el texto
    assert pick_question(None, "¿Inditex?", True, "text") == "text"
    assert pick_question(None, "¿Inditex?", True, "audio") == "audio"  # grabado después de escribir
    assert pick_question(None, "  ", True, None) == "audio"
    assert pick_question(None, "", False, None) == ""


def _wav_bytes(seconds: float = 0.5, amplitude: int = 0) -> bytes:
    import io

    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        n = int(16000 * seconds)
        w.writeframes(b"".join(struct.pack("<h", amplitude if i % 2 else -amplitude) for i in range(n)))
    return buf.getvalue()


def test_m3_ask_page_text_after_voice_uses_text(monkeypatch: pytest.MonkeyPatch) -> None:
    """Preguntar por voz y luego por texto: la 2.ª pregunta es el texto, no la grabación vieja,
    y la grabación temporal se borra."""
    import streamlit as st
    from streamlit.testing.v1 import AppTest

    if str(APP_DIR) not in sys.path:
        sys.path.insert(0, str(APP_DIR))
    recording = SimpleNamespace(getvalue=lambda: _wav_bytes(amplitude=3000))

    def fake_audio_input(label, *, key=None, **_kw):  # Streamlit vacía el widget al cambiar la clave
        return recording if key == "qa_audio_0" else None

    monkeypatch.setattr(st, "audio_input", fake_audio_input)
    questions: list[object] = []
    real_answer = pipeline.answer_question

    def spy(question, *args, **kwargs):
        questions.append(question)
        if isinstance(question, Path):
            assert question.is_file()
        return real_answer(question, *args, **kwargs)

    monkeypatch.setattr(pipeline, "answer_question", spy)
    at = AppTest.from_file(str(APP_DIR / "pages" / "2_Preguntar.py"), default_timeout=60).run()
    at.checkbox[0].uncheck().run()
    preguntar = next(b for b in at.button if b.label == "Preguntar")
    preguntar.click().run()  # 1.ª: por voz (solo hay grabación)
    assert not at.exception
    assert isinstance(questions[0], Path) and not questions[0].exists()  # borrada tras transcribir
    assert at.session_state["qa_answers"][0].question.startswith("[MOCK]")
    at.text_input[0].input("¿Qué ha pasado con Inditex?").run()
    next(b for b in at.button if b.label == "Preguntar").click().run()
    assert not at.exception
    assert questions[1] == "¿Qué ha pasado con Inditex?"
    assert at.session_state["qa_answers"][0].question == "¿Qué ha pasado con Inditex?"


def test_m3_stale_recording_loses_to_typed_text(monkeypatch: pytest.MonkeyPatch) -> None:
    import streamlit as st
    from streamlit.testing.v1 import AppTest

    if str(APP_DIR) not in sys.path:
        sys.path.insert(0, str(APP_DIR))
    recording = SimpleNamespace(getvalue=lambda: _wav_bytes(amplitude=3000))
    monkeypatch.setattr(st, "audio_input", lambda *a, **k: recording)  # la grabación sigue ahí
    at = AppTest.from_file(str(APP_DIR / "pages" / "2_Preguntar.py"), default_timeout=60).run()
    at.checkbox[0].uncheck().run()
    at.text_input[0].input("¿Y Repsol?").run()
    next(b for b in at.button if b.label == "Preguntar").click().run()
    assert not at.exception
    assert at.session_state["qa_answers"][0].question == "¿Y Repsol?"


# ── M4: WhisperAPI y STT mock ─────────────────────────────────────────────────────


def test_m4_mock_stt_is_marked() -> None:
    assert mock.MockSTT().transcribe(Path("x.wav")).startswith("[MOCK]")


class _FakeTranscriptions:
    def __init__(self, response) -> None:
        self.response = response
        self.calls: list[dict] = []

    def create(self, **kwargs):
        kwargs["file_bytes"] = kwargs.pop("file").read()
        self.calls.append(kwargs)
        return self.response


def _whisper(model: str, response) -> tuple[object, _FakeTranscriptions]:
    from briefer.providers.stt.whisper_api import WhisperAPI

    stt = WhisperAPI(Settings(_env_file=None, openai_api_key="sk-test-123456789", briefer_whisper_api_model=model))
    fake = _FakeTranscriptions(response)
    stt._client = SimpleNamespace(audio=SimpleNamespace(transcriptions=fake))
    return stt, fake


def test_m4_whisper_transcribes_with_config_model_and_language(tmp_path: Path) -> None:
    audio = tmp_path / "q.wav"
    audio.write_bytes(_wav_bytes(seconds=1.0, amplitude=3000))
    stt, fake = _whisper("whisper-1", SimpleNamespace(text="  ¿Por qué  cae Inditex? ", duration=1.0))
    assert stt.transcribe(audio, "es") == "¿Por qué cae Inditex?"
    call = fake.calls[0]
    assert call["model"] == "whisper-1" and call["language"] == "es"
    assert call["response_format"] == "verbose_json" and "prompt" not in call  # sin prompt: no se repite
    assert stt.last_duration_s == pytest.approx(1.0)

    stt2, fake2 = _whisper("gpt-4o-mini-transcribe", SimpleNamespace(
        text="Hola", usage=SimpleNamespace(type="tokens", input_token_details=SimpleNamespace(audio_tokens=37))))
    mp3 = tmp_path / "q.mp3"
    mp3.write_bytes(b"ID3fakeaudio")
    assert stt2.transcribe(mp3) == "Hola"
    assert "response_format" not in fake2.calls[0]
    assert stt2.last_duration_s == pytest.approx(3.7)  # estimado por tokens de audio


def test_m4_whisper_rejects_bad_inputs_without_calling_api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from briefer.providers.stt import whisper_api

    stt, fake = _whisper("gpt-4o-mini-transcribe", SimpleNamespace(text="x"))
    empty = tmp_path / "e.wav"
    empty.write_bytes(b"")
    with pytest.raises(ValueError, match="vacío"):
        stt.transcribe(empty)
    bad = tmp_path / "q.txt"
    bad.write_bytes(b"hola")
    with pytest.raises(ValueError, match="no admitido"):
        stt.transcribe(bad)
    with pytest.raises(FileNotFoundError):
        stt.transcribe(tmp_path / "no.wav")
    silent = tmp_path / "s.wav"
    silent.write_bytes(_wav_bytes(seconds=1.0, amplitude=0))
    assert stt.transcribe(silent) == ""  # silencio: no se llama (whisper alucina con audio mudo)
    big = tmp_path / "big.mp3"
    big.write_bytes(b"0" * 64)
    monkeypatch.setattr(whisper_api, "MAX_BYTES", 32)
    with pytest.raises(ValueError, match="25 MB"):
        stt.transcribe(big)
    assert fake.calls == []


def test_m4_voice_question_costs_stt(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """El paso ``qa.stt`` estima el coste con la duración que da el proveedor."""
    class PaidSTT(mock.MockSTT):
        provider_name = "openai"

        def __init__(self) -> None:
            self.model, self.last_duration_s = "gpt-4o-mini-transcribe", 60.0

        def transcribe(self, audio_path, language="es"):
            return "¿Qué tal el IBEX?"

    from briefer.providers import registry

    monkeypatch.setattr(registry, "get_stt", lambda *a, **k: PaidSTT())
    audio = tmp_path / "q.wav"
    audio.write_bytes(_wav_bytes())
    answer = pipeline.answer_question(audio, None, speak=False)
    stt_metric = next(m for m in answer.metrics if m.step == "qa.stt")
    assert stt_metric.est_cost_eur > 0


# ── M5: la portada no destaca briefings simulados ─────────────────────────────────


def test_m5_latest_briefing_skips_simulated(sample_briefing: Briefing, tmp_path: Path) -> None:
    outputs = tmp_path / "outs"
    real = sample_briefing.model_copy(update={
        "id": "20261005-080000-aaaaaa",
        "metrics": [StepMetric(step="agents.analyst", provider="anthropic", model="m", latency_s=1.0)],
    })
    demo = sample_briefing.model_copy(update={"id": "20261005-090000-bbbbbb"})  # métrica mock
    fell_back = real.model_copy(update={"id": "20261005-100000-cccccc", "metrics": [
        StepMetric(step="ingest.prices", provider="synthetic", model="-", latency_s=0.1,
                   error="Fallback a precios sintéticos tras X: y")]})
    for b in (real, demo, fell_back):
        storage.save_briefing(b, outputs)
    assert storage.is_simulated_briefing(demo) and storage.is_simulated_briefing(fell_back)
    assert not storage.is_simulated_briefing(real)
    assert storage.latest_briefing(outputs).id == real.id
    assert storage.latest_briefing(outputs, include_simulated=True).id == fell_back.id
    featured = storage.load_featured_briefing(outputs, tmp_path / "no_samples")
    assert featured is not None and featured[0].id == real.id and featured[1] == "guardado"


def test_m5_only_simulated_saved_falls_back_to_pregenerated(sample_briefing: Briefing, tmp_path: Path) -> None:
    outputs, samples = tmp_path / "outs", tmp_path / "samples"
    storage.save_briefing(sample_briefing, outputs)  # mock
    real = sample_briefing.model_copy(update={
        "id": "20261001-080000-dddddd",
        "metrics": [StepMetric(step="agents.analyst", provider="anthropic", model="m", latency_s=1.0)],
    })
    storage.export_briefing(real, storage.demo_briefing_dir(samples))
    briefing, origin = storage.load_featured_briefing(outputs, samples)
    assert origin == "pregenerado" and briefing.id == real.id


# ── M6: funciones en desarrollo desactivadas ──────────────────────────────────────


def test_m6_pending_features_disabled_in_ui() -> None:
    from streamlit.testing.v1 import AppTest

    if str(APP_DIR) not in sys.path:
        sys.path.insert(0, str(APP_DIR))
    at = AppTest.from_file(str(APP_DIR / "pages" / "1_Briefing.py"), default_timeout=60).run()
    assert not at.exception
    labels = {c.label: c for c in at.checkbox}
    assert labels["Generar vídeo corto"].disabled and labels["Generar portada con IA"].disabled
    assert at.multiselect[1].disabled  # «Enviar también por»
    at.button[0].click().run()  # generar: sin avisos de pasos fallidos ni entregas fallidas
    assert not at.exception
    warnings = "\n".join(w.value for w in at.warning)
    assert "fallaron" not in warnings and "Entregas fallidas" not in warnings


# ── M7: redacción de secretos ─────────────────────────────────────────────────────

FAKE_OPENAI = "sk-proj-ABCDEFGHIJKLMNOP1234567890"
FAKE_TG = "123456789:AAH-abcdefghijklmnopqrstuvwxyz012345"


@pytest.fixture
def secret_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OPENAI_API_KEY", FAKE_OPENAI)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", FAKE_TG)
    monkeypatch.setenv("GEMINI_API_KEY", "AQ.Ab8RN6-custom-gemini-secret")
    reset_settings_cache()
    yield
    reset_settings_cache()


def test_m7_redact_patterns_and_settings_values(secret_env) -> None:
    text = (f"ConnectionError: https://api.telegram.org/bot{FAKE_TG}/sendMessage failed; key={FAKE_OPENAI}; "
            "x AIzaSyA1234567890abcdefghij y sk-ant-api03-zzzzzzzzzzzzzz "
            "Authorization: Bearer abc.def AQ.Ab8RN6-custom-gemini-secret ?api_key=s3cr3t&x=1")
    out = redact_secrets(text)
    for secret in (FAKE_TG, FAKE_OPENAI, "AIzaSyA1234567890abcdefghij", "sk-ant-api03-zzzzzzzzzzzzzz",
                   "abc.def", "AQ.Ab8RN6-custom-gemini-secret", "s3cr3t", "AAH-abcdefghij"):
        assert secret not in out, secret
    assert "api.telegram.org/bot***" in out


def test_m7_track_step_fallback_and_pipeline_error_are_redacted(secret_env) -> None:
    exc = RuntimeError(f"401 https://api.telegram.org/bot{FAKE_TG}/sendAudio key {FAKE_OPENAI}")
    metrics: list[StepMetric] = []
    with pytest.raises(RuntimeError), track_step("delivery.telegram", "telegram", "-", metrics):
        raise exc
    assert FAKE_TG not in metrics[0].error and FAKE_OPENAI not in metrics[0].error
    assert FAKE_TG not in fallback_error("mock", exc) and FAKE_OPENAI not in error_text(exc)
    err = pipeline.PipelineStepError("agents.analyst", exc)
    assert FAKE_TG not in str(err) and FAKE_OPENAI not in str(err)
    # Un secreto que quedaría partido por el recorte tampoco se escapa (se redacta antes de recortar).
    long_exc = RuntimeError("x" * 150 + FAKE_OPENAI)
    assert FAKE_OPENAI[:12] not in error_text(long_exc, 160)


def test_m7_log_output_is_redacted(secret_env, capsys) -> None:
    import logging

    from briefer.logging_utils import _RedactingFormatter

    record = logging.LogRecord("briefer", logging.ERROR, __file__, 1, "fallo %s", (FAKE_OPENAI,), None)
    assert FAKE_OPENAI not in _RedactingFormatter("%(message)s").format(record)


def test_m7_show_error_hides_traceback_and_secrets(secret_env, monkeypatch: pytest.MonkeyPatch) -> None:
    from streamlit.testing.v1 import AppTest

    if str(APP_DIR) not in sys.path:
        sys.path.insert(0, str(APP_DIR))

    def boom(*_a, **_k):
        raise pipeline.PipelineStepError("media.podcast", ConnectionError(f"https://x/bot{FAKE_TG}/y"))

    monkeypatch.setattr(pipeline, "run_briefing", boom)
    at = AppTest.from_file(str(APP_DIR / "pages" / "1_Briefing.py"), default_timeout=60).run()
    at.button[0].click().run()
    shown = "\n".join(e.value for e in at.error) + "\n".join(c.value for c in at.code)
    assert "media.podcast" in shown and FAKE_TG not in shown
    assert not at.code  # sin traceback salvo BRIEFER_LOG_LEVEL=DEBUG


# ── Peticiones cruzadas: gráficos con precios sintéticos y stats de noticias ─────


def test_charts_say_synthetic_prices_in_demo(monkeypatch: pytest.MonkeyPatch) -> None:
    sources: list[object] = []
    real = charts_mod.make_charts

    def spy(*args, **kwargs):
        sources.append(kwargs.get("source"))
        return real(*args, **kwargs)

    monkeypatch.setattr(charts_mod, "make_charts", spy)
    pipeline.run_briefing(["SAN.MC"], use_mock=True)
    assert sources == [pipeline.SYNTHETIC_PRICES_SOURCE]


def test_real_mode_news_stats_in_detail_and_synthetic_fallback_labelled(monkeypatch: pytest.MonkeyPatch) -> None:
    from briefer.ingest import news as news_mod
    from briefer.ingest import prices as prices_mod

    def fake_fetch(tickers, *, stats_out=None, **_kw):
        stats_out["fetch"] = {"google:SAN.MC": {"items": 3, "cached": True, "error": None},
                              "bing:SAN.MC": {"items": 0, "cached": False, "error": "timeout"}}
        stats_out["quality"] = {"sources_latency_s": 1.2, "selected": 4, "with_summary": 3,
                                "near_duplicates": 2, "landing_pages": 1,
                                "enrich": {"candidates": 2, "resolved": 1, "summaries": 1, "timed_out": 0}}
        return news_mod.load_sample_news()

    def no_prices(*_a, **_k):
        raise prices_mod.PriceFetchError("sin red")

    monkeypatch.setattr(news_mod, "fetch_news", fake_fetch)
    monkeypatch.setattr(prices_mod, "get_price_snapshots", no_prices)
    sources: list[object] = []
    real = charts_mod.make_charts
    monkeypatch.setattr(charts_mod, "make_charts", lambda *a, **k: sources.append(k.get("source")) or real(*a, **k))
    briefing = pipeline.run_briefing(["SAN.MC"], mode="real")
    news_metric = next(m for m in briefing.metrics if m.step == "ingest.news")
    assert "2 fuentes (1 fallidas, 1 de caché)" in news_metric.detail
    assert "4 seleccionadas (3 con extracto)" in news_metric.detail
    prices_metric = next(m for m in briefing.metrics if m.step == "ingest.prices")
    assert prices_metric.provider == "synthetic"
    assert sources == [pipeline.SYNTHETIC_PRICES_SOURCE]


def test_format_news_stats_empty() -> None:
    from briefer.ingest.news import format_news_stats

    assert format_news_stats({}) is None


# ── SHOULD aplicados ──────────────────────────────────────────────────────────────


def test_s10_fallback_script_in_finalize_uses_configured_names(monkeypatch: pytest.MonkeyPatch) -> None:
    from briefer.agents import scriptwriter

    analysis = mock.sample_analysis()
    monkeypatch.setattr(scriptwriter, "merge_long_runs", lambda lines: [])  # guion vacío tras reparar
    out = scriptwriter._finalize(mock.sample_script(), analysis, None, ("Nuria", "Pablo"))
    text = " ".join(line.text for line in out.lines)
    assert "Nuria" in text and brand.SPEAKER_A_NAME not in text


def test_s6_no_nested_retries_with_edge(monkeypatch: pytest.MonkeyPatch) -> None:
    from briefer.media import podcast

    seen: list[int] = []
    real = podcast.synthesize_podcast

    def spy(script, tts, out_dir, **kw):
        seen.append(kw.get("retries"))
        return real(script, tts, out_dir, **kw)

    monkeypatch.setattr(podcast, "synthesize_podcast", spy)
    pipeline.run_briefing(["SAN.MC"], use_mock=True)  # TTS mock: conserva los reintentos del podcast

    class FakeEdge(mock.MockTTS):
        provider_name = "edge"

    monkeypatch.setattr(pipeline, "demo_voice_tts", lambda _s: FakeEdge())
    pipeline.run_briefing(["SAN.MC"], mode="demo_voices")  # edge ya reintenta: 0 en el podcast
    assert seen == [2, 0]


def test_export_with_relative_dest_dir_writes_folder_relative_paths(
    sample_briefing: Briefing, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``export_briefing(b, Path("data/samples/demo_briefing"))`` (ruta relativa) debe dejar rutas
    relativas a la carpeta del JSON (``charts/x.png``), no a la carpeta de trabajo."""
    gen = tmp_path / "gen"
    gen.mkdir()
    for name in ("podcast.mp3", "podcast.srt", "c.png"):
        (gen / name).write_bytes(b"x")
    b = sample_briefing.model_copy(update={
        "audio": sample_briefing.audio.model_copy(update={"path": gen / "podcast.mp3"}),
        "transcript": sample_briefing.transcript.model_copy(update={"srt_path": gen / "podcast.srt"}),
        "charts": [sample_briefing.charts[0].model_copy(update={"path": gen / "c.png"})],
        "video": None,
    })
    monkeypatch.chdir(tmp_path)
    path = storage.export_briefing(b, Path("rel") / "demo_briefing")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["audio"]["path"] == "podcast.mp3" and data["charts"][0]["path"] == "charts/c.png"
    loaded = storage.load_briefing(path)
    assert Path(loaded.charts[0].path).is_file() and Path(loaded.audio.path).is_file()


def test_m1_portfolio_chart_tmp_dirs_are_purged(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import os
    import tempfile
    import time as _time

    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
    old = tmp_path / "briefer_cartera" / "viejo"
    old.mkdir(parents=True)
    past = _time.time() - (pipeline.PORTFOLIO_CHART_TTL_H + 1) * 3600
    os.utime(old, (past, past))
    new = pipeline._portfolio_chart_dir("20261005-000000-abcdef")
    assert new.parent == tmp_path / "briefer_cartera" and new.is_dir()
    assert not old.exists()


# ── Pista de vocabulario para el STT (nombres del briefing) ───────────────────────


def test_vocabulary_hint_uses_company_names() -> None:
    from briefer.ingest import voice

    hint = voice.vocabulary_hint(["AAPL", "itx.mc", "AAPL", "ZZZ.MC"])
    assert hint.startswith("Vocabulario: Apple, Inditex, ZZZ,") and "IBEX 35" in hint
    assert voice.vocabulary_hint(None) == "" and voice.vocabulary_hint([]) == ""


def test_whisper_sends_prompt_only_when_given(tmp_path: Path) -> None:
    audio = tmp_path / "q.wav"
    audio.write_bytes(_wav_bytes(seconds=1.0, amplitude=3000))
    stt, fake = _whisper("gpt-4o-mini-transcribe", SimpleNamespace(text="¿Por qué sube Apple?"))
    assert stt.transcribe(audio, "es", prompt="Vocabulario: Apple.") == "¿Por qué sube Apple?"
    assert fake.calls[0]["prompt"] == "Vocabulario: Apple."


def test_transcribe_question_passes_hint_and_drops_echo(tmp_path: Path) -> None:
    from briefer.ingest import voice

    audio = tmp_path / "q.wav"
    audio.write_bytes(_wav_bytes())
    seen: dict = {}

    class HintSTT(mock.MockSTT):
        def transcribe(self, audio_path, language="es", prompt=None):
            seen["prompt"] = prompt
            return self.reply

    stt = HintSTT()
    stt.reply = "¿Qué ha pasado con Apple?"
    hint = voice.vocabulary_hint(["AAPL"])
    assert voice.transcribe_question(audio, stt, vocabulary=hint) == "¿Qué ha pasado con Apple?"
    assert seen["prompt"] == hint
    stt.reply = "Vocabulario: Apple"  # eco de la pista ante audio sin voz
    with pytest.raises(ValueError, match="No se ha entendido"):
        voice.transcribe_question(audio, stt, vocabulary=hint)


def test_transcribe_question_old_signature_stt_still_works(tmp_path: Path) -> None:
    from briefer.ingest import voice

    audio = tmp_path / "q.wav"
    audio.write_bytes(_wav_bytes())

    class OldSTT(mock.MockSTT):
        def transcribe(self, audio_path, language="es"):
            return "Hola"

    assert voice.transcribe_question(audio, OldSTT(), vocabulary="Vocabulario: Apple.") == "Hola"
