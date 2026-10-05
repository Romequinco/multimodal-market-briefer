"""Estados vacíos y de error de la UI (AppTest, sin red): CSV de cartera mal formado, histórico vacío o
con briefings dañados / sin audio, «Borrar mis datos» y la página Briefing sin valores."""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

from briefer import pipeline, storage
from briefer.config import ROOT_DIR, reset_settings_cache
from briefer.ingest.portfolio import load_portfolio_csv

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from components.players import portfolio_error_message  # noqa: E402

TIMEOUT = 60


def _app(name: str) -> AppTest:
    return AppTest.from_file(str(APP_DIR / name), default_timeout=TIMEOUT)


def _texts(elements) -> str:
    return "\n".join(str(e.value) for e in elements)


def _button(at: AppTest, label: str):
    return next(b for b in at.button if b.label == label)


# ── Mi cartera: CSV mal formados ───────────────────────────────────────────────────

BAD_CSVS = {
    "vacio": (b"", "vacío"),
    "solo_espacios": (b"  \n \n", "vacío"),
    "sin_columna_ticker": (b"nombre,peso\nSantander,1\n", "columna 'ticker'"),
    "sin_pesos_ni_cantidad": (b"ticker,nombre\nSAN.MC,Santander\n", "'weight'"),
    "peso_no_numerico": (b"ticker,weight\nSAN.MC,mucho\nAAPL,0.5\n", "no numérico"),
    "peso_negativo": (b"ticker,weight\nSAN.MC,-0.5\nAAPL,1.5\n", "negativo"),
    "no_suman_1": (b"ticker,weight\nSAN.MC,0.3\nAAPL,0.3\n", "deben sumar 1"),
    "no_suman_100": (b"ticker;weight\nSAN.MC;30\nAAPL;30\n", "deben sumar 1"),
    "solo_cabecera": (b"ticker,weight\n", "ninguna posición"),
    "binario": (bytes(range(256)) * 4, ""),
}


@pytest.mark.parametrize("case", sorted(BAD_CSVS))
def test_bad_portfolio_csv_gives_friendly_spanish_message(case: str) -> None:
    content, expected = BAD_CSVS[case]
    with pytest.raises(Exception) as info:
        load_portfolio_csv(content.decode("latin-1") if case == "binario" else _as_file(content))
    msg = portfolio_error_message(info.value)
    assert msg and "Traceback" not in msg and "\n" not in msg and len(msg) <= 300
    assert expected in msg


def _as_file(content: bytes) -> io.BytesIO:
    return io.BytesIO(content)


def test_bom_and_cp1252_csv_load_fine() -> None:
    bom = "﻿ticker;peso\nSAN.MC;60 %\nAAPL;40 %\n".encode()
    assert [p.ticker for p in load_portfolio_csv(_as_file(bom)).positions] == ["SAN.MC", "AAPL"]
    cp1252 = "ticker,weight,nombre\nSAN.MC,0.5,España\nAAPL,0.5,Cañón\n".encode("cp1252")  # Excel antiguo
    assert len(load_portfolio_csv(_as_file(cp1252)).positions) == 2


def test_unexpected_errors_get_generic_message() -> None:
    from pydantic import BaseModel, ValidationError

    class M(BaseModel):
        x: int

    with pytest.raises(ValidationError) as info:
        M(x="no")
    assert "ticker" in portfolio_error_message(info.value)
    assert "CSV" in portfolio_error_message(TypeError("raro"))
    assert "UTF-8" in portfolio_error_message(UnicodeDecodeError("utf-8", b"\xff", 0, 1, "x"))


@pytest.fixture
def bad_sample(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    samples = tmp_path / "samples"
    samples.mkdir()
    (samples / "portfolio_ejemplo.csv").write_text("nombre,peso\nSantander,1\n", encoding="utf-8")
    monkeypatch.setenv("BRIEFER_SAMPLES_DIR", str(samples))
    reset_settings_cache()
    return samples


def test_portfolio_page_shows_friendly_error_not_traceback(bad_sample: Path) -> None:
    at = _app("pages/3_Mi_cartera.py").run()
    _button(at, "Usar cartera de ejemplo").click().run()
    assert not at.exception
    errors = _texts(at.error)
    assert "No se pudo cargar la cartera" in errors and "columna 'ticker'" in errors
    assert "Traceback" not in errors
    assert "portfolio" not in at.session_state
    assert any("Cómo debe ser el CSV" in e.label for e in at.expander)


def test_portfolio_page_keeps_previous_portfolio_on_error(bad_sample: Path) -> None:
    good = load_portfolio_csv(_as_file(b"ticker,weight\nAAPL,1\n"), name="Buena")
    at = _app("pages/3_Mi_cartera.py")
    at.session_state["portfolio"] = good
    at.run()
    _button(at, "Usar cartera de ejemplo").click().run()
    assert not at.exception
    assert at.session_state["portfolio"].name == "Buena"
    assert "Se mantiene la cartera" in _texts(at.caption)


# ── Histórico: vacío, dañado, sin audio ────────────────────────────────────────────


def test_history_empty_state() -> None:
    at = _app("pages/4_Historico.py").run()
    assert not at.exception
    assert "Todavía no hay briefings guardados" in _texts(at.info)
    assert _button(at, "Borrar mis datos").disabled  # zona de peligro visible, pero sin confirmar


def test_history_marks_briefing_without_required_fields_and_missing_audio() -> None:
    saved = pipeline.run_briefing(["SAN.MC"], use_mock=True)
    assert saved.audio is not None
    Path(saved.audio.path).unlink()  # el audio desaparece del disco
    broken = storage.briefing_dir("29991231-235959-ffffff")  # JSON válido pero sin campos obligatorios
    (broken / storage.BRIEFING_FILE).write_text(json.dumps({"id": "29991231-235959-ffffff"}), encoding="utf-8")
    storage.briefing_dir("29991230-000000-eeeeee")  # carpeta sin briefing.json: no se lista
    at = _app("pages/4_Historico.py").run()
    assert not at.exception
    options = at.selectbox[0].options
    assert len(options) == 2
    assert "no está disponible" in _texts(at.warning)
    at.selectbox[0].set_value(saved.id).run()
    assert not at.exception
    assert any("sin audio en disco" in o for o in at.selectbox[0].options)
    assert "ya no está en disco" in _texts(at.info)


def test_history_delete_single_briefing_needs_confirmation() -> None:
    first = pipeline.run_briefing(["SAN.MC"], use_mock=True)
    at = _app("pages/4_Historico.py").run()
    btn = _button(at, "Borrar este briefing")
    assert btn.disabled
    next(c for c in at.checkbox if c.label.startswith("Sí, quiero borrar")).check().run()
    _button(at, "Borrar este briefing").click().run()
    assert not at.exception
    assert "Briefing borrado" in _texts(at.success)
    assert storage.list_briefings() == []
    assert "briefing" not in at.session_state or at.session_state["briefing"].id != first.id


def test_history_delete_all_user_data_keeps_samples() -> None:
    pipeline.run_briefing(["SAN.MC"], use_mock=True)
    from briefer.config import get_settings

    cache = get_settings().cache_path
    (cache / "uploads").mkdir(parents=True, exist_ok=True)
    (cache / "uploads" / "x.pdf").write_bytes(b"x")
    demo = storage.demo_briefing_dir() / storage.BRIEFING_FILE
    demo_existed = demo.is_file()
    at = _app("pages/4_Historico.py")
    at.session_state["portfolio"] = load_portfolio_csv(_as_file(b"ticker,weight\nAAPL,1\n"))
    at.run()
    assert _button(at, "Borrar mis datos").disabled  # sin confirmar no se puede pulsar
    assert storage.list_briefings()
    next(c for c in at.checkbox if c.label.startswith("Entiendo")).check().run()
    assert not _button(at, "Borrar mis datos").disabled
    _button(at, "Borrar mis datos").click().run()
    assert not at.exception
    assert "Datos borrados: 1 briefing(s)" in _texts(at.success)
    assert storage.list_briefings() == [] and not any(cache.iterdir())
    assert "portfolio" not in at.session_state
    assert demo.is_file() == demo_existed  # el pregenerado del repo sigue ahí
    assert (ROOT_DIR / "data" / "samples").is_dir()
    assert "Todavía no hay briefings guardados" in _texts(at.info)


# ── Briefing sin valores ───────────────────────────────────────────────────────────


def test_briefing_page_without_tickers_disables_generate() -> None:
    at = _app("pages/1_Briefing.py").run()
    at.multiselect[0].set_value([]).run()
    assert not at.exception
    assert _button(at, "Generar briefing").disabled
    assert "Elige al menos un valor" in _texts(at.caption)

