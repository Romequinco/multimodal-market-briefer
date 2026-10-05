"""Salidas del carril C con proveedores mock: podcast, transcripción/SRT, gráficos y textos de entrega.

Sin red: ``MockTTS`` escribe WAV de silencio. La vía ffmpeg (MP3 / mezclas) solo se prueba si
``imageio-ffmpeg`` está instalado.
"""

from __future__ import annotations

import re
import struct
import wave
from datetime import date, timedelta
from pathlib import Path

import pytest

from briefer.delivery.email_sender import build_email_html
from briefer.delivery.telegram_sender import build_caption
from briefer.media import charts, podcast, transcript
from briefer.providers.mock import MockTTS, sample_script, write_silence_wav
from briefer.schemas import (
    DISCLAIMER_ES,
    AudioSegment,
    Briefing,
    PodcastScript,
    Portfolio,
    Position,
    PriceSnapshot,
    ScriptLine,
)

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _has_ffmpeg() -> bool:
    try:
        podcast.ffmpeg_exe()
        return True
    except Exception:
        return False


def _png_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()[:24]
    assert data[:8] == PNG_MAGIC
    return struct.unpack(">II", data[16:24])


def _snapshot(ticker: str, change: float, days: int = 20, start: float = 100.0) -> PriceSnapshot:
    history = [(date(2026, 9, 1) + timedelta(days=i), round(start * (1 + 0.005 * i), 2)) for i in range(days)]
    return PriceSnapshot(ticker=ticker, last=history[-1][1] if history else start, change_pct=change,
                         currency="EUR", history=history)


# ── Podcast ────────────────────────────────────────────────────────────────────────


def test_synthesize_podcast_with_mock_tts(tmp_path: Path) -> None:
    script = sample_script()
    audio = podcast.synthesize_podcast(script, MockTTS(), tmp_path, "voz-a", "voz-b", pause_s=0.35)

    assert audio.path == tmp_path / "podcast.wav" and audio.path.exists()
    assert len(audio.segments) == len(script.lines)
    assert [s.speaker for s in audio.segments] == [line.speaker for line in script.lines]
    # Tiempos crecientes, sin solapes y con la pausa entre intervenciones
    for prev, nxt in zip(audio.segments, audio.segments[1:], strict=False):
        assert prev.end_s > prev.start_s
        assert nxt.start_s == pytest.approx(prev.end_s + 0.35, abs=1e-3)
    assert audio.segments[0].start_s == 0.0
    assert audio.duration_s == pytest.approx(audio.segments[-1].end_s, abs=0.01)
    assert audio.duration_s == pytest.approx(podcast.audio_duration_s(audio.path), abs=1e-6)
    assert not (tmp_path / "parts").exists()  # partes intermedias borradas


def test_synthesize_podcast_sequential_equals_parallel(tmp_path: Path) -> None:
    script = sample_script()
    a = podcast.synthesize_podcast(script, MockTTS(), tmp_path / "par", "a", "b", max_workers=4)
    b = podcast.synthesize_podcast(script, MockTTS(), tmp_path / "seq", "a", "b", max_workers=1)
    assert a.segments == b.segments


def test_synthesize_podcast_uses_voice_per_speaker(tmp_path: Path) -> None:
    calls: list[tuple[str, str]] = []

    class SpyTTS(MockTTS):
        def synthesize(self, text: str, voice: str, out_path: Path) -> Path:
            calls.append((text, voice))
            return super().synthesize(text, voice, out_path)

    script = PodcastScript(
        title="t",
        lines=[ScriptLine(speaker="A", text="Hola"), ScriptLine(speaker="B", text="Buenas"),
               ScriptLine(speaker="A", text="   ")],  # las líneas vacías se omiten
    )
    audio = podcast.synthesize_podcast(script, SpyTTS(), tmp_path, "VOZ_A", "VOZ_B")
    assert sorted(calls) == [("Buenas", "VOZ_B"), ("Hola", "VOZ_A")]
    assert len(audio.segments) == 2


def test_synthesize_podcast_retries_then_succeeds(tmp_path: Path) -> None:
    class FlakyTTS(MockTTS):
        failures = 1

        def synthesize(self, text: str, voice: str, out_path: Path) -> Path:
            if FlakyTTS.failures:
                FlakyTTS.failures -= 1
                raise ConnectionError("fallo de red simulado")
            return super().synthesize(text, voice, out_path)

    audio = podcast.synthesize_podcast(sample_script(), FlakyTTS(), tmp_path, "a", "b", max_workers=1)
    assert audio.path.exists()


def test_synthesize_podcast_empty_script_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        podcast.synthesize_podcast(PodcastScript(title="vacío"), MockTTS(), tmp_path, "a", "b")


def test_concat_wav_stdlib_adds_pauses(tmp_path: Path) -> None:
    parts = [write_silence_wav(tmp_path / f"{i}.wav", 0.5) for i in range(3)]
    out = podcast.concat_audio(parts, tmp_path / "out.wav", pause_s=0.25)
    assert podcast.audio_duration_s(out) == pytest.approx(3 * 0.5 + 2 * 0.25, abs=1e-3)
    with wave.open(str(out)) as wav:
        assert wav.getframerate() == 16_000 and wav.getnchannels() == 1


def test_concat_audio_empty_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        podcast.concat_audio([], tmp_path / "x.wav")


@pytest.mark.skipif(not _has_ffmpeg(), reason="imageio-ffmpeg no instalado")
def test_concat_mixed_formats_to_mp3_with_ffmpeg(tmp_path: Path) -> None:
    a = write_silence_wav(tmp_path / "a.wav", 1.0, sample_rate=16_000)
    b = write_silence_wav(tmp_path / "b.wav", 0.5, sample_rate=22_050)  # otra frecuencia
    mp3 = podcast.concat_audio([a, b], tmp_path / "out.mp3", pause_s=0.35)
    assert mp3.exists() and mp3.stat().st_size > 0
    assert podcast.audio_duration_s(mp3) == pytest.approx(1.85, abs=0.15)
    # MP3 como entrada (camino de edge-tts): concatenar dos MP3 y medir
    mp3_2 = podcast.concat_audio([mp3, mp3], tmp_path / "twice.mp3", pause_s=0.0)
    assert podcast.audio_duration_s(mp3_2) == pytest.approx(3.7, abs=0.25)


# ── Transcripción ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [(0, "00:00:00,000"), (3.5, "00:00:03,500"), (61.0004, "00:01:01,000"), (3725.25, "01:02:05,250"),
     (-1, "00:00:00,000"), (59.9996, "00:01:00,000")],
)
def test_format_srt_timestamp(seconds: float, expected: str) -> None:
    assert transcript.format_srt_timestamp(seconds) == expected


def test_segments_to_srt_names_and_splitting() -> None:
    long_text = " ".join(["palabra"] * 40)  # ~320 caracteres -> varios bloques
    segments = [
        AudioSegment(speaker="A", text="Hola", start_s=0.0, end_s=1.0),
        AudioSegment(speaker="B", text=long_text, start_s=1.35, end_s=11.35),
    ]
    srt = transcript.segments_to_srt(segments, {"A": "Álvaro", "B": "Elvira"})
    blocks = [b for b in srt.strip().split("\n\n") if b]
    assert len(blocks) > 2
    assert blocks[0].splitlines()[2] == "Álvaro: Hola"
    assert blocks[1].splitlines()[2].startswith("Elvira: ")
    for i, block in enumerate(blocks, start=1):
        lines = block.splitlines()
        assert lines[0] == str(i)
        assert re.fullmatch(r"\d{2}:\d{2}:\d{2},\d{3} --> \d{2}:\d{2}:\d{2},\d{3}", lines[1])
        text_rows = lines[2:]
        assert 1 <= len(text_rows) <= 2 and all(len(r) <= 42 for r in text_rows)
    # El último bloque del segmento largo termina exactamente en su end_s
    assert blocks[-1].splitlines()[1].endswith("00:00:11,350")


def test_build_transcript_matches_audio(tmp_path: Path) -> None:
    script = sample_script()
    audio = podcast.synthesize_podcast(script, MockTTS(), tmp_path, "a", "b")
    names = {"A": "Álvaro", "B": "Elvira"}
    tr = transcript.build_transcript(script, audio.segments, tmp_path, speaker_names=names)

    assert tr.srt_path == tmp_path / "podcast.srt" and tr.srt_path.exists()
    assert tr.text.startswith("Álvaro: ") and "Elvira: " in tr.text
    srt = tr.srt_path.read_text(encoding="utf-8")
    ends = re.findall(r"--> (\d{2}):(\d{2}):(\d{2}),(\d{3})", srt)
    h, m, s, ms = map(int, ends[-1])
    assert h * 3600 + m * 60 + s + ms / 1000 == pytest.approx(audio.duration_s, abs=0.01)


def test_build_transcript_without_segments(tmp_path: Path) -> None:
    tr = transcript.build_transcript(sample_script(), [], tmp_path, speaker_names={"A": "Ana", "B": "Bea"})
    assert tr.srt_path is None
    assert tr.text.startswith("Ana: ")
    assert not (tmp_path / "podcast.srt").exists()


# ── Gráficos ───────────────────────────────────────────────────────────────────────


def test_make_charts_generates_pngs(tmp_path: Path) -> None:
    prices = [_snapshot("SAN.MC", 1.2), _snapshot("^IBEX", -0.8), _snapshot("AAPL", 0.0)]
    portfolio = Portfolio(name="Test", positions=[Position(ticker="SAN.MC", weight=0.6),
                                                  Position(ticker="AAPL", weight=0.38),
                                                  Position(ticker="NVDA", weight=0.02)])
    assets = charts.make_charts(prices, tmp_path / "charts", portfolio=portfolio)

    kinds = [a.kind for a in assets]
    assert kinds == ["overview_bar", "price_line", "price_line", "price_line", "portfolio_pie"]
    assert [a.ticker for a in assets if a.kind == "price_line"] == ["SAN.MC", "^IBEX", "AAPL"]
    for asset in assets:
        assert asset.path.exists()
        assert _png_size(asset.path) == (1920, 1080)  # 16:9 apto para vídeo
    assert (tmp_path / "charts" / "IBEX_price.png").exists()  # nombre de fichero seguro


def test_make_charts_is_robust(tmp_path: Path) -> None:
    # Un ticker sin histórico no tumba el resto; un solo ticker no genera overview.
    assets = charts.make_charts([_snapshot("SAN.MC", 1.0), _snapshot("AAPL", 2.0, days=0)], tmp_path)
    assert [a.kind for a in assets] == ["overview_bar", "price_line"]
    single = charts.make_charts([_snapshot("SAN.MC", 1.0)], tmp_path / "one")
    assert [a.kind for a in single] == ["price_line"]
    with pytest.raises(ValueError):
        charts.make_price_chart(_snapshot("X", 0.0, days=0), tmp_path)


def test_portfolio_weights_from_quantities() -> None:
    portfolio = Portfolio(name="Q", positions=[Position(ticker="A", quantity=10), Position(ticker="B", quantity=5)])
    prices = [PriceSnapshot(ticker="A", last=10, change_pct=0, currency="EUR"),
              PriceSnapshot(ticker="B", last=20, change_pct=0, currency="EUR")]
    assert charts.portfolio_weights(portfolio, prices) == {"A": 0.5, "B": 0.5}
    assert charts.portfolio_weights(portfolio) == {}


def test_number_formatting_es() -> None:
    assert charts.fmt_number(12345.678) == "12.345,68"
    assert charts.fmt_pct(1.234) == "+1,23 %"
    assert charts.fmt_pct(-0.5) == "−0,50 %"


# ── Entrega (funciones puras) ─────────────────────────────────────────────────────


def test_build_email_html(sample_briefing: Briefing) -> None:
    html = build_email_html(sample_briefing)
    assert sample_briefing.analysis.headline in html
    assert "cid:chart0" in html
    assert "https://example.com/1" in html  # la fuente se enlaza a la noticia
    assert "sintéticas" in html
    assert DISCLAIMER_ES.split(".")[0] in html


def test_build_caption_respects_limit(sample_briefing: Briefing) -> None:
    caption = build_caption(sample_briefing)
    assert len(caption) <= 1024 and "<b>Titular</b>" in caption and "MiFID II" in caption
    short = build_caption(sample_briefing, max_len=len(DISCLAIMER_ES) + 120)
    assert len(short) <= len(DISCLAIMER_ES) + 120
    assert "MiFID II" in short  # el disclaimer nunca se recorta
