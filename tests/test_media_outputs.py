"""Salidas (D2, carril C): gráficos con índices de referencia, sonoridad del podcast, limpieza de
temporales, fallo rápido del TTS y nuevas reglas de locución. Sin red (ffmpeg local de imageio-ffmpeg)."""

from __future__ import annotations

import json
import re
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

import pytest
from matplotlib.text import Text

from briefer.config import ROOT_DIR
from briefer.media import charts, podcast
from briefer.media.speech import normalize_for_speech
from briefer.providers.mock import MockTTS
from briefer.schemas import PodcastScript, PriceSnapshot, ScriptLine

DEMO_JSON = ROOT_DIR / "data" / "samples" / "demo_briefing" / "briefing.json"


def _snap(ticker: str, change: float, days: int = 22, start: float = 100.0) -> PriceSnapshot:
    history = [(date(2026, 9, 7) + timedelta(days=i), round(start * (1 + 0.004 * i), 2)) for i in range(days)]
    return PriceSnapshot(ticker=ticker, last=history[-1][1], change_pct=change, currency="EUR", history=history)


def _figure_texts(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """Intercepta ``charts._save`` para leer los textos de cada figura antes de guardarla."""
    captured: list[list[str]] = []
    real_save = charts._save

    def spy(fig, path):
        captured.append([t.get_text() for t in fig.findobj(Text) if t.get_text()])
        return real_save(fig, path)

    monkeypatch.setattr(charts, "_save", spy)
    return captured


# ── Gráficos ───────────────────────────────────────────────────────────────────────


def test_overview_labels_indices_as_reference(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    texts = _figure_texts(monkeypatch)
    prices = [_snap("SAN.MC", 2.44), _snap("^IBEX", 0.68), _snap("AAPL", -1.0), _snap("^GSPC", 0.73)]
    asset = charts.make_overview_chart(prices, tmp_path)
    assert asset.kind == "overview_bar" and asset.path.exists()
    words = texts[0]
    # Los índices salen con su nombre y la marca «índice», nunca como «^IBEX».
    assert "IBEX 35" in words and "S&P 500" in words
    assert words.count("índice") == 2
    assert "Índices de referencia" in words
    assert not any("^" in w for w in words)
    # Los valores, con nombre de empresa y ticker.
    assert "Banco Santander" in words and "SAN.MC" in words
    # Título con fecha de la última sesión y fuente en el pie.
    assert any(w.startswith("Variación del día · 28/09/2026") for w in words)
    assert any("Fuente: Yahoo Finance" in w for w in words)
    # Subtítulo: el recuento «suben/bajan» es solo de valores del usuario.
    assert any("2 valores: 1 suben · 1 bajan" in w for w in words)


def test_overview_order_values_first_then_indices(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    texts = _figure_texts(monkeypatch)
    prices = [_snap("^IBEX", 5.0), _snap("ITX.MC", 0.3), _snap("SAN.MC", 2.4)]
    charts.make_overview_chart(prices, tmp_path)
    names = [w for w in texts[0] if w in {"Banco Santander", "Inditex", "IBEX 35"}]
    # Mayor subida arriba entre los valores; el índice (aunque suba más) va al final, aparte.
    assert names == ["Banco Santander", "Inditex", "IBEX 35"]


def test_overview_only_indices_and_custom_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    texts = _figure_texts(monkeypatch)
    charts.make_overview_chart([_snap("^IBEX", -0.5), _snap("^GSPC", 0.2)], tmp_path,
                               source="precios sintéticos (demo)")
    words = texts[0]
    assert "Índices de referencia" not in words  # sin valores no hace falta separador
    assert any("Fuente: precios sintéticos (demo)" in w for w in words)


def test_price_chart_title_has_name_date_and_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    texts = _figure_texts(monkeypatch)
    charts.make_price_chart(_snap("SAN.MC", 1.5), tmp_path)
    charts.make_price_chart(_snap("^IBEX", -0.2, start=19000), tmp_path, source=None)
    san, ibex = texts
    assert any(w.startswith("Banco Santander · SAN.MC") for w in san)
    assert any("Cierre del 28/09/2026" in w for w in san)
    assert any("Fuente: Yahoo Finance" in w for w in san)
    assert any(w.startswith("IBEX 35 · índice") for w in ibex)
    assert any("puntos" in w for w in ibex)  # un índice cotiza en puntos, no en EUR
    assert not any("Fuente:" in w for w in ibex)


def test_make_charts_passes_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    texts = _figure_texts(monkeypatch)
    charts.make_charts([_snap("SAN.MC", 1.0), _snap("^IBEX", 0.5)], tmp_path, line_tickers=["SAN.MC"],
                       source="datos de ejemplo")
    assert len(texts) == 2
    assert all(any("Fuente: datos de ejemplo" in w for w in fig) for fig in texts)


def test_charts_are_thread_safe(tmp_path: Path) -> None:
    """Varias sesiones dibujando a la vez (API OO sin pyplot): ningún gráfico falla ni se mezcla."""
    prices = [_snap("SAN.MC", 1.0), _snap("AAPL", -2.0), _snap("^IBEX", 0.3)]

    def run(i: int) -> int:
        return len(charts.make_charts(prices, tmp_path / f"run{i}", line_tickers=["SAN.MC", "AAPL"]))

    with ThreadPoolExecutor(max_workers=6) as pool:
        counts = list(pool.map(run, range(12)))
    assert counts == [3] * 12
    assert not list(tmp_path.rglob("*.tmp"))  # escritura atómica: sin temporales


def test_helpers() -> None:
    assert charts.is_index("^IBEX") and not charts.is_index("SAN.MC")
    assert charts.display_name("^GSPC") == "S&P 500"
    assert charts.display_name("XYZ.MC") == "XYZ.MC"
    assert charts.fmt_pct(-0.001) == "0,00 %"  # sin «−0,00 %»
    assert charts.fmt_date(date(2026, 10, 5)) == "05/10/2026"
    days = [date(2026, 9, 1) + timedelta(days=i) for i in range(30)]
    ticks = charts._date_ticks(days)
    assert len(ticks) == 7 and ticks[0] == days[0] and ticks[-1] == days[-1]
    assert charts.last_session([_snap("A", 0.0, days=3), _snap("B", 0.0, days=5)]) == date(2026, 9, 11)


# ── Podcast: sonoridad, temporales y fallo rápido ──────────────────────────────────


def _tone(path: Path, volume: float, seconds: float = 3.0, freq: int = 440) -> Path:
    """Genera un tono MP3 con ffmpeg (sin red) a un volumen dado."""
    subprocess.run(
        [podcast.ffmpeg_exe(), "-hide_banner", "-nostdin", "-y", "-f", "lavfi", "-i",
         f"sine=frequency={freq}:duration={seconds}:sample_rate=24000", "-af", f"volume={volume}",
         "-c:a", "libmp3lame", "-b:a", "64k", str(path)],
        check=True, capture_output=True,
    )
    return path


def _integrated_lufs(path: Path) -> float:
    proc = subprocess.run([podcast.ffmpeg_exe(), "-hide_banner", "-nostdin", "-i", str(path), "-af", "ebur128",
                           "-f", "null", "-"], capture_output=True, text=True, encoding="utf-8", errors="replace",
                          check=False)
    summary = proc.stderr[proc.stderr.rfind("Summary"):]
    return float(re.search(r"I:\s+(-?[\d.]+) LUFS", summary).group(1))


def test_concat_with_loudnorm_reaches_target(tmp_path: Path) -> None:
    quiet = _tone(tmp_path / "a.mp3", 0.05)
    loud = _tone(tmp_path / "b.mp3", 0.5, freq=660)
    plain = podcast.concat_audio([quiet, loud], tmp_path / "plain.mp3", 0.3)
    norm = podcast.concat_audio([quiet, loud], tmp_path / "norm.mp3", 0.3,
                                loudness_lufs=podcast.PODCAST_LOUDNESS_LUFS)
    assert abs(_integrated_lufs(norm) - podcast.PODCAST_LOUDNESS_LUFS) < 1.5
    assert abs(_integrated_lufs(plain) - podcast.PODCAST_LOUDNESS_LUFS) > 3
    # La normalización no cambia la duración (los segmentos del SRT siguen cuadrando).
    assert abs(podcast.audio_duration_s(norm) - podcast.audio_duration_s(plain)) < 0.1
    assert not list(tmp_path.glob("*.tmp*")) and not list(tmp_path.glob("*.filtergraph.txt"))


def test_loudnorm_filter_text() -> None:
    assert podcast.loudnorm_filter(-16.0).startswith("loudnorm=I=-16.0:TP=-1.5:LRA=11.0,aresample=24000")


def test_mock_wav_podcast_skips_loudnorm(tmp_path: Path) -> None:
    script = PodcastScript(title="t", lines=[ScriptLine(speaker="A", text="Hola"), ScriptLine(speaker="B", text="Adiós")])
    audio = podcast.synthesize_podcast(script, MockTTS(), tmp_path, "a", "b")
    assert audio.path.suffix == ".wav" and audio.path.exists()  # vía stdlib, sin ffmpeg


class _FlakyTTS(MockTTS):
    """Falla siempre en las líneas que contienen «FALLA»; cuenta las llamadas."""

    def __init__(self) -> None:
        super().__init__()
        self.calls = 0
        self.lock = threading.Lock()

    def synthesize(self, text: str, voice: str, out_path: Path) -> Path:
        with self.lock:
            self.calls += 1
        if "FALLA" in text:
            raise ConnectionError("servicio caído")
        return super().synthesize(text, voice, out_path)


def test_failed_podcast_leaves_no_parts_and_fails_fast(tmp_path: Path) -> None:
    lines = [ScriptLine(speaker="A", text="FALLA aquí")] + [
        ScriptLine(speaker="AB"[i % 2], text=f"Línea {i}") for i in range(1, 40)
    ]
    tts = _FlakyTTS()
    with pytest.raises(ConnectionError, match="servicio caído"):  # la causa real, no «cancelada»
        podcast.synthesize_podcast(PodcastScript(title="t", lines=lines), tts, tmp_path, "a", "b",
                                   max_workers=1, retries=2)
    assert not (tmp_path / "parts").exists()
    assert tts.calls == 3  # 1 intento + 2 reintentos de la línea 0; el resto no se intenta


def test_failed_podcast_parallel_propagates_root_cause(tmp_path: Path) -> None:
    lines = [ScriptLine(speaker="AB"[i % 2], text=f"Línea {i}") for i in range(20)]
    lines[5] = ScriptLine(speaker="B", text="FALLA")
    with pytest.raises(ConnectionError):
        podcast.synthesize_podcast(PodcastScript(title="t", lines=lines), _FlakyTTS(), tmp_path, "a", "b",
                                   max_workers=4, retries=0)
    assert not (tmp_path / "parts").exists()


# ── Locución: reglas nuevas y guion real del pregenerado ───────────────────────────


@pytest.mark.parametrize(
    "text,expected",
    [
        ("El S&P 500 sube", "El Standard and Poor's 500 sube"),
        ("la IA generativa", "la inteligencia artificial generativa"),
        ("una IPO y un ETF", "una salida a bolsa y un fondo cotizado"),
        ("a las 15:30 h", "a las quince treinta horas"),
        ("a las 9:05", "a las nueve y cinco"),
        ("el 1º de octubre", "el primero de octubre"),
        ("la 3ª sesión y el 1er trimestre", "la tercera sesión y el primer trimestre"),
        ("de 5 a 6", "de 5 a 6"),
        ("dividendo de 0,25 €/acción", "dividendo de cero coma veinticinco euros por acción"),
        ("cotiza a 3,5x ventas", "cotiza a tres coma cinco veces ventas"),
        ("el 5 oct. 2026", "el cinco de octubre de dos mil veintiséis"),
        ("el 5 de oct.", "el cinco de octubre"),
        ("+/- 3%", "más o menos tres por ciento"),
        ("sube 10 bps", "sube diez puntos básicos"),
        ("el nº 1", "el número 1"),
        ("EUR/USD en 1,16", "euro dólar en uno coma dieciséis"),
        ("en el FY26", "en el año fiscal dos mil veintiséis"),
        ("YTD sube un 12%", "en lo que va de año sube un doce por ciento"),
        ("Esto es Market Briefer.", "Esto es Márket Brífer."),
        ("ratio 2:1", "ratio 2:1"),
    ],
)
def test_normalize_new_rules(text: str, expected: str) -> None:
    assert normalize_for_speech(text) == expected
    assert normalize_for_speech(expected) == expected or normalize_for_speech(normalize_for_speech(text)) == expected


@pytest.mark.skipif(not DEMO_JSON.exists(), reason="sin briefing pregenerado")
def test_demo_script_reads_cleanly() -> None:
    """Todo el guion real del pregenerado: sin símbolos, decimales, tickers ni siglas que se lean mal."""
    lines = [line["text"] for line in json.loads(DEMO_JSON.read_text(encoding="utf-8"))["script"]["lines"]]
    assert lines
    for line in lines:
        out = normalize_for_speech(line)
        for bad in ("%", "€", "$", "&", ".MC", "^", "NVIDIA", "S&P", "ese and pe", "Market Briefer"):
            assert bad not in out, (bad, out)
        assert not re.search(r"\d[.,]\d", out), out  # ningún decimal ni miles con punto
        assert normalize_for_speech(out) == out  # idempotente
