"""``EdgeTTS`` sin red: se sustituye ``edge_tts.Communicate`` por un doble con ``monkeypatch``.

El test real (``test_edge_tts_live_two_voices``) va marcado ``live`` y solo se ejecuta con
``RUN_LIVE=1`` (necesita red, no claves).
"""

from __future__ import annotations

import asyncio
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

edge_tts = pytest.importorskip("edge_tts")

from briefer.config import Settings  # noqa: E402
from briefer.providers.tts.edge_tts_provider import EdgeTTS  # noqa: E402

FAKE_MP3 = b"ID3\x03\x00\x00\x00\x00\x00\x00" + b"\xff\xfb\x90\x00" * 64


class FakeCommunicate:
    """Doble de ``edge_tts.Communicate``: registra las llamadas y escribe bytes de «MP3»."""

    calls: list[dict] = []
    fail_times: int = 0
    exc_factory = staticmethod(lambda: edge_tts.exceptions.WebSocketError("conexión cerrada"))
    lock = threading.Lock()

    def __init__(self, text, voice, *, rate="+0%", pitch="+0Hz", connect_timeout=None,
                 receive_timeout=None, **_):
        self.text, self.voice, self.rate, self.pitch = text, voice, rate, pitch

    async def save(self, path: str) -> None:
        await asyncio.sleep(0)
        with FakeCommunicate.lock:
            FakeCommunicate.calls.append(
                {"text": self.text, "voice": self.voice, "rate": self.rate, "pitch": self.pitch,
                 "thread": threading.get_ident()}
            )
            if FakeCommunicate.fail_times > 0:
                FakeCommunicate.fail_times -= 1
                raise FakeCommunicate.exc_factory()
        Path(path).write_bytes(FAKE_MP3)


@pytest.fixture
def fake_edge(monkeypatch: pytest.MonkeyPatch):
    FakeCommunicate.calls = []
    FakeCommunicate.fail_times = 0
    FakeCommunicate.exc_factory = staticmethod(lambda: edge_tts.exceptions.WebSocketError("conexión cerrada"))
    monkeypatch.setattr(edge_tts, "Communicate", FakeCommunicate)
    return FakeCommunicate


def _tts(settings: Settings, **kw) -> EdgeTTS:
    kw.setdefault("backoff_s", 0.0)
    return EdgeTTS(settings, **kw)


def test_synthesize_writes_mp3_and_changes_extension(fake_edge, settings: Settings, tmp_path: Path) -> None:
    out = _tts(settings).synthesize("Hola  mundo\n", "es-ES-AlvaroNeural", tmp_path / "sub" / "linea.wav")
    assert out == tmp_path / "sub" / "linea.mp3"
    assert out.read_bytes() == FAKE_MP3
    assert fake_edge.calls[0]["text"] == "Hola mundo"  # espacios colapsados
    assert fake_edge.calls[0]["voice"] == "es-ES-AlvaroNeural"
    assert not list(out.parent.glob("*.part"))  # sin temporales


def test_provider_metadata(settings: Settings) -> None:
    tts = EdgeTTS(settings)
    assert tts.provider_name == "edge"
    assert tts.model == "edge-tts"
    assert tts.audio_extension == ".mp3"


def test_default_rate_is_option_b(settings: Settings) -> None:
    """Opción «B» de la cata: +10 % por defecto, también con ``BRIEFER_TTS_RATE=`` vacío en .env."""
    assert EdgeTTS(Settings(_env_file=None)).rate == "+10%"
    assert EdgeTTS(Settings(_env_file=None, briefer_tts_rate="")).rate == "+10%"
    assert EdgeTTS(None).rate == "+10%"
    assert EdgeTTS(Settings(_env_file=None, briefer_tts_rate="+0%")).rate == "+0%"  # override por .env


def test_rate_and_pitch_default_and_override(fake_edge, settings: Settings, tmp_path: Path) -> None:
    tts = _tts(settings, rate="+8%", pitch="-2Hz")
    tts.synthesize("uno", "v", tmp_path / "a")
    tts.synthesize("dos", "v", tmp_path / "b", rate="-5%", pitch="+1Hz")
    assert (fake_edge.calls[0]["rate"], fake_edge.calls[0]["pitch"]) == ("+8%", "-2Hz")
    assert (fake_edge.calls[1]["rate"], fake_edge.calls[1]["pitch"]) == ("-5%", "+1Hz")


@pytest.mark.parametrize("kwargs", [{"rate": "8%"}, {"rate": "+abc%"}, {"pitch": "+2"}, {"pitch": "2Hz"}])
def test_invalid_rate_or_pitch(settings: Settings, kwargs: dict) -> None:
    with pytest.raises(ValueError):
        EdgeTTS(settings, **kwargs)


@pytest.mark.parametrize("text,voice", [("", "v"), ("   ", "v"), ("hola", ""), ("hola", "  ")])
def test_empty_text_or_voice(fake_edge, settings: Settings, tmp_path: Path, text: str, voice: str) -> None:
    with pytest.raises(ValueError):
        _tts(settings).synthesize(text, voice, tmp_path / "x")
    assert fake_edge.calls == []


def test_retries_transient_errors_then_succeeds(fake_edge, settings: Settings, tmp_path: Path) -> None:
    fake_edge.fail_times = 2
    out = _tts(settings, retries=2).synthesize("hola", "v", tmp_path / "x")
    assert out.exists()
    assert len(fake_edge.calls) == 3


def test_retries_exhausted_raise_runtime_error(fake_edge, settings: Settings, tmp_path: Path) -> None:
    fake_edge.fail_times = 10
    with pytest.raises(RuntimeError, match="3 intentos") as info:
        _tts(settings, retries=2).synthesize("hola", "v", tmp_path / "x")
    assert isinstance(info.value.__cause__, edge_tts.exceptions.WebSocketError)
    assert len(fake_edge.calls) == 3
    assert not (tmp_path / "x.mp3").exists()
    assert not list(tmp_path.glob("*.part"))


def test_network_errors_are_retried(fake_edge, settings: Settings, tmp_path: Path) -> None:
    fake_edge.fail_times = 1
    fake_edge.exc_factory = staticmethod(lambda: ConnectionResetError("reset"))
    assert _tts(settings, retries=1).synthesize("hola", "v", tmp_path / "x").exists()


def test_usage_errors_are_not_retried(fake_edge, settings: Settings, tmp_path: Path) -> None:
    fake_edge.fail_times = 5
    fake_edge.exc_factory = staticmethod(lambda: ValueError("voz no válida"))
    with pytest.raises(ValueError):
        _tts(settings, retries=3).synthesize("hola", "v", tmp_path / "x")
    assert len(fake_edge.calls) == 1


def test_empty_audio_counts_as_failure(monkeypatch: pytest.MonkeyPatch, settings: Settings, tmp_path: Path) -> None:
    calls = []

    class Silent(FakeCommunicate):
        async def save(self, path: str) -> None:
            calls.append(path)
            Path(path).write_bytes(b"")

    monkeypatch.setattr(edge_tts, "Communicate", Silent)
    with pytest.raises(RuntimeError):
        _tts(settings, retries=1).synthesize("hola", "v", tmp_path / "x")
    assert len(calls) == 2


def test_thread_safe_parallel_calls(fake_edge, settings: Settings, tmp_path: Path) -> None:
    tts = _tts(settings)
    with ThreadPoolExecutor(max_workers=6) as pool:
        outs = list(pool.map(lambda i: tts.synthesize(f"línea {i}", "v", tmp_path / f"{i:03d}"), range(24)))
    assert [p.name for p in outs] == [f"{i:03d}.mp3" for i in range(24)]
    assert all(p.read_bytes() == FAKE_MP3 for p in outs)
    assert len({c["thread"] for c in fake_edge.calls}) > 1


def test_works_inside_running_event_loop(fake_edge, settings: Settings, tmp_path: Path) -> None:
    """Si el hilo ya tiene un bucle activo (notebook), la síntesis va a un hilo auxiliar."""
    tts = _tts(settings)

    async def main() -> Path:
        return tts.synthesize("hola", "v", tmp_path / "loop")

    out = asyncio.run(main())
    assert out.exists()


def test_registry_builds_edge_tts(monkeypatch: pytest.MonkeyPatch) -> None:
    from briefer.config import reset_settings_cache
    from briefer.providers import registry

    monkeypatch.setenv("BRIEFER_TTS_PROVIDER", "edge")
    reset_settings_cache()
    assert isinstance(registry.get_tts(), EdgeTTS)


@pytest.mark.live
@pytest.mark.skipif(os.environ.get("RUN_LIVE") != "1", reason="test real: exportar RUN_LIVE=1 (usa red)")
def test_edge_tts_live_two_voices(settings: Settings, tmp_path: Path) -> None:
    from briefer.media.podcast import audio_duration_s

    tts = EdgeTTS(settings)
    for voice in (settings.briefer_voice_a, settings.briefer_voice_b):
        out = tts.synthesize("Buenas noches, esto es una prueba de Briefly.", voice, tmp_path / voice)
        assert out.stat().st_size > 1000
        assert 1.0 < audio_duration_s(out) < 10.0
