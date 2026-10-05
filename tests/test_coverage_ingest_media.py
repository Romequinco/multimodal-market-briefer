"""Cobertura de ramas de error de la ingesta y del audio, sin red: PDFs cifrados o rotos, imágenes
embebidas raras, precios con datos anómalos, CSV de cartera ilegibles y fallos de ffmpeg/TTS."""

from __future__ import annotations

import io
import struct
import subprocess
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
from PIL import Image

from briefer.agents import guardrails
from briefer.config import ROOT_DIR
from briefer.ingest import cache, chart_reader, pdf_reader, portfolio, prices, voice
from briefer.media import podcast
from briefer.providers.mock import MockLLM, MockTTS, MockVision, write_silence_wav
from briefer.schemas import PodcastScript, ScriptLine

SAMPLE_PDF = ROOT_DIR / "data" / "samples" / "resultados_ejemplo.pdf"


# ── PDF ───────────────────────────────────────────────────────────────────────────


def _pdf_with_text(path: Path, password: str | None = None, pages: int = 1) -> Path:
    from pypdf import PdfWriter

    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=200, height=200)
    if password is not None:
        writer.encrypt(user_password=password, owner_password="propietario")
    with path.open("wb") as fh:
        writer.write(fh)
    return path


def test_pdf_missing_and_password_protected(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        pdf_reader.extract_page_texts(tmp_path / "no.pdf")
    with pytest.raises(ValueError, match="contraseña"):
        pdf_reader.extract_page_texts(_pdf_with_text(tmp_path / "cifrado.pdf", password="clave"))


def test_pdf_encrypted_with_empty_password_is_read(tmp_path: Path) -> None:
    pdf = _pdf_with_text(tmp_path / "vacia.pdf", password="", pages=2)
    assert pdf_reader.extract_page_texts(pdf) == ["", ""]


def test_pdf_decrypt_exception_means_protected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from pypdf import PdfReader

    def boom(self, password):
        raise NotImplementedError("algoritmo no soportado")

    monkeypatch.setattr(PdfReader, "decrypt", boom)
    with pytest.raises(ValueError, match="contraseña"):
        pdf_reader.extract_page_texts(_pdf_with_text(tmp_path / "raro.pdf", password="x"))


def test_pdf_without_pages_or_broken_page_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValueError, match="no tiene páginas"):
        pdf_reader.extract_page_texts(_pdf_with_text(tmp_path / "cero.pdf", pages=0))

    from pypdf import PdfReader

    def broken(self):
        raise KeyError("/Kids")

    monkeypatch.setattr(PdfReader, "pages", property(broken))
    with pytest.raises(ValueError, match="estructura de páginas dañada"):
        pdf_reader.extract_page_texts(_pdf_with_text(tmp_path / "roto.pdf"))


def test_page_texts_survives_a_broken_page(caplog: pytest.LogCaptureFixture) -> None:
    class Page:
        def __init__(self, text: str | Exception) -> None:
            self.text = text

        def extract_text(self) -> str:
            if isinstance(self.text, Exception):
                raise self.text
            return self.text

    reader = SimpleNamespace(pages=[Page(" uno "), Page(RuntimeError("fuente rara")), Page(None)])  # type: ignore[arg-type]
    with caplog.at_level("WARNING", logger="briefer.ingest.pdf"):
        assert pdf_reader._page_texts(reader, "x.pdf", 10) == ["uno", "", ""]
    assert any("No se pudo extraer texto" in r.getMessage() for r in caplog.records)


class FakeImage:
    def __init__(self, name: str, pil: Image.Image | Exception | None, data: bytes = b"") -> None:
        self.name = name
        self._pil = pil
        self.data = data

    @property
    def image(self) -> Image.Image | None:
        if isinstance(self._pil, Exception):
            raise self._pil
        return self._pil


def test_normalize_image_variants() -> None:
    big = Image.new("RGB", (100, 100), "white")
    # Formato que aceptan los VLM: se manda tal cual.
    assert pdf_reader._normalize_image(FakeImage("x.PNG", big, b"PNGDATA"), 64) == b"PNGDATA"
    # Icono: se descarta.
    assert pdf_reader._normalize_image(FakeImage("x.png", Image.new("RGB", (10, 10)), b"d"), 64) is None
    # Filtro no soportado y formato no aceptado: no se puede recodificar.
    assert pdf_reader._normalize_image(FakeImage("x.jp2", RuntimeError("JBIG2"), b"d"), 64) is None
    # JPEG sin poder abrir con Pillow pero con bytes válidos: se manda tal cual.
    assert pdf_reader._normalize_image(FakeImage("x.jpg", RuntimeError("x"), b"JPG"), 64) == b"JPG"
    # TIFF en CMYK: se recodifica a PNG (RGB).
    png = pdf_reader._normalize_image(FakeImage("x.tiff", Image.new("CMYK", (80, 80)), b"TIFF"), 64)
    assert png and Image.open(io.BytesIO(png)).format == "PNG"


def test_normalize_image_recode_failure_returns_none() -> None:
    class BadPil:
        size = (100, 100)
        mode = "P"

        def convert(self, mode: str):
            raise OSError("paleta rota")

    assert pdf_reader._normalize_image(FakeImage("x.bmp", BadPil()), 64) is None  # type: ignore[arg-type]


def test_page_images_index_and_extraction_errors(caplog: pytest.LogCaptureFixture) -> None:
    class Page:
        @property
        def images(self):
            raise ValueError("filtro no soportado")

    reader = SimpleNamespace(pages=[Page()])
    with pytest.raises(IndexError, match="no existe la página 3"):
        pdf_reader._page_images(reader, 2)
    with caplog.at_level("WARNING", logger="briefer.ingest.pdf"):
        assert pdf_reader._page_images(reader, 0) == []


def test_vision_images_falls_back_when_render_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(path, index, scale=1.0):
        raise RuntimeError("pdfium no abre el fichero")

    monkeypatch.setattr(pdf_reader, "render_page", boom)
    reader = pdf_reader._open(SAMPLE_PDF)
    images, label = pdf_reader._vision_images(SAMPLE_PDF, reader, 0, render=True)
    assert label == "imagen" and len(images) <= pdf_reader.MAX_IMAGES_PER_PAGE


def test_read_pdf_truncates_long_content_and_checks_llm_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pdf_reader, "MAX_LLM_CHARS", 120)
    insight = pdf_reader.read_pdf(SAMPLE_PDF, llm=MockLLM(), vision=None)
    assert insight.extracted_text.endswith("[… recortado]") and len(insight.extracted_text) < 200

    class TextLLM(MockLLM):
        def complete(self, system, messages, response_model=None):
            return "texto libre"

    with pytest.raises(TypeError, match="DocumentInsight"):
        pdf_reader.read_pdf(SAMPLE_PDF, llm=TextLLM(), vision=None)


def test_format_pdf_stats_variants() -> None:
    assert pdf_reader.format_pdf_stats({}) is None
    assert pdf_reader.format_pdf_stats({"pages_read": 2, "total_pages": 3}) == "2 de 3 páginas leídas"
    text = pdf_reader.format_pdf_stats({"pages_read": 1, "total_pages": 1, "vision_pages": 1})
    assert text == "1 de 1 páginas leídas · 1 a visión"


# ── imagen de gráfico ─────────────────────────────────────────────────────────────


def test_chart_validate_rejects_unsupported_format_and_empty_classifier() -> None:
    buf = io.BytesIO()
    Image.new("RGB", (8, 8)).save(buf, format="BMP")
    with pytest.raises(ValueError, match="no soportado \\(BMP\\)"):
        chart_reader.validate_image(buf.getvalue())
    with pytest.raises(ValueError, match="vacía"):
        chart_reader.validate_image(b"")

    class Empty:
        def classify(self, image, labels):
            return {}

    assert chart_reader.classify_image(b"x", Empty()) == (chart_reader.NOT_CHART_LABEL, 0.0)  # type: ignore[arg-type]


def test_read_chart_checks_llm_contract() -> None:
    buf = io.BytesIO()
    Image.new("RGB", (32, 32), "white").save(buf, format="PNG")

    class TextLLM(MockLLM):
        def complete(self, system, messages, response_model=None):
            return "texto libre"

    with pytest.raises(TypeError, match="DocumentInsight"):
        chart_reader.read_chart(buf.getvalue(), "g.png", MockVision(), llm=TextLLM())


# ── precios ───────────────────────────────────────────────────────────────────────


def _closes(values: list[float], end: str = "2026-10-05") -> pd.Series:
    return pd.Series(values, index=pd.bdate_range(end=end, periods=len(values)))


def test_close_series_edge_cases() -> None:
    assert prices._close_series(None, "X") is None
    assert prices._close_series(pd.DataFrame(), "X") is None
    multi = pd.DataFrame({("SAN.MC", "Close"): [1.0, 2.0]})
    assert prices._close_series(multi, "AAPL") is None  # el ticker no está en ningún nivel
    assert prices._close_series(pd.DataFrame({"Open": [1.0]}), "X") is None  # sin cierre
    dup = pd.DataFrame([[1.0, 9.0], [2.0, 9.0]], columns=["Close", "Close"])
    assert list(prices._close_series(dup, "X")) == [1.0, 2.0]  # columnas duplicadas: la primera
    zeros = pd.DataFrame({"Close": [0.0, float("nan"), "x"]})
    assert prices._close_series(zeros, "X") is None


def test_snapshot_from_closes_with_plain_dates_and_empty() -> None:
    series = pd.Series([10.0, 11.0], index=[date(2026, 10, 2), date(2026, 10, 5)])
    snap = prices.snapshot_from_closes("SAN.MC", series, "EUR")
    assert snap.change_pct == 10.0 and snap.history[0][0] == date(2026, 10, 2)
    dt_series = pd.Series([1.0], index=[datetime(2026, 10, 5, 17, 30)])
    assert prices.snapshot_from_closes("X", dt_series, "USD").history == [(date(2026, 10, 5), 1.0)]
    with pytest.raises(ValueError, match="Sin cierres"):
        prices.snapshot_from_closes("X", pd.Series([], dtype=float), "USD")


def test_price_snapshots_bad_cache_and_total_failure(monkeypatch: pytest.MonkeyPatch,
                                                     caplog: pytest.LogCaptureFixture) -> None:
    cache.write_cache("prices", cache.cache_key("SAN.MC", "1mo"), {"no": "es un snapshot"})

    def down(*_a, **_k):
        raise ConnectionError("sin red")

    monkeypatch.setattr(prices, "_download", down)
    monkeypatch.setattr(prices, "_history", down)
    with caplog.at_level("WARNING", logger="briefer.ingest.prices"):
        with pytest.raises(prices.PriceFetchError, match="SAN.MC"):
            prices.get_price_snapshots(["SAN.MC"])
    messages = " ".join(r.getMessage() for r in caplog.records)
    assert "Caché de precios incompatible" in messages and "Sin precios para SAN.MC" in messages


def test_price_snapshots_warn_on_stale_data(monkeypatch: pytest.MonkeyPatch,
                                            caplog: pytest.LogCaptureFixture) -> None:
    old_end = (date.today() - timedelta(days=30)).isoformat()
    frame = pd.DataFrame({"Close": [5.0, 5.5]}, index=pd.bdate_range(end=old_end, periods=2))
    monkeypatch.setattr(prices, "_download", lambda tickers, period: frame)
    monkeypatch.setattr(prices, "_currency", lambda t: "EUR")
    with caplog.at_level("WARNING", logger="briefer.ingest.prices"):
        (snap,) = prices.get_price_snapshots(["SAN.MC"], use_cache=False)
    assert snap.last == 5.5
    assert any("dato antiguo" in r.getMessage() for r in caplog.records)


def test_synthetic_snapshots_minimum_window_on_monday() -> None:
    monday = date(2026, 10, 5)
    assert monday.weekday() == 0
    (snap,) = prices.synthetic_snapshots(["SAN.MC"], days=1, end=monday)
    assert len(snap.history) >= 2 and snap.history[-1][0] == monday


# ── cartera ───────────────────────────────────────────────────────────────────────


def test_portfolio_unreadable_sources() -> None:
    with pytest.raises(TypeError, match="no soportada"):
        portfolio.load_portfolio_csv(12345)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="codificación"):
        portfolio.load_portfolio_csv(io.BytesIO(b"ticker;peso\n\x81\x8d\x8f;1\n"))
    with pytest.raises(ValueError, match="vacío"):
        portfolio.load_portfolio_csv(",,,\n,,\n")  # solo separadores: ninguna fila con datos


def test_portfolio_reads_text_stream_with_bom() -> None:
    pf = portfolio.load_portfolio_csv(io.StringIO("﻿ticker,weight\nSAN.MC,1\n"))
    assert [p.ticker for p in pf.positions] == ["SAN.MC"]


# ── voz y guardarraíles ───────────────────────────────────────────────────────────


def test_accepts_prompt_with_unintrospectable_transcribe() -> None:
    class Weird:
        transcribe = 42  # inspect.signature lanza TypeError

    assert voice._accepts_prompt(Weird()) is False  # type: ignore[arg-type]


def test_figure_values_mixed_separators_and_strip_noop() -> None:
    assert guardrails._figure_values("1.245,5") == [(1245.5, 1)]
    assert guardrails._figure_values("-1,245.50") == [(1245.5, 2)]
    assert guardrails.strip_figures("", ["1"]) == ("", False)
    assert guardrails.strip_figures("Sube un 2 %.", []) == ("Sube un 2 %.", False)


# ── ffmpeg y podcast ──────────────────────────────────────────────────────────────


def test_run_ffmpeg_timeout_and_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(podcast, "ffmpeg_exe", lambda: "ffmpeg")

    def slow(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, kw.get("timeout"))

    monkeypatch.setattr(podcast.subprocess, "run", slow)
    with pytest.raises(RuntimeError, match="no terminó"):
        podcast._run_ffmpeg(["-version"])

    stderr = "\n".join(f"línea {i}" for i in range(20))
    monkeypatch.setattr(podcast.subprocess, "run",
                        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, "", stderr))
    with pytest.raises(RuntimeError, match="código 1") as info:
        podcast._run_ffmpeg(["-i", "x"])
    assert "línea 19" in str(info.value) and "línea 5" not in str(info.value)  # solo el final


def _float_wav(path: Path) -> Path:
    """WAV con muestras en coma flotante (formato 3): ``wave`` no lo lee (no es PCM)."""
    fmt = struct.pack("<HHIIHH", 3, 1, 8000, 32000, 4, 32)
    data = bytes(16)
    body = b"WAVEfmt " + struct.pack("<I", len(fmt)) + fmt + b"data" + struct.pack("<I", len(data)) + data
    path.write_bytes(b"RIFF" + struct.pack("<I", len(body)) + body)
    return path


def test_audio_duration_fallbacks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(FileNotFoundError):
        podcast.audio_duration_s(tmp_path / "no.wav")
    fake_wav = _float_wav(tmp_path / "float.wav")
    assert podcast._wav_params(fake_wav) is None
    monkeypatch.setattr(podcast, "_run_ffmpeg",
                        lambda args: SimpleNamespace(stderr="Duration: 00:01:02.50, start: 0"))
    assert podcast.audio_duration_s(fake_wav) == 62.5
    monkeypatch.setattr(podcast, "_run_ffmpeg", lambda args: SimpleNamespace(stderr="sin datos"))
    with pytest.raises(RuntimeError, match="No se pudo medir"):
        podcast.audio_duration_s(fake_wav)


def test_concat_audio_validation_and_codecs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValueError, match="vacía"):
        podcast.concat_audio([], tmp_path / "o.wav")
    with pytest.raises(FileNotFoundError):
        podcast.concat_audio([tmp_path / "falta.wav"], tmp_path / "o.wav")

    part = write_silence_wav(tmp_path / "p.wav", 0.3)
    calls: list[list[str]] = []

    def fake_ffmpeg(args: list[str]):
        calls.append(args)
        Path(args[-1]).write_bytes(b"audio")
        return SimpleNamespace(stderr="")

    monkeypatch.setattr(podcast, "_run_ffmpeg", fake_ffmpeg)
    out = podcast.concat_audio([part, part], tmp_path / "norm.wav", loudness_lufs=-16)
    assert out.read_bytes() == b"audio" and "pcm_s16le" in calls[-1]
    podcast.concat_audio([part], tmp_path / "out.m4a")
    assert "-c:a" not in calls[-1]  # ffmpeg elige el códec por la extensión
    assert not list(tmp_path.glob("*.tmp*")) and not list(tmp_path.glob("*.filtergraph.txt"))


def test_synthesize_with_retry_detects_empty_output(tmp_path: Path) -> None:
    class EmptyTTS(MockTTS):
        def synthesize(self, text, voice, out_path):
            Path(out_path).write_bytes(b"")
            return out_path

    with pytest.raises(RuntimeError, match="no escribió audio"):
        podcast._synthesize_with_retry(EmptyTTS(), "hola", "v", tmp_path / "x.wav", retries=0)


def test_podcast_uses_theoretical_length_when_final_measure_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = podcast.audio_duration_s

    def measure(path: Path) -> float:
        if Path(path).stem == "podcast":
            raise RuntimeError("ffprobe roto")
        return real(path)

    monkeypatch.setattr(podcast, "audio_duration_s", measure)
    script = PodcastScript(title="T", lines=[ScriptLine(speaker="A", text="Hola"),
                                             ScriptLine(speaker="B", text="Buenas")], est_duration_s=2)
    asset = podcast.synthesize_podcast(script, MockTTS(), tmp_path, "va", "vb", pause_s=0.5, max_workers=1)
    assert asset.duration_s == pytest.approx(asset.segments[-1].end_s, abs=1e-3)
    assert asset.segments[1].start_s == pytest.approx(asset.segments[0].end_s + 0.5, abs=1e-3)


@pytest.mark.xfail(
    strict=True,
    raises=RuntimeError,
    reason="BUG podcast.py:120-123/138-141: un WAV con un bloque de tamaño imposible hace que "
    "wave.open lance RuntimeError (wave._Chunk.seek), que no se captura: _wav_params debería "
    "devolver None y audio_duration_s pasar a ffmpeg, como documentan.",
)
def test_corrupt_wav_chunk_size_falls_back_instead_of_crashing(tmp_path: Path) -> None:
    corrupt = tmp_path / "corrupto.wav"
    huge = bytes([255, 255, 255, 127])  # tamaño de bloque mucho mayor que el fichero
    corrupt.write_bytes(b"RIFF" + bytes([255, 255, 0, 0]) + b"WAVEjunk" + huge + bytes(8))
    assert podcast._wav_params(corrupt) is None
