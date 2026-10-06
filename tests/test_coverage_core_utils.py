"""Cobertura de utilidades transversales sin red: estimación de costes, redacción de secretos y
logging, caché diaria «best effort», registro de proveedores y generador de instancias del mock."""

from __future__ import annotations

import json
import logging
import typing
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import BaseModel, SecretStr

from briefer import costs, logging_utils
from briefer.config import Settings
from briefer.ingest import cache
from briefer.providers import mock, registry
from briefer.schemas import StepMetric

# ── costes ────────────────────────────────────────────────────────────────────────


def test_token_estimates() -> None:
    assert costs.estimate_tokens("") == 0
    assert costs.estimate_tokens("abc") == 1
    assert costs.estimate_tokens("a" * 400) == 100
    assert costs.estimate_image_tokens(10, 10) == 1
    assert costs.estimate_image_tokens(1500, 750) == 1500


def test_llm_price_prefix_lookup() -> None:
    assert costs.llm_price_usd_per_mtok("claude-haiku-4-5-20251001") == (1.00, 5.00)
    assert costs.llm_price_usd_per_mtok("modelo-desconocido") is None
    assert costs.estimate_llm_cost_eur("modelo-desconocido", 1000, 1000) == 0.0


def test_prompt_cache_multipliers() -> None:
    base = costs.estimate_llm_cost_eur("claude-sonnet-5-5", input_tokens=1_000_000)
    read = costs.estimate_llm_cost_eur("claude-sonnet-5-5", cache_read_input_tokens=1_000_000)
    write = costs.estimate_llm_cost_eur("claude-sonnet-5-5", cache_creation_input_tokens=1_000_000)
    assert read == pytest.approx(base * costs.CACHE_READ_MULTIPLIER)
    assert write == pytest.approx(base * costs.CACHE_WRITE_MULTIPLIER)


def test_estimate_cost_dispatcher_branches() -> None:
    assert costs.estimate_cost_eur("mock", "claude-sonnet-5-5", input_tokens=10**6) == 0.0
    stt = costs.estimate_cost_eur("openai", "whisper-1", duration_s=60)
    assert stt == pytest.approx(0.006 * costs.USD_TO_EUR)
    assert costs.estimate_stt_cost_eur("modelo-raro", 60) == 0.0
    tts = costs.estimate_cost_eur("elevenlabs", "-", n_chars=1000)
    assert tts == pytest.approx(0.18 * costs.USD_TO_EUR)
    assert costs.estimate_cost_eur("edge", "-", n_chars=10_000) == 0.0
    assert costs.estimate_cost_eur("otro_img", "-", n_images=3) == 0.0
    assert costs.estimate_image_cost_eur("sdxl_turbo", 4) == 0.0
    assert costs.estimate_cost_eur("anthropic", "claude-sonnet-5-5") == 0.0  # sin datos de uso


def _metric(step: str, cost: float, latency: float = 1.0) -> StepMetric:
    return StepMetric(step=step, provider="anthropic", model="m", latency_s=latency, est_cost_eur=cost)


def test_cost_breakdown_and_summary() -> None:
    metrics = [_metric("a", 0.03), _metric("b", 0.01), _metric("c", 0.0)]
    assert costs.cost_breakdown(metrics) == [("a", 0.03, 75.0), ("b", 0.01, 25.0)]
    assert costs.cost_breakdown([_metric("c", 0.0)]) == []
    summary = costs.summarize_metrics(metrics)
    assert summary == {"steps": 3.0, "total_latency_s": 3.0, "total_cost_eur": 0.04}
    text = costs.format_cost_summary(metrics, label="Q&A")
    assert text.startswith("Coste estimado del Q&A: 0,0400 €") and "a 0,0300 € (75 %)" in text
    assert "0 €" in costs.format_cost_summary([])


# ── logging y secretos ────────────────────────────────────────────────────────────


def test_redact_handles_unprintable_objects() -> None:
    class Weird:
        def __str__(self) -> str:
            raise RuntimeError("no imprimible")

    assert logging_utils.redact_secrets(Weird()) == "<error no representable>"


@pytest.mark.parametrize(
    ("raw", "leak"),
    [
        ("https://api.telegram.org/bot123456789:AAEabcdefghijklmnopqrstuvwxyz012/sendMessage",
         "AAEabcdefghijklmnopqrstuvwxyz012"),
        ("GET https://g.example/v1?key=AIzaSyA1234567890abcdef&alt=json", "AIzaSyA1234567890abcdef"),
        ("headers={'x-api-key': 'clave-secreta-muy-larga'}", "clave-secreta-muy-larga"),
        ("Authorization: Bearer tok_abcdef123456", "tok_abcdef123456"),
        ("token AQ.Ab8RN6abcdefghijk1234 caducado", "AQ.Ab8RN6abcdefghijk1234"),
    ],
)
def test_redact_known_patterns(raw: str, leak: str) -> None:
    assert leak not in logging_utils.redact_secrets(raw)


def test_redact_extra_values_and_settings_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "valor-literal-del-token")
    from briefer.config import reset_settings_cache

    reset_settings_cache()
    text = "fallo con valor-literal-del-token y extra-1234"
    out = logging_utils.redact_secrets(text, extra=["extra-1234", "abc"])  # "abc": demasiado corto
    assert "valor-literal" not in out and "extra-1234" not in out


def _fake_get_settings(value: object | None):
    """Sustituto de ``config.get_settings`` (con ``cache_clear``, que usa el conftest al terminar).

    ``None`` simula una configuración inválida (lanza ``ValueError``).
    """

    def fake():
        if value is None:
            raise ValueError("config inválida")
        return value

    fake.cache_clear = lambda: None  # type: ignore[attr-defined]
    return fake


def test_settings_secrets_tolerates_broken_config(monkeypatch: pytest.MonkeyPatch) -> None:
    import briefer.config as config

    monkeypatch.setattr(config, "get_settings", _fake_get_settings(None))
    assert logging_utils._settings_secrets() == []
    assert logging_utils.redact_secrets("sk-abcdefghijklmnop") == "sk-***"


def test_settings_secrets_skips_failing_getters(monkeypatch: pytest.MonkeyPatch) -> None:
    import briefer.config as config

    class Boom:
        def get_secret_value(self) -> str:
            raise RuntimeError("no")

    class FakeSettings(BaseModel):
        model_config = {"arbitrary_types_allowed": True}
        a: typing.Any = None
        b: SecretStr = SecretStr("secreto-largo-1")

    fake = FakeSettings(a=Boom())
    monkeypatch.setattr(config, "get_settings", _fake_get_settings(fake))
    assert logging_utils._settings_secrets() == ["secreto-largo-1"]


def test_error_text_without_message_and_truncation() -> None:
    assert logging_utils.error_text(KeyError()) == "KeyError"
    long = logging_utils.error_text(RuntimeError("x" * 500), max_chars=20)
    assert long == "RuntimeError: " + "x" * 20


def test_get_logger_names_and_redacting_formatter(monkeypatch: pytest.MonkeyPatch) -> None:
    assert logging_utils.get_logger().name == "briefer"
    assert logging_utils.get_logger("briefer.x").name == "briefer.x"
    assert logging_utils.get_logger("ingest").name == "briefer.ingest"
    fmt = logging_utils._RedactingFormatter("%(message)s")
    record = logging.LogRecord("briefer", logging.INFO, __file__, 1, "clave sk-abcdefghijklmnop", None, None)
    assert fmt.format(record) == "clave sk-***"


def test_get_logger_survives_invalid_config(monkeypatch: pytest.MonkeyPatch) -> None:
    import briefer.config as config

    monkeypatch.setattr(logging_utils, "_configured", False)
    monkeypatch.setattr(config, "get_settings", _fake_get_settings(None))
    root = logging.getLogger("briefer")
    level = root.level
    root.setLevel(logging.NOTSET)  # sin nivel previo: lo fija get_logger (INFO por defecto)
    try:
        assert logging_utils.get_logger("x").name == "briefer.x"
        assert root.level == logging.INFO
    finally:
        root.setLevel(level)


def test_track_step_records_failure_and_redacts() -> None:
    metrics: list[StepMetric] = []
    with pytest.raises(RuntimeError):
        with logging_utils.track_step("paso", "p", "m", metrics) as handle:
            handle.detail = "nota con sk-abcdefghijklmnop"
            raise RuntimeError("fallo con sk-abcdefghijklmnop")
    (metric,) = metrics
    assert logging_utils.step_failed(metric) and not logging_utils.step_fell_back(metric)
    assert "sk-***" in logging_utils.step_error(metric) and metric.detail == "nota con sk-***"
    assert handle.metric is metric
    ok = StepMetric(step="x", provider="p", model="m", latency_s=0.0, est_cost_eur=0.0)
    assert logging_utils.step_error(ok) is None and not logging_utils.step_failed(ok)
    fb = ok.model_copy(update={"error": logging_utils.fallback_error("mock", ValueError("v"))})
    assert logging_utils.step_fell_back(fb) and fb.error == "Fallback a mock tras ValueError: v"


# ── caché diaria ──────────────────────────────────────────────────────────────────


def test_cache_corrupt_file_is_ignored(caplog: pytest.LogCaptureFixture) -> None:
    path = cache.cache_file("prices", "k1")
    path.write_text("{roto", encoding="utf-8")
    with caplog.at_level("WARNING", logger="briefer.ingest.cache"):
        assert cache.read_cache("prices", "k1") is None
    assert any("ilegible" in r.getMessage() for r in caplog.records)


def test_cache_key_and_unsafe_names() -> None:
    assert cache.cache_key("a", 1) == cache.cache_key("a", 1) != cache.cache_key("a", 2)
    path = cache.cache_file("news/meta x", "../k", date(2026, 10, 5))
    assert path.name == "news_meta_x_.._k_20261005.json" and path.parent == cache.cache_dir()


def test_read_recent_finds_older_entries() -> None:
    old = date.today() - timedelta(days=3)
    cache.write_cache("news-robots", "host", {"allow_all": True}, day=old)
    assert cache.read_recent("news-robots", "host", days=7) == {"allow_all": True}
    assert cache.read_recent("news-robots", "host", days=2) is None
    assert cache.read_recent("news-robots", "otro", days=0) is None  # mínimo: hoy


def test_write_cache_unserializable_is_logged_and_leaves_no_temp(caplog: pytest.LogCaptureFixture) -> None:
    cache.write_cache("prices", "k2", {"z": object(), "y": date(2026, 10, 5)})  # default=str
    stored = cache.read_cache("prices", "k2")
    assert stored["y"] == "2026-10-05" and isinstance(stored["z"], str)
    with caplog.at_level("WARNING", logger="briefer.ingest.cache"):
        cache.write_cache("prices", "k3", _circular())  # ValueError: referencia circular
    assert cache.read_cache("prices", "k3") is None
    assert not list(cache.cache_dir().glob("*.tmp"))
    assert any("No se pudo escribir" in r.getMessage() for r in caplog.records)


def _circular() -> dict:
    d: dict = {}
    d["d"] = d
    return d


def test_purge_old_removes_only_old_and_well_named(monkeypatch: pytest.MonkeyPatch) -> None:
    d = cache.cache_dir()
    old = date.today() - timedelta(days=10)
    (d / f"prices_a_{old:%Y%m%d}.json").write_text("{}", encoding="utf-8")
    (d / "prices_b_20261399.json").write_text("{}", encoding="utf-8")  # fecha imposible
    (d / "suelto_sin_fecha.json").write_text("{}", encoding="utf-8")
    cache.write_cache("prices", "hoy", {"ok": 1})
    assert cache.purge_old(7) == 1
    names = {p.name for p in d.iterdir()}
    assert "prices_b_20261399.json" in names and "suelto_sin_fecha.json" in names


def test_maybe_purge_runs_once_per_day_and_tolerates_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    def boom(keep: int) -> int:
        calls.append(keep)
        raise OSError("disco")

    monkeypatch.setitem(cache._purged, "day", None)
    monkeypatch.setattr(cache, "purge_old", boom)
    cache._maybe_purge()
    cache._maybe_purge()
    assert calls == [cache.KEEP_DAYS]

    monkeypatch.setitem(cache._purged, "day", None)
    monkeypatch.setattr(cache, "purge_old", lambda keep: 3)
    cache._maybe_purge()
    assert cache._purged["day"] == date.today()


# ── registro de proveedores ───────────────────────────────────────────────────────


def _settings(tmp_path: Path, **kw) -> Settings:
    base = {
        "_env_file": None, "briefer_output_dir": tmp_path / "o", "briefer_cache_dir": tmp_path / "c",
        "briefer_fallback_to_mock": False,
    }
    return Settings(**(base | kw))


def test_registry_unknown_provider_raises(tmp_path: Path) -> None:
    s = _settings(tmp_path)
    with pytest.raises(registry.ProviderConfigError, match="desconocido"):
        registry._build("llm", "inventado", registry.LLM_IMPLS, mock.MockLLM, s)


def test_registry_import_error_without_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(registry.LLM_IMPLS, "roto", ("briefer.no_existe_modulo", "X", None))
    with pytest.raises(registry.ProviderConfigError, match="No se pudo cargar llm='roto'"):
        registry._build("llm", "roto", registry.LLM_IMPLS, mock.MockLLM, _settings(tmp_path))
    fallback = _settings(tmp_path, briefer_fallback_to_mock=True)
    built = registry._build("llm", "roto", registry.LLM_IMPLS, mock.MockLLM, fallback)
    assert isinstance(built, mock.MockLLM)


def test_registry_missing_secret_without_fallback(tmp_path: Path) -> None:
    s = _settings(tmp_path, briefer_llm_provider="anthropic", anthropic_api_key=None)
    with pytest.raises(registry.ProviderConfigError, match="ANTHROPIC_API_KEY"):
        registry.get_llm(s)


# ── mock: instancias válidas de cualquier anotación ───────────────────────────────


class _Inner(BaseModel):
    nombre: str


@pytest.mark.parametrize(
    ("annotation", "expected"),
    [
        (type(None), None),
        (typing.Literal["a", "b"], "a"),
        (typing.Annotated[int, "meta"], 1),
        (typing.Optional[float], 1.0),  # noqa: UP045 - forma typing.Union a propósito
        (int | None, 1),
        (tuple[int, ...], (1,)),
        (tuple[int, str], (1, "campo (mock)")),
        (dict[str, int], {"clave (mock)": 1}),
        (typing.Dict, {}),  # noqa: UP006 - dict sin parámetros (forma typing) a propósito
        (set[bool], [False]),
        (typing.List, []),  # noqa: UP006 - lista sin parámetros (forma typing) a propósito
        (datetime, mock.FIXED_DATETIME),
        (date, mock.FIXED_DATE),
        (Path, Path("mock")),
        (bytes, None),
    ],
)
def test_fake_value_annotations(annotation: typing.Any, expected: typing.Any) -> None:
    assert mock._fake_value(annotation) == expected


def test_fake_value_nested_model() -> None:
    assert mock._fake_value(_Inner) == _Inner(nombre="nombre (mock)")
    assert mock._fake_value(bool | str) is False  # unión: el primer tipo no nulo


def test_mock_classifier_edge_cases() -> None:
    clf = mock.MockImageClassifier()
    assert clf.classify(b"", []) == {}
    assert clf.classify(b"", ["solo"]) == {"solo": 1.0}
    probs = clf.classify(b"", ["a", "b", "c"])
    assert probs["a"] == 0.7 and sum(probs.values()) == pytest.approx(1.0)


def test_json_roundtrip_of_metrics_summary() -> None:
    """``summarize_metrics`` devuelve solo floats serializables (lo lee la UI y el CLI)."""
    assert json.loads(json.dumps(costs.summarize_metrics([_metric("a", 0.1)])))["steps"] == 1.0
