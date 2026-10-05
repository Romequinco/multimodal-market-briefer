"""Las 5 páginas de la UI con ``streamlit.testing.v1.AppTest`` (modo demo, sin red ni claves).

``conftest._mock_env`` deja todos los proveedores en mock y las salidas en un directorio temporal.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from briefer import brand, pipeline, storage
from briefer.config import reset_settings_cache

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

TIMEOUT = 60


def _app(name: str) -> AppTest:
    return AppTest.from_file(str(APP_DIR / name), default_timeout=TIMEOUT)


def _texts(elements) -> str:
    return "\n".join(str(e.value) for e in elements)


@pytest.fixture
def empty_samples(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Carpeta de samples sin briefing pregenerado (aísla el test del contenido del repo)."""
    import shutil

    real = Path(__file__).resolve().parents[1] / "data" / "samples"
    samples = tmp_path / "samples"
    samples.mkdir()
    for f in real.iterdir():  # datos de ejemplo sí; demo_briefing/ no
        if f.is_file():
            shutil.copy2(f, samples / f.name)
    monkeypatch.setenv("BRIEFER_SAMPLES_DIR", str(samples))
    reset_settings_cache()
    return samples


def _make_demo(samples: Path) -> None:
    briefing = pipeline.run_briefing(["SAN.MC", "AAPL"], use_mock=True)
    storage.export_briefing(briefing, storage.demo_briefing_dir(samples))
    # Que la portada no lo encuentre como «guardado»: se vacía data/outputs
    for path in storage.list_briefings():
        path.unlink()


# ── Portada ────────────────────────────────────────────────────────────────────────


def test_home_without_any_briefing_shows_friendly_message(empty_samples: Path) -> None:
    at = _app("main.py").run()
    assert not at.exception
    assert at.title[0].value == brand.BRAND_NAME
    assert "Todavía no hay ningún briefing" in _texts(at.info)
    assert "MODO DEMO" in _texts(at.sidebar.markdown)


def test_home_shows_pregenerated_briefing(empty_samples: Path) -> None:
    _make_demo(empty_samples)
    at = _app("main.py").run()
    assert not at.exception
    assert "pregenerado" in _texts(at.markdown)  # insignia de origen
    assert at.get("audio"), "la portada debe tener el reproductor del podcast"
    assert at.get("graphviz_chart"), "la pestaña «Cómo se hizo» debe dibujar la traza"
    assert "sintéticas" in _texts(at.caption)
    assert any("Cómo se hizo:" in c.value for c in at.caption), "franja de traza visible sin pulsar nada"
    labels = [b.label for b in at.get("download_button")]
    assert any("audio" in label for label in labels) and any(".srt" in label for label in labels)


def _as_real(briefing):
    """Copia del briefing con métricas de proveedores reales (simula un briefing 100 % real)."""
    real = {"ingest.news": "yfinance+rss", "ingest.prices": "yfinance", "agents.analyst": "anthropic",
            "agents.scriptwriter": "anthropic", "media.podcast": "edge"}
    metrics = [m.model_copy(update={"provider": real.get(m.step, m.provider), "model": "x"})
               if m.step in real else m for m in briefing.metrics]
    return briefing.model_copy(update={"metrics": metrics})


def test_home_skips_saved_mock_briefing_and_keeps_pregenerated(empty_samples: Path) -> None:
    """M5: un ensayo en «Demo offline» no tapa el pregenerado real de la portada."""
    _make_demo(empty_samples)
    demo_id = storage.load_demo_briefing().id
    saved = pipeline.run_briefing(["ITX.MC"], use_mock=True)  # se guarda en data/outputs (tmp)
    assert storage.is_simulated_briefing(saved)
    at = _app("main.py").run()
    assert not at.exception
    assert "pregenerado" in _texts(at.markdown)
    assert at.session_state["briefing"].id == demo_id != saved.id


def test_home_prefers_latest_saved_real_briefing(empty_samples: Path) -> None:
    _make_demo(empty_samples)
    saved = _as_real(pipeline.run_briefing(["ITX.MC"], use_mock=True))
    storage.save_briefing(saved)
    at = _app("main.py").run()
    assert not at.exception
    assert "Último briefing guardado" in _texts(at.markdown)
    assert at.session_state["briefing"].id == saved.id


# ── Briefing ───────────────────────────────────────────────────────────────────────


def test_briefing_page_defaults_and_demo_mode() -> None:
    at = _app("pages/1_Briefing.py").run()
    assert not at.exception
    assert at.multiselect[0].value == ["SAN.MC", "ITX.MC", "IBE.MC", "AAPL", "NVDA"]
    toggle = at.sidebar.toggle[0]
    assert toggle.value is False and toggle.disabled  # sin claves: modo real bloqueado
    assert "Modo real no disponible" in _texts(at.sidebar.caption)


def test_briefing_page_generates_in_demo_mode() -> None:
    at = _app("pages/1_Briefing.py").run()
    at.button[0].click().run()
    assert not at.exception
    assert not at.error, _texts(at.error)
    status = at.status[0]
    assert status.state == "complete" and status.label == "Briefing listo"
    progress_lines = [m.value for m in status.markdown if m.value.startswith("(")]
    assert progress_lines and progress_lines[-1].endswith("Briefing listo.")
    assert "briefing" in at.session_state
    assert [t.label for t in at.tabs] == ["Puntos clave", "Transcripción", "Gráficos", "Cómo se hizo"]
    assert at.get("graphviz_chart")
    labels = [b.label for b in at.get("download_button")]
    assert "Descargar audio (wav)" in labels and "Descargar subtítulos (.srt)" in labels
    assert any("demostración" in c.value for c in at.caption)


def test_briefing_page_friendly_error_with_step(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*args, **kwargs):
        raise pipeline.PipelineStepError("media.podcast", RuntimeError("sin conexión"))

    monkeypatch.setattr(pipeline, "run_briefing", boom)
    at = _app("pages/1_Briefing.py").run()
    at.button[0].click().run()
    assert not at.exception
    assert at.status[0].state == "error"
    assert "media.podcast" in at.status[0].label
    assert "sin conexión" in _texts(at.error)


def test_briefing_page_shows_fallback_warning() -> None:
    from briefer.schemas import StepMetric

    briefing = pipeline.run_briefing(["SAN.MC"], use_mock=True)
    metrics = [m.model_copy(update={"provider": "anthropic", "model": "claude"}) if m.step == "agents.analyst"
               else m for m in briefing.metrics]
    metrics.append(StepMetric(step="agents.scriptwriter", provider="mock", model="mock-llm", latency_s=0.0,
                              error="APIStatusError: 529"))
    at = _app("pages/1_Briefing.py")
    at.session_state["briefing"] = briefing.model_copy(update={"metrics": metrics})
    at.run()
    assert not at.exception
    assert "cayeron a mock" in _texts(at.warning)


# ── Preguntar, Mi cartera, Histórico ───────────────────────────────────────────────


def test_ask_page_answers_in_demo_mode() -> None:
    at = _app("pages/2_Preguntar.py").run()
    assert not at.exception
    at.text_input[0].input("¿Qué ha pasado hoy con el Santander?").run()
    at.button[0].click().run()
    assert not at.exception
    assert not at.error, _texts(at.error)
    assert at.session_state["qa_answers"]
    assert "Pregunta:" in _texts(at.markdown)


def test_portfolio_page_loads_sample() -> None:
    at = _app("pages/3_Mi_cartera.py").run()
    assert not at.exception
    at.button[0].click().run()  # «Usar cartera de ejemplo»
    assert not at.exception
    assert at.session_state["portfolio"].positions
    assert len(at.dataframe) == 1


def test_history_page_opens_saved_briefing() -> None:
    saved = pipeline.run_briefing(["SAN.MC"], use_mock=True)
    at = _app("pages/4_Historico.py").run()
    assert not at.exception
    assert at.selectbox[0].value == saved.id  # se abre el más reciente sin pulsar nada
    assert at.session_state["briefing"].id == saved.id
    assert at.get("graphviz_chart")


def test_history_page_empty() -> None:
    at = _app("pages/4_Historico.py").run()
    assert not at.exception
    assert "Todavía no hay briefings guardados" in _texts(at.info)


# ── Integración F1: modos, refresco de caché e insignias de sustituto ─────────────


def test_briefing_page_offers_demo_with_real_voices() -> None:
    at = _app("pages/1_Briefing.py").run()
    assert not at.exception
    radio = at.sidebar.radio[0]
    assert radio.options == ["Demo sin claves (voces reales)", "Demo offline (mock, sin red)"]
    # Con BRIEFER_TTS_PROVIDER=mock explícito (tests/CI) la demo por defecto es la offline.
    assert radio.value == "mock"
    refresh = next(b for b in at.button if b.label == "Refrescar datos")
    assert refresh.disabled  # solo en modo real
    radio.set_value("demo_voices").run()
    assert not at.exception
    assert "MODO DEMO SIN CLAVES" in _texts(at.markdown)


def test_briefing_page_marks_sample_fallback_as_substitute() -> None:
    from briefer.logging_utils import fallback_error

    briefing = pipeline.run_briefing(["SAN.MC"], use_mock=True)
    metrics = []
    for m in briefing.metrics:
        if m.step == "agents.analyst":
            m = m.model_copy(update={"provider": "anthropic", "model": "claude", "detail": "grounding OK"})
        if m.step == "ingest.news":
            m = m.model_copy(update={"error": fallback_error("data/samples", ConnectionError("sin red"))})
        metrics.append(m)
    at = _app("pages/1_Briefing.py")
    at.session_state["briefing"] = briefing.model_copy(update={"metrics": metrics})
    at.run()
    assert not at.exception
    warnings = _texts(at.warning)
    assert "cayeron a mock o a datos de ejemplo" in warnings and "datos de ejemplo (sustituto)" in warnings
    assert "fallaron" not in warnings  # el sustituto no se cuenta como error
    assert "grounding OK" in _texts(at.caption)
