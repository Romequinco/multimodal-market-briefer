"""Portada local con diffusers (sin red): pipeline falso, presets, errores sin dependencias y registry.

El modelo real (descarga ~1,8 GB, ~4-7 s por imagen en CPU) solo se prueba con ``-m live``.
"""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from briefer import costs
from briefer.config import Settings
from briefer.media import cover
from briefer.providers import registry
from briefer.providers.image import sdxl_turbo
from briefer.providers.image.sdxl_turbo import SDXLTurbo


def _settings(tmp_path: Path, **kw) -> Settings:
    base = {
        "_env_file": None,
        "briefer_image_gen_provider": "local",
        "briefer_output_dir": tmp_path / "outputs",
        "briefer_cache_dir": tmp_path / "cache",
    }
    base.update(kw)
    return Settings(**base)


class FakePipe:
    """Doble de un pipeline de diffusers: anota la llamada y devuelve una imagen lisa."""

    def __init__(self, size: tuple[int, int] = (768, 432), empty: bool = False) -> None:
        self.size = size
        self.empty = empty
        self.calls: list[dict] = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        images = [] if self.empty else [Image.new("RGB", self.size, (18, 21, 27))]
        return SimpleNamespace(images=images)


def test_default_model_is_permissive_lcm(tmp_path: Path) -> None:
    s = _settings(tmp_path)
    assert s.briefer_sdxl_model == "IDKiro/sdxs-512-dreamshaper"
    assert s.briefer_sdxl_steps == 0


def test_presets_by_model_family() -> None:
    sdxs = sdxl_turbo.preset_for("IDKiro/sdxs-512-dreamshaper")
    assert (sdxs.steps, sdxs.guidance, sdxs.negative) == (1, 0.0, False)
    lcm = sdxl_turbo.preset_for("SimianLuo/LCM_Dreamshaper_v7")
    assert (lcm.steps, lcm.guidance, lcm.negative) == (4, 8.0, False)
    turbo = sdxl_turbo.preset_for("stabilityai/sd-turbo")
    assert (turbo.steps, turbo.guidance, turbo.negative) == (2, 0.0, False)
    classic = sdxl_turbo.preset_for("runwayml/stable-diffusion-v1-5")
    assert classic.negative and classic.guidance > 1


def test_generate_with_fake_pipeline_saves_png(tmp_path: Path) -> None:
    pipe = FakePipe()
    gen = SDXLTurbo(_settings(tmp_path), pipeline=pipe)
    out = gen.generate("a quiet city at night", tmp_path / "sub" / "cover.jpg")
    assert out == tmp_path / "sub" / "cover.png" and out.exists()
    with Image.open(out) as img:
        assert img.format == "PNG" and img.size == (768, 432)
    call = pipe.calls[0]
    assert call["num_inference_steps"] == 1 and call["guidance_scale"] == 0.0
    assert (call["width"], call["height"]) == (sdxl_turbo.WIDTH, sdxl_turbo.HEIGHT)
    assert "negative_prompt" not in call  # SDXS no usa CFG clásico
    assert not list(out.parent.glob("*.part"))
    assert set(gen.last_timings) == {"load_s", "generate_s"}


def test_steps_override_and_negative_prompt_for_classic_models(tmp_path: Path) -> None:
    pipe = FakePipe()
    s = _settings(tmp_path, briefer_sdxl_model="some/stable-diffusion", briefer_sdxl_steps=3)
    SDXLTurbo(s, pipeline=pipe).generate("p", tmp_path / "c.png")
    assert pipe.calls[0]["num_inference_steps"] == 3
    assert pipe.calls[0]["negative_prompt"] == sdxl_turbo.NEGATIVE_PROMPT


def test_same_prompt_same_seed() -> None:
    assert sdxl_turbo.seed_for("abc") == sdxl_turbo.seed_for("abc")
    assert sdxl_turbo.seed_for("abc") != sdxl_turbo.seed_for("abd")


@pytest.mark.parametrize("size", [(512, 512), (1024, 400), (768, 432)])
def test_output_is_cropped_to_16_9(tmp_path: Path, size: tuple[int, int]) -> None:
    gen = SDXLTurbo(_settings(tmp_path), pipeline=FakePipe(size=size))
    out = gen.generate("p", tmp_path / "c.png")
    with Image.open(out) as img:
        assert abs(img.width / img.height - 16 / 9) < 0.01


def test_empty_prompt_and_empty_result(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        SDXLTurbo(_settings(tmp_path), pipeline=FakePipe()).generate("  ", tmp_path / "c.png")
    with pytest.raises(RuntimeError, match="ninguna imagen"):
        SDXLTurbo(_settings(tmp_path), pipeline=FakePipe(empty=True)).generate("p", tmp_path / "c.png")


def test_missing_diffusers_raises_clear_import_error(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(sdxl_turbo, "diffusers_available", lambda: False)
    monkeypatch.setattr(sdxl_turbo, "resolve_device", lambda setting: "cpu")
    gen = SDXLTurbo(_settings(tmp_path, briefer_sdxl_model="not/downloaded-model"))
    with pytest.raises(ImportError, match="requirements-local.txt"):
        gen.generate("p", tmp_path / "c.png")


def test_make_cover_with_local_provider(tmp_path: Path) -> None:
    from briefer import storage

    briefing = storage.load_demo_briefing()
    assert briefing is not None
    gen = SDXLTurbo(_settings(tmp_path), pipeline=FakePipe())
    path = cover.make_cover(briefing.analysis, gen, tmp_path / "out")
    assert path is not None and path.name == "cover.png"
    with Image.open(path) as img:
        assert img.width >= cover.MIN_WIDTH


def test_registry_local_alias_and_legacy_name(tmp_path: Path) -> None:
    for name in ("local", "sdxl_turbo"):
        gen = registry.get_image_gen(_settings(tmp_path, briefer_image_gen_provider=name))
        assert isinstance(gen, SDXLTurbo)
        assert gen.provider_name == "sdxl_turbo"  # nombre estable para trazas y costes
        assert gen.model == "IDKiro/sdxs-512-dreamshaper"
    assert sdxl_turbo.LocalImageGen is SDXLTurbo


def test_local_cover_costs_nothing() -> None:
    assert costs.estimate_cost_eur("sdxl_turbo", "IDKiro/sdxs-512-dreamshaper", n_images=1) == 0.0
    assert costs.estimate_image_cost_eur("sdxl_turbo", 3) == 0.0


@pytest.mark.live
def test_live_local_cover(tmp_path: Path) -> None:
    """Modelo real (descarga ~1,8 GB la primera vez; sin coste). ``python -m pytest -m live``."""
    pytest.importorskip("diffusers")
    pytest.importorskip("torch")
    from briefer import storage

    briefing = storage.load_demo_briefing()
    assert briefing is not None
    model = os.environ.get("BRIEFER_SDXL_MODEL", "IDKiro/sdxs-512-dreamshaper")
    gen = SDXLTurbo(_settings(tmp_path, briefer_sdxl_model=model))
    path = cover.make_cover(briefing.analysis, gen, tmp_path)
    assert path is not None and path.exists()
    assert gen.last_timings["generate_s"] < 120
