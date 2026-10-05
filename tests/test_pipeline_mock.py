"""Tests de extremo a extremo del pipeline con proveedores mock reales (sin red ni claves).

A diferencia de ``test_agents_mock.py`` (que sustituye ingest/media/storage por dobles), aquí
corren los módulos de verdad de los tres carriles con ``use_mock=True``.
"""

from __future__ import annotations

from pathlib import Path

from briefer.config import ROOT_DIR, Settings
from briefer.logging_utils import step_failed
from briefer.providers.mock import write_silence_wav
from briefer.schemas import Briefing, QAAnswer

SAMPLES_DIR = ROOT_DIR / "data" / "samples"


def test_run_briefing_with_mocks(settings: Settings) -> None:
    from briefer.pipeline import run_briefing

    briefing = run_briefing(["SAN.MC", "AAPL"], use_mock=True, settings=settings)
    assert isinstance(briefing, Briefing)
    assert briefing.analysis.key_points
    assert {line.speaker for line in briefing.script.lines} == {"A", "B"}
    assert briefing.audio is not None and Path(briefing.audio.path).exists()
    assert briefing.audio.duration_s > 0
    assert briefing.transcript is not None
    assert briefing.charts and all(Path(c.path).exists() for c in briefing.charts)
    assert any(m.step == "agents.analyst" for m in briefing.metrics)
    assert not any(step_failed(m) for m in briefing.metrics)
    assert (settings.output_path / briefing.id / "briefing.json").exists()


def test_run_briefing_normalizes_company_names(settings: Settings) -> None:
    from briefer.pipeline import run_briefing

    briefing = run_briefing(["santander", "Telefonica", "aapl"], use_mock=True, settings=settings)
    assert briefing.context.tickers == ["SAN.MC", "TEF.MC", "AAPL"]


def test_run_briefing_with_uploads_end_to_end(settings: Settings, tmp_path: Path) -> None:
    """PDF + gráfico + nota de voz -> tres DocumentInsight en el contexto, sin pasos fallidos."""
    from briefer.pipeline import run_briefing

    pdf = SAMPLES_DIR / "resultados_ejemplo.pdf"
    png = SAMPLES_DIR / "grafico_ejemplo.png"
    wav = write_silence_wav(tmp_path / "nota_voz.wav", duration_s=0.2)
    assert pdf.exists() and png.exists()

    briefing = run_briefing(["SAN.MC", "AAPL"], uploads=[pdf, png, wav], use_mock=True, settings=settings)

    by_type = {i.source_type: i for i in briefing.context.insights}
    assert set(by_type) == {"pdf", "chart", "voice"}
    assert by_type["pdf"].source_name == "resultados_ejemplo.pdf"
    assert "1.245" in by_type["pdf"].key_figures.get("Ingresos 3T 2026", "")
    assert by_type["pdf"].extracted_text  # texto real extraído con pypdf
    assert "22,44" in by_type["chart"].key_figures.get("Último cierre", "")
    assert by_type["voice"].source_name == "nota_voz.wav" and by_type["voice"].extracted_text
    for insight in briefing.context.insights:
        assert "(mock)" not in insight.summary  # nada de relleno genérico de fake_instance

    steps = [m.step for m in briefing.metrics]
    for expected in ("ingest.pdf", "ingest.chart", "ingest.voice"):
        assert expected in steps
    assert not any(step_failed(m) for m in briefing.metrics)
    assert briefing.audio is not None and Path(briefing.audio.path).exists()
    saved = Briefing.model_validate_json(
        (settings.output_path / briefing.id / "briefing.json").read_text(encoding="utf-8")
    )
    assert len(saved.context.insights) == 3


def test_failed_upload_is_reported_in_metrics(settings: Settings, tmp_path: Path) -> None:
    from briefer.pipeline import run_briefing

    bad = tmp_path / "roto.pdf"
    bad.write_bytes(b"esto no es un pdf")
    briefing = run_briefing(["SAN.MC"], uploads=[bad], use_mock=True, settings=settings)
    assert briefing.context.insights == []
    failed = [m for m in briefing.metrics if step_failed(m)]
    assert [m.step for m in failed] == ["ingest.pdf"] and failed[0].error


def test_answer_question_with_mocks(settings: Settings, sample_briefing: Briefing) -> None:
    from briefer.pipeline import answer_question

    answer = answer_question("¿Por qué sube el Santander?", sample_briefing, use_mock=True, settings=settings)
    assert isinstance(answer, QAAnswer)
    assert answer.answer_text
    assert answer.audio_path is not None and Path(answer.audio_path).exists()
    assert [m.step for m in answer.metrics] == ["agents.qa", "qa.tts"]
    assert sum(m.latency_s for m in answer.metrics) < 10


def test_answer_voice_question_with_mocks(
    settings: Settings, sample_briefing: Briefing, tmp_path: Path
) -> None:
    from briefer.pipeline import answer_question

    audio = write_silence_wav(tmp_path / "pregunta.wav", duration_s=0.2)
    answer = answer_question(audio, sample_briefing, use_mock=True, settings=settings)
    assert answer.question and answer.answer_text
    assert [m.step for m in answer.metrics] == ["qa.stt", "agents.qa", "qa.tts"]


def test_pipeline_module_imports() -> None:
    import briefer.pipeline as pipeline

    assert callable(pipeline.run_briefing) and callable(pipeline.answer_question)
