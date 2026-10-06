"""Portada con Gemini (sin red): cliente simulado, errores sin claves, registro y coste por imagen."""

from __future__ import annotations

import io
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

pytest.importorskip("google.genai")

from briefer import costs  # noqa: E402
from briefer.config import Settings  # noqa: E402
from briefer.providers import registry  # noqa: E402
from briefer.providers.image import gemini_image  # noqa: E402
from briefer.providers.image.gemini_image import GeminiImage  # noqa: E402

FAKE_KEY = "AIzaFAKEKEYfortests0123456789abcdefXYZ"


def _jpeg(size: tuple[int, int] = (1344, 768)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, (20, 30, 50)).save(buf, format="JPEG")
    return buf.getvalue()


class FakeModels:
    """Doble de ``client.models.generate_content`` con imagen, solo texto o excepción."""

    def __init__(self, *, data: bytes | None = None, fail: BaseException | None = None,
                 text_only: bool = False) -> None:
        self.calls: list[dict] = []
        self.data = data
        self.fail = fail
        self.text_only = text_only

    def generate_content(self, *, model, contents, config):
        self.calls.append({"model": model, "contents": contents, "config": config})
        if self.fail is not None:
            raise self.fail
        if self.text_only:
            part = SimpleNamespace(text="No puedo generar esa imagen", inline_data=None)
        else:
            part = SimpleNamespace(inline_data=SimpleNamespace(data=self.data, mime_type="image/jpeg"))
        return SimpleNamespace(
            candidates=[SimpleNamespace(content=SimpleNamespace(parts=[part]), finish_reason="STOP")],
            usage_metadata=SimpleNamespace(prompt_token_count=120, candidates_token_count=1290),
        )


def _settings(tmp_path: Path, **kw) -> Settings:
    base = {
        "_env_file": None,
        "briefer_image_gen_provider": "gemini",
        "gemini_api_key": FAKE_KEY,
        "briefer_output_dir": tmp_path / "outputs",
        "briefer_cache_dir": tmp_path / "cache",
    }
    base.update(kw)
    return Settings(**base)


def _gen(tmp_path: Path, models: FakeModels) -> GeminiImage:
    return GeminiImage(_settings(tmp_path), client=SimpleNamespace(models=models))


def test_generate_saves_png_with_16_9_config(tmp_path: Path) -> None:
    models = FakeModels(data=_jpeg())
    gen = _gen(tmp_path, models)
    out = gen.generate("night skyline, no text", tmp_path / "cover.jpg")
    assert out == tmp_path / "cover.png" and out.exists()
    img = Image.open(out)
    assert img.format == "PNG" and img.size == (1344, 768)
    call = models.calls[0]
    assert call["model"] == "gemini-3.1-flash-lite-image" == gen.model
    assert call["config"].response_modalities == ["IMAGE"]
    assert call["config"].image_config.aspect_ratio == gemini_image.ASPECT_RATIO == "16:9"
    assert gen.last_usage == {"input_tokens": 120, "output_tokens": 1290}
    assert not list(tmp_path.glob("*.part"))


def test_response_without_image_is_clear_error(tmp_path: Path) -> None:
    gen = _gen(tmp_path, FakeModels(text_only=True))
    with pytest.raises(RuntimeError, match="no devolvió ninguna imagen") as info:
        gen.generate("prompt", tmp_path / "c.png")
    assert FAKE_KEY not in str(info.value)
    assert not (tmp_path / "c.png").exists()


def test_undecodable_image_is_error(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="no se puede abrir"):
        _gen(tmp_path, FakeModels(data=b"no es una imagen")).generate("prompt", tmp_path / "c.png")


def test_empty_prompt_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        _gen(tmp_path, FakeModels(data=_jpeg())).generate("  ", tmp_path / "c.png")


def test_no_billing_quota_error_is_translated_without_key(tmp_path: Path) -> None:
    raw = RuntimeError(
        "429 RESOURCE_EXHAUSTED. Quota exceeded for metric: generate_content_free_tier_requests, "
        f"limit: 0, model: gemini-3.1-flash-lite-image key={FAKE_KEY}"
    )
    assert gemini_image.is_no_billing_error(raw)
    with pytest.raises(RuntimeError, match="facturación") as info:
        _gen(tmp_path, FakeModels(fail=raw)).generate("prompt", tmp_path / "c.png")
    assert FAKE_KEY not in str(info.value)
    assert info.value.__cause__ is None and info.value.__suppress_context__


def test_other_errors_propagate(tmp_path: Path) -> None:
    with pytest.raises(ConnectionError):
        _gen(tmp_path, FakeModels(fail=ConnectionError("red caída"))).generate("p", tmp_path / "c.png")
    assert not gemini_image.is_no_billing_error(ConnectionError("red caída"))


def test_missing_key_without_client_raises(tmp_path: Path) -> None:
    gen = GeminiImage(_settings(tmp_path, gemini_api_key=None))
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        gen.generate("p", tmp_path / "c.png")


def test_registry_gemini_image(tmp_path: Path) -> None:
    gen = registry.get_image_gen(_settings(tmp_path))
    assert isinstance(gen, GeminiImage) and gen.provider_name == "gemini"
    fallback = registry.get_image_gen(_settings(tmp_path, gemini_api_key=None))
    assert fallback is not None and fallback.provider_name == "mock"
    with pytest.raises(registry.ProviderConfigError):
        registry.get_image_gen(_settings(tmp_path, gemini_api_key=None, briefer_fallback_to_mock=False))
    assert registry.get_image_gen(_settings(tmp_path, briefer_image_gen_provider="none")) is None
    forced = registry.get_image_gen(_settings(tmp_path), force_mock=True)
    assert forced is not None and forced.provider_name == "mock"


def test_image_cost_per_model() -> None:
    eur = costs.estimate_cost_eur("gemini", "gemini-3.1-flash-lite-image", n_images=1)
    assert eur == pytest.approx(0.0336 * costs.USD_TO_EUR, abs=1e-6)
    assert costs.estimate_cost_eur("gemini", "gemini-3.1-flash-image", n_images=2) == pytest.approx(
        2 * 0.067 * costs.USD_TO_EUR, abs=1e-6
    )
    assert costs.estimate_cost_eur("gemini", "gemini-3-pro-image-preview", n_images=1) == pytest.approx(
        0.134 * costs.USD_TO_EUR, abs=1e-6
    )
    assert costs.estimate_cost_eur("mock", "mock-image", n_images=1) == 0.0
    assert costs.estimate_image_cost_eur("sdxl_turbo", 4) == 0.0
