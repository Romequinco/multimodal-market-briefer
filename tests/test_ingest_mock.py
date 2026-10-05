"""Tests del carril A (``ingest/``) en modo mock: sin red ni claves."""

from __future__ import annotations

import codecs
import io
import json
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from briefer.config import ROOT_DIR
from briefer.ingest import chart_reader, news, pdf_reader, portfolio, prices, tickers, voice
from briefer.providers.mock import MockImageClassifier, MockLLM, MockSTT, MockVision, write_solid_png
from briefer.schemas import DocumentInsight, NewsItem, Portfolio, Position, PriceSnapshot

SAMPLES_DIR = ROOT_DIR / "data" / "samples"
SAMPLE_PDF = SAMPLES_DIR / "resultados_ejemplo.pdf"
SAMPLE_PNG = SAMPLES_DIR / "grafico_ejemplo.png"


def _news(title: str, summary: str = "", tickers_: list[str] | None = None, **kw) -> NewsItem:
    data = {
        "id": kw.pop("id", title[:10]),
        "title": title,
        "summary": summary,
        "source": "Test",
        "url": kw.pop("url", f"https://example.com/{abs(hash(title))}"),
        "published_at": kw.pop("published_at", datetime(2026, 10, 5, 8, 0)),
        "tickers": tickers_ or [],
    }
    return NewsItem(**data, **kw)


# ── news ──────────────────────────────────────────────────────────────────────────


def test_load_sample_news_default_path_sorted() -> None:
    items = news.load_sample_news()
    assert 4 <= len(items) <= 6
    assert all(isinstance(i, NewsItem) and i.source and i.url for i in items)
    dates = [i.published_at for i in items]
    assert dates == sorted(dates, reverse=True)


def test_load_sample_news_custom_path_and_errors(tmp_path: Path) -> None:
    good = tmp_path / "n.json"
    good.write_text(json.dumps([json.loads(_news("[EJEMPLO] x").model_dump_json())]), encoding="utf-8")
    assert len(news.load_sample_news(good)) == 1
    bad = tmp_path / "bad.json"
    bad.write_text("{no es json", encoding="utf-8")
    with pytest.raises(ValueError):
        news.load_sample_news(bad)
    with pytest.raises(FileNotFoundError):
        news.load_sample_news(tmp_path / "no_existe.json")


def test_dedupe_news_by_url_and_title() -> None:
    a = _news("Inditex sube", "corto", ["ITX.MC"], url="https://x.com/a?utm=1")
    b = _news("Inditex sube", "resumen más largo", ["SAN.MC"], url="https://x.com/a")
    c = _news("¡Inditex  SUBE!", "", ["BBVA.MC"], url="https://otra.com/b")
    d = _news("Otra cosa", "", [], url="https://x.com/d")
    out = news.dedupe_news([a, b, c, d])
    assert len(out) == 2
    assert out[0].tickers == ["ITX.MC", "SAN.MC", "BBVA.MC"]
    assert out[0].summary == "resumen más largo"
    assert a.tickers == ["ITX.MC"]  # no muta la entrada


# fetch_news / get_price_snapshots (camino real) se prueban sin red en tests/test_ingest_real.py
# y contra las fuentes reales en tests/test_ingest_live.py (RUN_LIVE=1).


# ── tickers ───────────────────────────────────────────────────────────────────────


def test_ticker_universe_shape() -> None:
    assert 15 <= len(tickers.TICKER_UNIVERSE) <= 25
    for info in tickers.TICKER_UNIVERSE.values():
        assert isinstance(info["name"], str) and isinstance(info["aliases"], list)
    # La cartera y las noticias de ejemplo están cubiertas.
    pf = portfolio.load_portfolio_csv(SAMPLES_DIR / "portfolio_ejemplo.csv")
    sample_tickers = {t for n in news.load_sample_news() for t in n.tickers}
    assert set(portfolio.portfolio_tickers(pf)) | sample_tickers <= set(tickers.TICKER_UNIVERSE)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("san.mc", "SAN.MC"),
        ("  SAN.MC ", "SAN.MC"),
        ("san", "SAN.MC"),
        ("santander", "SAN.MC"),
        ("Banco Santander", "SAN.MC"),
        ("telefonica", "TEF.MC"),
        ("Telefónica", "TEF.MC"),
        ("$aapl", "AAPL"),
        ("nvidia", "NVDA"),
        ("ibex 35", "^IBEX"),
        ("s&p 500", "^GSPC"),
        ("xyz.de", "XYZ.DE"),
    ],
)
def test_normalize_ticker(raw: str, expected: str) -> None:
    assert tickers.normalize_ticker(raw) == expected


def test_normalize_ticker_empty() -> None:
    with pytest.raises(ValueError):
        tickers.normalize_ticker("   ")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("El Banco Santander gana un 5 %", ["SAN.MC"]),
        ("SAN.MC y BBVA.MC lideran el IBEX 35", ["SAN.MC", "BBVA.MC", "^IBEX"]),
        ("Compras en SAN y en $NVDA", ["SAN.MC", "NVDA"]),
        ("TELEFONICA y repsol", ["TEF.MC", "REP.MC"]),
        ("Zara abre tienda; el iPhone se vende bien", ["ITX.MC", "AAPL"]),
        ("El S&P 500 cierra plano", ["^GSPC"]),
    ],
)
def test_extract_tickers_positive(text: str, expected: list[str]) -> None:
    assert tickers.extract_tickers(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "Fiestas de San Sebastián y San Fermín",  # "San" no es SAN.MC
        "SANTANDERINO sin más",  # SAN dentro de otra palabra
        "Un representante (rep) de ventas",  # rep en minúsculas
        "La meta del Gobierno es reducir el déficit",  # "meta" palabra común
        "Applesauce y amazonas",  # alias dentro de otra palabra
        "AAPLX no existe",
        "",
    ],
)
def test_extract_tickers_no_false_positives(text: str) -> None:
    assert tickers.extract_tickers(text) == []


def test_extract_tickers_custom_universe() -> None:
    text = "Santander y Apple; también XYZ.DE"
    assert tickers.extract_tickers(text, universe=["AAPL", "XYZ.DE"]) == ["AAPL", "XYZ.DE"]


def test_filter_by_tickers_keeps_relevant_and_enriches() -> None:
    items = [
        _news("Apple presenta resultados", tickers_=[]),
        _news("Repsol invierte", tickers_=["REP.MC"]),
        _news("El IBEX 35 abre plano"),
        _news("Noticia sin relación"),
    ]
    out = tickers.filter_by_tickers(items, ["aapl"], min_items=1)
    assert [n.title for n in out] == ["Apple presenta resultados"]
    assert out[0].tickers == ["AAPL"]
    assert items[0].tickers == []  # entrada sin mutar


def test_filter_by_tickers_completes_with_market_news() -> None:
    items = [
        _news("Apple presenta resultados"),
        _news("Repsol invierte"),
        _news("El IBEX 35 abre plano"),
        _news("Wall Street: el S&P 500 sube"),
    ]
    out = tickers.filter_by_tickers(items, ["AAPL"])  # min_items=3 por defecto
    assert [n.title for n in out] == [
        "Apple presenta resultados",
        "El IBEX 35 abre plano",
        "Wall Street: el S&P 500 sube",
    ]


def test_filter_by_tickers_empty_returns_all() -> None:
    items = news.load_sample_news()
    assert len(tickers.filter_by_tickers(items, [])) == len(items)


def test_filter_sample_news_with_portfolio_tickers() -> None:
    out = tickers.filter_by_tickers(news.load_sample_news(), ["SAN.MC"])
    assert out[0].id == "ejemplo-001" or any(n.id == "ejemplo-001" for n in out)
    assert len(out) >= 2  # la de banca + noticias generales de mercado


# ── prices ────────────────────────────────────────────────────────────────────────


def test_synthetic_snapshots_shape_and_currency() -> None:
    end = date(2026, 10, 5)  # lunes
    snaps = prices.synthetic_snapshots(["san.mc", "AAPL", "^IBEX", "SAN.MC"], end=end)
    assert [s.ticker for s in snaps] == ["SAN.MC", "AAPL", "^IBEX"]
    assert [s.currency for s in snaps] == ["EUR", "USD", "EUR"]
    for s in snaps:
        assert isinstance(s, PriceSnapshot)
        assert 20 <= len(s.history) <= 23
        days = [d for d, _ in s.history]
        assert days == sorted(days) and all(d.weekday() < 5 for d in days)
        assert days[-1] == end
        assert s.last == s.history[-1][1] > 0
        prev = s.history[-2][1]
        assert s.change_pct == pytest.approx((s.last / prev - 1) * 100, abs=0.01)


def test_synthetic_snapshots_deterministic_per_ticker() -> None:
    end = date(2026, 10, 2)
    a = prices.synthetic_snapshots(["SAN.MC", "AAPL"], end=end)
    b = prices.synthetic_snapshots(["AAPL"], end=end)
    assert a[1] == b[0]  # no depende del resto de la lista
    assert a[0].history != a[1].history
    c = prices.synthetic_snapshots(["AAPL"], end=end, seed=1)
    assert c[0].history != b[0].history


def test_synthetic_snapshots_weekend_end_and_defaults() -> None:
    snaps = prices.synthetic_snapshots(["NVDA"], end=date(2026, 10, 4))  # domingo
    assert snaps[0].history[-1][0] == date(2026, 10, 2)
    today = prices.synthetic_snapshots(["NVDA"])
    assert today[0].history[-1][0] <= date.today()
    assert date.today() - today[0].history[-1][0] <= timedelta(days=2)
    assert prices.synthetic_snapshots([]) == []


# ── portfolio ─────────────────────────────────────────────────────────────────────


def test_load_sample_portfolio() -> None:
    pf = portfolio.load_portfolio_csv(SAMPLES_DIR / "portfolio_ejemplo.csv", name="Ejemplo")
    assert isinstance(pf, Portfolio) and pf.name == "Ejemplo"
    assert len(pf.positions) == 7
    assert sum(p.weight or 0 for p in pf.positions) == pytest.approx(1.0)
    assert portfolio.portfolio_tickers(pf)[0] == "SAN.MC"


def test_load_portfolio_from_str_path_and_file_objects() -> None:
    path = SAMPLES_DIR / "portfolio_ejemplo.csv"
    by_str = portfolio.load_portfolio_csv(str(path))
    by_bytes = portfolio.load_portfolio_csv(io.BytesIO(path.read_bytes()))
    by_text = portfolio.load_portfolio_csv(path.read_text(encoding="utf-8"))
    assert by_str.positions == by_bytes.positions == by_text.positions


def test_load_portfolio_spanish_format_percentages_and_duplicates() -> None:
    csv_text = "Símbolo;Peso;Cantidad\nsantander;40,5 %;100\nApple;29,5;\n\nSAN.MC;30;50\n"
    pf = portfolio.load_portfolio_csv(io.BytesIO(codecs.BOM_UTF8 + csv_text.encode("utf-8")))  # con BOM de Excel
    by_ticker = {p.ticker: p for p in pf.positions}
    assert set(by_ticker) == {"SAN.MC", "AAPL"}
    assert by_ticker["SAN.MC"].weight == pytest.approx(0.705)
    assert by_ticker["SAN.MC"].quantity == 150
    assert by_ticker["AAPL"].weight == pytest.approx(0.295)
    assert by_ticker["AAPL"].quantity is None


def test_load_portfolio_quantities_only() -> None:
    pf = portfolio.load_portfolio_csv("ticker,quantity\nMSFT,4\nNVDA,9\n")
    assert [p.quantity for p in pf.positions] == [4, 9]
    assert all(p.weight is None for p in pf.positions)
    assert portfolio.portfolio_tickers(pf) == ["MSFT", "NVDA"]


@pytest.mark.parametrize(
    ("csv_text", "match"),
    [
        ("", "vacío"),
        ("nombre,weight\nSantander,1\n", "ticker"),
        ("ticker,name\nSAN.MC,Santander\n", "weight"),
        ("ticker,weight\nSAN.MC,0.5\nAAPL,0.2\n", "suman"),
        ("ticker,weight\nSAN.MC,abc\n", "no numérico"),
        ("ticker,weight\nSAN.MC,-1\nAAPL,2\n", "negativo"),
        ("ticker,weight\n,\n", "ninguna posición"),
    ],
)
def test_load_portfolio_errors(csv_text: str, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        portfolio.load_portfolio_csv(io.BytesIO(csv_text.encode("utf-8")))


def test_portfolio_tickers_order() -> None:
    pf = Portfolio(
        name="t",
        positions=[
            Position(ticker="AAPL", quantity=3),
            Position(ticker="SAN.MC", weight=0.2),
            Position(ticker="NVDA", weight=0.8),
            Position(ticker="san.mc", weight=0.1),
        ],
    )
    assert portfolio.portfolio_tickers(pf) == ["NVDA", "SAN.MC", "AAPL"]


# ── voice ─────────────────────────────────────────────────────────────────────────


def test_voice_save_and_transcribe(tmp_path: Path) -> None:
    path = voice.save_audio_upload(b"RIFF....", tmp_path / "audio", suffix="wav")
    assert path.exists() and path.suffix == ".wav"
    text = voice.transcribe_question(path, MockSTT())
    assert "Santander" in text
    insight = voice.voice_to_insight(path, MockSTT())
    assert insight.source_type == "voice" and insight.source_name == path.name
    assert insight.extracted_text == text


def test_voice_errors(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        voice.save_audio_upload(b"", tmp_path)

    class SilentSTT(MockSTT):
        def transcribe(self, audio_path: Path, language: str = "es") -> str:
            return "   "

    path = voice.save_audio_upload(b"x", tmp_path)
    with pytest.raises(ValueError, match="No se ha entendido"):
        voice.transcribe_question(path, SilentSTT())
    with pytest.raises(FileNotFoundError):
        voice.transcribe_question(tmp_path / "no.wav", MockSTT())


# ── chart_reader ──────────────────────────────────────────────────────────────────


def test_sample_chart_png_exists_and_small() -> None:
    assert SAMPLE_PNG.exists() and SAMPLE_PNG.stat().st_size < 1_000_000
    assert chart_reader.validate_image(SAMPLE_PNG.read_bytes()) == "PNG"


def test_read_chart_full_chain_with_mocks() -> None:
    llm = MockLLM()
    insight = chart_reader.read_chart(
        SAMPLE_PNG.read_bytes(), "grafico_ejemplo.png", MockVision(), llm=llm, classifier=MockImageClassifier()
    )
    assert isinstance(insight, DocumentInsight)
    assert insight.source_type == "chart" and insight.source_name == "grafico_ejemplo.png"
    assert "[MOCK]" in insight.extracted_text
    assert insight.summary
    assert llm.last_usage["input_tokens"] > 0


def test_read_chart_without_llm_uses_first_sentence(tmp_path: Path) -> None:
    png = write_solid_png(tmp_path / "x.png")
    insight = chart_reader.read_chart(png.read_bytes(), "x.png", MockVision())
    assert insight.key_figures == {}
    assert insight.summary.startswith("[MOCK]") and len(insight.summary) <= 300


def test_read_chart_rejects_non_financial_image() -> None:
    class NotChart(MockImageClassifier):
        def classify(self, image: bytes, labels: list[str]) -> dict[str, float]:
            return {label: (0.9 if label == chart_reader.NOT_CHART_LABEL else 0.1 / 3) for label in labels}

    class NoVision(MockVision):
        def describe(self, image: bytes, prompt: str) -> str:  # pragma: no cover - no debe llamarse
            raise AssertionError("no debe llamarse a visión")

    insight = chart_reader.read_chart(SAMPLE_PNG.read_bytes(), "foto.png", NoVision(), classifier=NotChart())
    assert "no parece un gráfico" in insight.summary


@pytest.mark.parametrize("data", [b"", b"esto no es una imagen"])
def test_read_chart_invalid_image(data: bytes) -> None:
    with pytest.raises(ValueError):
        chart_reader.read_chart(data, "x.heic", MockVision())


def test_classify_image() -> None:
    label, prob = chart_reader.classify_image(b"img", MockImageClassifier())
    assert label == chart_reader.CHART_LABELS[0] and prob == pytest.approx(0.7)


# ── pdf_reader ────────────────────────────────────────────────────────────────────


def test_sample_pdf_text_extraction() -> None:
    texts = pdf_reader.extract_page_texts(SAMPLE_PDF)
    assert len(texts) == 3
    assert "EJEMPLO FICTICIO" in texts[0]
    assert "1.245 millones de euros" in texts[0] and "más" in texts[0]
    assert "EBITDA" in texts[1]
    assert pdf_reader.pages_needing_vision(texts) == [2]
    images = pdf_reader.page_images(SAMPLE_PDF, 2)
    assert len(images) == 1 and chart_reader.validate_image(images[0]) == "PNG"
    with pytest.raises(IndexError):
        pdf_reader.page_images(SAMPLE_PDF, 10)


def test_pages_needing_vision_heuristic() -> None:
    texts = ["x" * 500, "", "1 2 3 4 5 6 7 8 9 " * 30, "y" * 50] + ["" for _ in range(10)]
    selected = pdf_reader.pages_needing_vision(texts)
    assert selected[:3] == [1, 2, 3]
    assert len(selected) == pdf_reader.MAX_VISION_PAGES


def test_read_pdf_full_chain_with_mocks() -> None:
    insight = pdf_reader.read_pdf(SAMPLE_PDF, llm=MockLLM(), vision=MockVision())
    assert insight.source_type == "pdf" and insight.source_name == "resultados_ejemplo.pdf"
    assert "[Página 1]" in insight.extracted_text
    assert "descripción por visión" in insight.extracted_text
    assert insight.summary


def test_read_pdf_errors(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        pdf_reader.read_pdf(tmp_path / "no.pdf", llm=MockLLM())
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"no es un pdf")
    with pytest.raises(ValueError):
        pdf_reader.extract_page_texts(bad)


# ── integración con el pipeline (process_upload en mock) ──────────────────────────


def test_process_upload_routes_samples(settings, tmp_path: Path) -> None:
    from briefer.pipeline import get_providers, process_upload

    providers = get_providers(settings, use_mock=True)
    metrics: list = []
    audio = voice.save_audio_upload(b"RIFF", tmp_path)
    kinds = [process_upload(p, providers, metrics).source_type for p in (SAMPLE_PDF, SAMPLE_PNG, audio)]
    assert kinds == ["pdf", "chart", "voice"]
    assert [m.step for m in metrics] == ["ingest.pdf", "ingest.chart", "ingest.voice"]
