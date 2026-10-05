"""Texto a imagen con SDXL-Turbo (``diffusers``) para la portada del episodio.

Carril C (opcional). Implementa ``ImageGenProvider.generate(prompt, out_path) -> Path``.
Inspirado en el **notebook 4 de clase (generación de imágenes con Stable Diffusion)**:
``AutoPipelineForText2Image`` con ``stabilityai/sdxl-turbo``, 1-4 pasos y
``guidance_scale=0.0``. Requiere ``requirements-local.txt`` y GPU recomendable.
Modelo: ``BRIEFER_SDXL_MODEL``.
"""

from __future__ import annotations

from pathlib import Path

from briefer.config import Settings
from briefer.providers.base import ImageGenProvider


class SDXLTurbo(ImageGenProvider):
    """Generación rápida (1 paso) de una portada 512x512."""

    provider_name = "sdxl_turbo"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.model = settings.briefer_sdxl_model
        self._pipe = None

    def generate(self, prompt: str, out_path: Path) -> Path:
        """Genera la imagen y la guarda como PNG."""
        # TODO:
        # 1. import torch; from diffusers import AutoPipelineForText2Image (perezoso).
        # 2. self._pipe = AutoPipelineForText2Image.from_pretrained(self.model,
        #    torch_dtype=torch.float16, variant="fp16").to("cuda") (float32 + "cpu" sin GPU).
        # 3. image = self._pipe(prompt=prompt, num_inference_steps=1, guidance_scale=0.0).images[0]
        # 4. image.save(out_path.with_suffix(".png")).
        # Casos borde: sin GPU tarda mucho -> registrar aviso; el modelo genera texto ilegible,
        # así que el prompt NO debe pedir letras/cifras (los títulos se superponen después).
        raise NotImplementedError("SDXLTurbo.generate: pendiente (carril C, opcional)")
