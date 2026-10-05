"""Test de extremo a extremo del pipeline con proveedores mock (sin red ni claves).

Se activa cuando los módulos de ``ingest``, ``agents``, ``media`` y ``storage`` dejen de
lanzar ``NotImplementedError``: basta con quitar el ``skip``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from briefer.config import Settings
from briefer.schemas import Briefing, QAAnswer

PENDING = (
    "TODO: activar cuando ingest/agents/media/storage estén implementados "
    "(hoy lanzan NotImplementedError)."
)


@pytest.mark.skip(reason=PENDING)
def test_run_briefing_with_mocks(settings: Settings) -> None:
    from briefer.pipeline import run_briefing

    briefing = run_briefing(["SAN.MC", "AAPL"], use_mock=True, settings=settings)
    assert isinstance(briefing, Briefing)
    assert briefing.analysis.key_points
    assert {line.speaker for line in briefing.script.lines} == {"A", "B"}
    assert briefing.audio is not None and Path(briefing.audio.path).exists()
    assert briefing.transcript is not None
    assert briefing.charts
    assert any(m.step == "agents.analyst" for m in briefing.metrics)
    assert (settings.output_path / briefing.id / "briefing.json").exists()


@pytest.mark.skip(reason=PENDING)
def test_answer_question_with_mocks(settings: Settings, sample_briefing: Briefing) -> None:
    from briefer.pipeline import answer_question

    answer = answer_question("¿Por qué sube el Santander?", sample_briefing, use_mock=True, settings=settings)
    assert isinstance(answer, QAAnswer)
    assert answer.answer_text
    assert answer.audio_path is not None and Path(answer.audio_path).exists()


def test_pipeline_module_imports() -> None:
    """La orquestación debe importar aunque los módulos sean stubs."""
    import briefer.pipeline as pipeline

    assert callable(pipeline.run_briefing) and callable(pipeline.answer_question)
