"""Robustez del carril A sin red: entradas raras en PDF, imágenes, audio, cartera, tickers,
precios (mercado cerrado, yfinance lento) y caché concurrente. Cada test cubre un fallo real
encontrado en la revisión del 05-oct-2026 (ver docstrings de ``ingest/*``)."""

from __future__ import annotations

import io
import json
import sys
import threading
import time
import types
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest
from PIL import Image

from briefer.config import ROOT_DIR
from briefer.ingest import cache, chart_reader, pdf_reader, portfolio, prices, tickers, voice
from briefer.providers.mock import MockLLM, MockVision
from briefer.schemas import DocumentInsight

SAMPLE_PDF = ROOT_DIR / "data" / "samples" / "resultados_ejemplo.pdf"


# ── tickers ───────────────────────────────────────────────────────────────────────


def test_short_symbols_need_dollar_prefix() -> None:
    universe = ["F", "GM", "SAN.MC"]
    assert tickers.extract_tickers("La Fase F del plan y la GM del sector", universe) == []
    assert tickers.extract_tickers("Ford ($F) y General Motors ($GM) suben", universe) == ["F", "GM"]
    assert tickers.extract_tickers("SAN sube", universe) == ["SAN.MC"]  # raíz de 3 letras: sin cambios


# ── voz ───────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("suffix", ["/../../evil.wav", "..\\x.wav", ".wav/../../a", "." + "a" * 20, ""])
def test_save_audio_upload_sanitizes_suffix(tmp_path: Path, suffix: str) -> None:
    out = voice.save_audio_upload(b"RIFF", tmp_path / "audio", suffix=suffix)
    assert out.parent == tmp_path / "audio" and out.suffix == ".wav"


def test_save_audio_upload_keeps_valid_suffix(tmp_path: Path) -> None:
    assert voice.save_audio_upload(b"OggS", tmp_path, suffix="OGG").suffix == ".ogg"


# ── cartera ───────────────────────────────────────────────────────────────────────


def test_portfolio_ignores_total_rows_and_currency_symbols() -> None:
    csv_text = "Valor;Peso;Cantidad\nSAN.MC;60 %;1.000\nAAPL;40 %;12\nTotal;100 %;\n"
    pf = portfolio.load_portfolio_csv(csv_text)
    assert [p.ticker for p in pf.positions] == ["SAN.MC", "AAPL"]
    assert pf.positions[0].weight == pytest.approx(0.6)
    euros = portfolio.load_portfolio_csv("ticker;quantity\nITX.MC;1.234,5 €\nIBE.MC;10 EUR\n")
    assert euros.positions[0].quantity == pytest.approx(1234.5) and euros.positions[1].quantity == 10


# ── imágenes ──────────────────────────────────────────────────────────────────────


def _image_bytes(fmt: str, size=(32, 32)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, (10, 120, 200)).save(buf, format=fmt)
    return buf.getvalue()


def test_validate_image_accepts_mpo_from_phones(monkeypatch) -> None:
    # Pillow identifica muchas fotos JPEG de móvil como «MPO»; se simula con un JPEG renombrado.
    data = _image_bytes("JPEG")
    real_open = Image.open

    def fake_open(fp, *a, **k):
        img = real_open(fp, *a, **k)
        img.format = "MPO"
        return img

    monkeypatch.setattr(Image, "open", fake_open)
    assert chart_reader.validate_image(data) == "MPO"


def test_validate_image_rejects_decompression_bomb(monkeypatch) -> None:
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100)  # 32x32 = 1024 px > 2x límite
    with pytest.raises(ValueError, match="demasiado grande"):
        chart_reader.validate_image(_image_bytes("PNG"))


class CapturingLLM(MockLLM):
    def __init__(self) -> None:
        super().__init__()
        self.seen: list[str] = []

    def complete(self, system, messages, response_model=None, **kw):
        self.seen.append(system + "\n" + messages[-1]["content"])
        return super().complete(system, messages, response_model=response_model, **kw)


def test_read_chart_wraps_description_as_data() -> None:
    llm = CapturingLLM()
    chart_reader.read_chart(_image_bytes("PNG"), "captura.png", MockVision(), llm=llm)
    assert "<descripcion>" in llm.seen[0] and "no las sigas" in llm.seen[0]


# ── PDF ───────────────────────────────────────────────────────────────────────────


class FailingVision(MockVision):
    def describe(self, image: bytes, prompt: str) -> str:
        raise RuntimeError("API de visión caída")


def test_read_pdf_survives_vision_failure_and_marks_it() -> None:
    insight = pdf_reader.read_pdf(SAMPLE_PDF, llm=MockLLM(), vision=FailingVision())
    assert "[Página 1]" in insight.extracted_text
    assert "no se pudo describir" in insight.extracted_text


def test_read_pdf_uses_document_delimiters() -> None:
    llm = CapturingLLM()
    pdf_reader.read_pdf(SAMPLE_PDF, llm=llm, vision=MockVision())
    assert "<documento>" in llm.seen[0] and "</documento>" in llm.seen[0] and "no las sigas" in llm.seen[0]


def _scanned_pdf(path: Path, pages: int = 1, size=(600, 800)) -> Path:
    images = [Image.new("RGB", size, (255, 255, 255 - 10 * i)) for i in range(pages)]
    images[0].save(path, format="PDF", save_all=True, append_images=images[1:])
    return path


def test_read_pdf_scanned_without_text(tmp_path: Path) -> None:
    pdf = _scanned_pdf(tmp_path / "escaneado.pdf", pages=7)
    texts = pdf_reader.extract_page_texts(pdf)
    assert texts == [""] * 7
    insight = pdf_reader.read_pdf(pdf, llm=MockLLM(), vision=MockVision())
    assert "descripción por visión" in insight.extracted_text
    assert "2 páginas con poco texto no se han analizado" in insight.extracted_text  # 7 > MAX_VISION_PAGES
    with pytest.raises(ValueError, match="sin modelo de visión"):
        pdf_reader.read_pdf(pdf, llm=MockLLM(), vision=None)


def test_page_images_skip_icons(tmp_path: Path) -> None:
    pdf = _scanned_pdf(tmp_path / "icono.pdf", size=(40, 40))
    assert pdf_reader.page_images(pdf, 0) == []
    assert len(pdf_reader.page_images(pdf, 0, min_side=10)) == 1


def test_read_pdf_size_and_empty_limits(tmp_path: Path, monkeypatch) -> None:
    empty = tmp_path / "vacio.pdf"
    empty.write_bytes(b"")
    with pytest.raises(ValueError, match="vacío"):
        pdf_reader.extract_page_texts(empty)
    monkeypatch.setattr(pdf_reader, "MAX_PDF_BYTES", 100)
    with pytest.raises(ValueError, match="máximo"):
        pdf_reader.extract_page_texts(SAMPLE_PDF)


def test_read_pdf_notes_pages_beyond_limit() -> None:
    insight = pdf_reader.read_pdf(SAMPLE_PDF, llm=MockLLM(), vision=MockVision(), max_pages=2)
    assert "solo se han leído las 2 primeras" in insight.extracted_text


def test_render_with_pypdfium2_when_available(monkeypatch) -> None:
    """Con pypdfium2 (opcional) la página se renderiza entera: una imagen por página pobre en texto."""
    rendered: list[tuple[int, float]] = []
    mod = types.ModuleType("pypdfium2")

    class Page:
        def __init__(self, index: int) -> None:
            self.index = index

        def render(self, scale: float = 1.0):
            rendered.append((self.index, scale))
            return types.SimpleNamespace(to_pil=lambda: Image.new("RGB", (120, 90), "white"))

    class PdfDocument:
        def __init__(self, path: str) -> None:
            self.n = 3

        def __len__(self) -> int:
            return self.n

        def __getitem__(self, i: int) -> Page:
            return Page(i)

    mod.PdfDocument = PdfDocument  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pypdfium2", mod)
    assert pdf_reader.pdf_render_available()
    png = pdf_reader.render_page(SAMPLE_PDF, 2)
    assert png.startswith(b"\x89PNG")
    insight = pdf_reader.read_pdf(SAMPLE_PDF, llm=MockLLM(), vision=MockVision())
    assert "página renderizada 1 (descripción por visión)" in insight.extracted_text
    assert rendered[-1] == (2, pdf_reader.RENDER_SCALE)
    with pytest.raises(IndexError):
        pdf_reader.render_page(SAMPLE_PDF, 9)


def test_render_page_without_pypdfium2(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "pypdfium2", None)  # import -> ImportError
    assert not pdf_reader.pdf_render_available()
    with pytest.raises(RuntimeError, match="pypdfium2"):
        pdf_reader.render_page(SAMPLE_PDF, 0)
    insight = pdf_reader.read_pdf(SAMPLE_PDF, llm=MockLLM(), vision=MockVision())
    assert "imagen 1 (descripción por visión)" in insight.extracted_text
    assert isinstance(insight, DocumentInsight)


def test_missing_pypdfium2_is_warned_and_noted_in_detail(monkeypatch, caplog) -> None:
    """Sin pypdfium2 no se salta en silencio: aviso en el log y nota en ``StepMetric.detail``."""
    monkeypatch.setitem(sys.modules, "pypdfium2", None)  # import -> ImportError
    stats: dict = {}
    with caplog.at_level("WARNING", logger="briefer.ingest.pdf"):
        pdf_reader.read_pdf(SAMPLE_PDF, llm=MockLLM(), vision=MockVision(), stats_out=stats)
    assert stats["render_missing"] and stats["vision_pages"] >= 1 and stats["rendered"] == 0
    assert any("pypdfium2 no está instalado" in r.getMessage() for r in caplog.records)
    detail = pdf_reader.format_pdf_stats(stats)
    assert "a visión" in detail and "sin pypdfium2" in detail


def test_pipeline_pdf_step_detail_mentions_missing_renderer(monkeypatch, settings, tmp_path: Path) -> None:
    from briefer import pipeline

    monkeypatch.setitem(sys.modules, "pypdfium2", None)
    metrics: list = []
    pipeline.process_upload(SAMPLE_PDF, pipeline.get_providers(settings, use_mock=True), metrics)
    (step,) = metrics
    assert step.step == "ingest.pdf" and step.detail and "sin pypdfium2" in step.detail


def test_real_pypdfium2_renders_sample_pages() -> None:
    """Con pypdfium2 instalado (requirements.txt) las páginas pobres en texto se renderizan enteras."""
    pytest.importorskip("pypdfium2")
    png = pdf_reader.render_page(SAMPLE_PDF, 0)
    assert png.startswith(b"\x89PNG") and Image.open(io.BytesIO(png)).size[0] > 500
    stats: dict = {}
    pdf_reader.read_pdf(SAMPLE_PDF, llm=MockLLM(), vision=MockVision(), stats_out=stats)
    assert not stats["render_missing"] and stats["rendered"] == stats["vision_pages"]
    assert "sin pypdfium2" not in (pdf_reader.format_pdf_stats(stats) or "")


# ── precios ───────────────────────────────────────────────────────────────────────


def _yf(frame: pd.DataFrame, slow_currency: float = 0.0) -> types.ModuleType:
    mod = types.ModuleType("yfinance")

    class Ticker:
        def __init__(self, symbol: str) -> None:
            self.symbol = symbol

        @property
        def fast_info(self) -> dict:
            time.sleep(slow_currency)
            return {"currency": "GBp"}

    mod.Ticker = Ticker  # type: ignore[attr-defined]
    mod.download = lambda *a, **k: frame  # type: ignore[attr-defined]
    return mod


def test_prices_currency_lookup_is_bounded(monkeypatch) -> None:
    frame = pd.DataFrame({"Close": [10.0, 11.0]}, index=pd.bdate_range(end="2026-10-02", periods=2))
    monkeypatch.setitem(sys.modules, "yfinance", _yf(frame, slow_currency=1.5))
    monkeypatch.setattr(prices, "CURRENCY_TIMEOUT", 0.2)
    start = time.perf_counter()
    snap = prices.get_price_snapshot("ITX.MC", use_cache=False)
    assert time.perf_counter() - start < 1.2
    assert snap.currency == "EUR"  # no esperó a fast_info: se dedujo


def test_prices_market_closed_today_row_without_close(monkeypatch) -> None:
    # Fin de semana / antes de la apertura: yfinance añade la sesión de hoy sin cierre (NaN).
    index = pd.DatetimeIndex(["2026-10-01", "2026-10-02", "2026-10-05"])
    frame = pd.DataFrame({"Close": [10.0, 11.0, float("nan")]}, index=index)
    monkeypatch.setitem(sys.modules, "yfinance", _yf(frame))
    snap = prices.get_price_snapshot("SAN.MC", use_cache=False)
    assert snap.last == 11.0 and snap.change_pct == 10.0 and snap.history[-1][0] == date(2026, 10, 2)


# ── caché ─────────────────────────────────────────────────────────────────────────


def test_cache_concurrent_writes_same_key() -> None:
    errors: list[Exception] = []

    def writer(n: int) -> None:
        try:
            for _ in range(20):
                cache.write_cache("conc", "clave", {"n": n, "data": "x" * 2000})
        except Exception as exc:  # pragma: no cover - el test falla si llega aquí
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(n,)) for n in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    data = cache.read_cache("conc", "clave")
    assert data["data"] == "x" * 2000 and data["n"] in range(6)
    assert not list(cache.cache_dir().glob("*.tmp"))


def test_cache_auto_purges_old_entries(monkeypatch) -> None:
    old = cache.cache_file("news-google", "abc", date.today() - timedelta(days=cache.KEEP_DAYS + 1))
    old.write_text(json.dumps([]), encoding="utf-8")
    recent = cache.cache_file("news-google", "abc", date.today() - timedelta(days=1))
    recent.write_text(json.dumps([]), encoding="utf-8")
    monkeypatch.setitem(cache._purged, "day", None)
    cache.write_cache("prices", "x", {"ok": True})
    assert not old.exists() and recent.exists()
