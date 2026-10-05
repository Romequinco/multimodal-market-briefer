"""Fixtures comunes: fuerza proveedores mock y rutas temporales para que los tests no
usen red, claves reales ni escriban en ``data/outputs``.

Aislamiento (antes había un test intermitente: ``test_fetch_news_combines_dedupes_and_tags``
fallaba en la suite completa y leía noticias reales de ``data/cache``):

- Hilos *daemon* de un test (``enrich_news`` deja peticiones de metadatos en curso al agotar su
  presupuesto) seguían vivos tras deshacerse el ``monkeypatch``: llamaban a la red real y a
  ``get_settings()`` con el entorno ya restaurado, así que la caché de ``Settings`` podía quedarse
  apuntando al ``.env`` y a la caché real (``data/cache``) durante el test siguiente. Ahora:
  1. Durante TODA la sesión el entorno de pruebas (proveedores mock, caché y salidas en un
     temporal) está fijado y no se lee el ``.env`` (``_session_env``): un hilo rezagado nunca ve
     la configuración real.
  2. Ninguna conexión sale de la máquina (``_block_network``): solo ``localhost``.
  3. Cada test espera a sus hilos de ingesta rezagados antes de deshacer el ``monkeypatch`` y
     reinicia los estados globales de la ingesta (cortocircuito de yfinance, robots, Google).

Los tests ``live`` (``-m live``, ``RUN_LIVE=1`` o ``BRIEFER_TESTS_ALLOW_NETWORK=1``) quedan fuera
de 1 y 2: necesitan red y las claves del ``.env``.
"""

from __future__ import annotations

import os
import shutil
import socket
import tempfile
import threading
import time
from datetime import date, datetime
from pathlib import Path

import pytest

from briefer.config import ROOT_DIR, Settings, reset_settings_cache
from briefer.schemas import (
    Analysis,
    AudioAsset,
    AudioSegment,
    Briefing,
    ChartAsset,
    DocumentInsight,
    KeyPoint,
    MarketContext,
    NewsItem,
    PodcastScript,
    Portfolio,
    Position,
    PriceSnapshot,
    ScriptLine,
    StepMetric,
    Transcript,
    VideoAsset,
)

SAMPLES_DIR = ROOT_DIR / "data" / "samples"

_PROVIDER_ENV = {
    "BRIEFER_LLM_PROVIDER": "mock",
    "BRIEFER_VISION_PROVIDER": "mock",
    "BRIEFER_STT_PROVIDER": "mock",
    "BRIEFER_TTS_PROVIDER": "mock",
    "BRIEFER_IMAGE_GEN_PROVIDER": "mock",
    "BRIEFER_IMAGE_CLASSIFIER_PROVIDER": "mock",
}


#: Prefijos de los hilos de la ingesta que pueden sobrevivir a la llamada que los lanzó.
_INGEST_THREAD_PREFIXES = ("news", "currency")
#: Espera máxima (s) a los hilos rezagados de un test antes de deshacer su ``monkeypatch``.
_STRAGGLER_JOIN_S = 10.0


def _wants_network(config: pytest.Config) -> bool:
    """True si se piden tests con red real (``-m live``, ``RUN_LIVE=1`` o ``BRIEFER_TESTS_ALLOW_NETWORK=1``)."""
    markexpr = (getattr(config.option, "markexpr", "") or "").replace(" ", "")
    live = "live" in markexpr and "notlive" not in markexpr
    return live or os.environ.get("RUN_LIVE") == "1" or os.environ.get("BRIEFER_TESTS_ALLOW_NETWORK") == "1"


_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0", "", None}


class NetworkBlockedError(ConnectionError):
    """Un test ha intentado salir a la red (los tests no usan red; ver docstring de conftest)."""


def _is_local(address: object) -> bool:
    if isinstance(address, (str, bytes)):  # AF_UNIX
        return True
    if isinstance(address, tuple) and address:
        host = address[0]
        return host in _LOCAL_HOSTS or str(host).startswith("127.")
    return False


_session_state: dict[str, object] = {}


def pytest_configure(config: pytest.Config) -> None:
    """Entorno de pruebas para todo el proceso (también para hilos rezagados) y red cortada."""
    if _wants_network(config):
        return
    tmp = Path(tempfile.mkdtemp(prefix="briefer-tests-"))
    env = {**_PROVIDER_ENV, "BRIEFER_OUTPUT_DIR": str(tmp / "outputs"), "BRIEFER_CACHE_DIR": str(tmp / "cache")}
    _session_state.update(tmp=tmp, env={k: os.environ.get(k) for k in env},
                          env_file=Settings.model_config.get("env_file"))
    os.environ.update(env)
    Settings.model_config["env_file"] = None  # los tests nunca leen el .env (claves reales)
    reset_settings_cache()

    real_connect, real_connect_ex, real_getaddrinfo = (
        socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo,
    )

    def connect(self, address):  # type: ignore[no-untyped-def]
        if not _is_local(address):
            raise NetworkBlockedError(f"Red bloqueada en tests: conexión a {address!r}")
        return real_connect(self, address)

    def connect_ex(self, address):  # type: ignore[no-untyped-def]
        if not _is_local(address):
            raise NetworkBlockedError(f"Red bloqueada en tests: conexión a {address!r}")
        return real_connect_ex(self, address)

    def getaddrinfo(host, *args, **kwargs):  # type: ignore[no-untyped-def]
        name = host.decode() if isinstance(host, bytes) else host
        if name not in _LOCAL_HOSTS and not str(name).startswith("127."):
            raise NetworkBlockedError(f"Red bloqueada en tests: resolución de {name!r}")
        return real_getaddrinfo(host, *args, **kwargs)

    socket.socket.connect = connect  # type: ignore[method-assign]
    socket.socket.connect_ex = connect_ex  # type: ignore[method-assign]
    socket.getaddrinfo = getaddrinfo
    _session_state["socket"] = (real_connect, real_connect_ex, real_getaddrinfo)


def pytest_unconfigure(config: pytest.Config) -> None:
    if "socket" in _session_state:
        socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo = _session_state.pop("socket")  # type: ignore[misc]
    if "env" in _session_state:
        for key, value in _session_state.pop("env").items():  # type: ignore[union-attr]
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        Settings.model_config["env_file"] = _session_state.pop("env_file")
        reset_settings_cache()
    tmp = _session_state.pop("tmp", None)
    if tmp is not None:
        shutil.rmtree(tmp, ignore_errors=True)  # type: ignore[arg-type]


def _reset_ingest_state() -> None:
    """Estados globales de la ingesta (cortocircuito de yfinance, robots.txt y pausa de Google)."""
    from briefer.ingest import article_meta, news

    news._reset_yf_news_state()
    article_meta._reset_robots_state()
    article_meta._reset_google_state()


def _ingest_threads() -> set[threading.Thread]:
    return {t for t in threading.enumerate() if t.name.startswith(_INGEST_THREAD_PREFIXES) and t.is_alive()}


@pytest.fixture(autouse=True)
def _mock_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Todos los proveedores en mock, salidas en un directorio temporal y estado de ingesta limpio.

    Al terminar, espera a los hilos de ingesta que el test dejó en marcha (antes de que el
    ``monkeypatch`` restaure las funciones de red reales que esos hilos podrían llamar).
    """
    for key, value in _PROVIDER_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("BRIEFER_OUTPUT_DIR", str(tmp_path / "outputs"))
    monkeypatch.setenv("BRIEFER_CACHE_DIR", str(tmp_path / "cache"))
    reset_settings_cache()
    _reset_ingest_state()
    before = _ingest_threads()
    yield
    deadline = time.monotonic() + _STRAGGLER_JOIN_S
    for thread in _ingest_threads() - before:
        thread.join(max(0.0, deadline - time.monotonic()))
    _reset_ingest_state()
    reset_settings_cache()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Settings explícitos (sin leer .env) con todo en mock."""
    return Settings(
        _env_file=None,
        briefer_llm_provider="mock",
        briefer_vision_provider="mock",
        briefer_stt_provider="mock",
        briefer_tts_provider="mock",
        briefer_image_gen_provider="mock",
        briefer_image_classifier_provider="mock",
        briefer_output_dir=tmp_path / "outputs",
        briefer_cache_dir=tmp_path / "cache",
    )


@pytest.fixture
def sample_context() -> MarketContext:
    news = NewsItem(
        id="ejemplo-001",
        title="[EJEMPLO] El banco sube",
        summary="Noticia ficticia para tests.",
        source="Ejemplo",
        url="https://example.com/1",
        published_at=datetime(2026, 10, 5, 8, 0),
        tickers=["SAN.MC"],
    )
    price = PriceSnapshot(
        ticker="SAN.MC",
        last=5.1,
        change_pct=1.2,
        currency="EUR",
        history=[(date(2026, 10, 2), 5.0), (date(2026, 10, 5), 5.1)],
    )
    insight = DocumentInsight(
        source_type="pdf",
        source_name="resultados.pdf",
        extracted_text="Ingresos 100",
        key_figures={"Ingresos": "100 M€"},
        summary="Resultados ficticios.",
    )
    portfolio = Portfolio(name="Test", positions=[Position(ticker="san.mc", weight=1.0)])
    return MarketContext(
        date=date(2026, 10, 5),
        tickers=["SAN.MC"],
        news=[news],
        prices=[price],
        insights=[insight],
        portfolio=portfolio,
    )


@pytest.fixture
def sample_briefing(sample_context: MarketContext, tmp_path: Path) -> Briefing:
    analysis = Analysis(
        date=date(2026, 10, 5),
        headline="Titular",
        key_points=[
            KeyPoint(
                title="Punto",
                explanation="Explicación",
                tickers=["SAN.MC"],
                sentiment="positivo",
                sources=["ejemplo-001"],
            )
        ],
        market_mood="Neutral",
    )
    script = PodcastScript(
        title="Episodio",
        lines=[ScriptLine(speaker="A", text="Hola"), ScriptLine(speaker="B", text="Buenas")],
        est_duration_s=2.0,
    )
    audio = AudioAsset(
        path=tmp_path / "podcast.mp3",
        duration_s=2.0,
        segments=[
            AudioSegment(speaker="A", text="Hola", start_s=0.0, end_s=1.0),
            AudioSegment(speaker="B", text="Buenas", start_s=1.0, end_s=2.0),
        ],
    )
    return Briefing(
        id="20261005-090000-abcdef",
        created_at=datetime(2026, 10, 5, 9, 0),
        context=sample_context,
        analysis=analysis,
        script=script,
        audio=audio,
        transcript=Transcript(text="A: Hola\nB: Buenas", srt_path=tmp_path / "podcast.srt"),
        charts=[ChartAsset(path=tmp_path / "c.png", ticker="SAN.MC", kind="price_line")],
        cover_path=None,
        video=VideoAsset(path=tmp_path / "v.mp4", duration_s=2.0),
        metrics=[StepMetric(step="x", provider="mock", model="m", latency_s=0.1, est_cost_eur=0.0)],
    )
