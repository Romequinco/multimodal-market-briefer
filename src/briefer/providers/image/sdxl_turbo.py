"""Texto a imagen **local y gratuito** (Hugging Face ``diffusers``) para la portada del episodio.

Carril C (opcional, ``BRIEFER_IMAGE_GEN_PROVIDER=local``; ``sdxl_turbo`` es el nombre histórico
y sigue valiendo). Implementa ``ImageGenProvider.generate(prompt, out_path) -> Path``.
Inspirado en el **notebook 4 de clase (Stable Diffusion con diffusers)**:
``AutoPipelineForText2Image`` con un modelo destilado de pocos pasos, para que corra en **CPU**.

Elección del modelo por defecto (``BRIEFER_SDXL_MODEL``), comparada el 06-oct-2026 en el PC del
equipo (Windows, 12 hilos, sin GPU, torch 2.14 CPU, diffusers 0.41):

- ``IDKiro/sdxs-512-dreamshaper`` (**por defecto**): SDXS, destilado a **1 paso** de Dreamshaper 8
  (SD 1.5) con VAE *tiny* (TAESD). Licencia **CreativeML OpenRAIL++**
  (https://huggingface.co/IDKiro/sdxs-512-dreamshaper): **permite uso comercial** con las
  restricciones de uso de la familia OpenRAIL (sin usos dañinos). Descarga ≈ 1,8 GB (UNet 1,26 GB +
  CLIP 0,49 GB + VAE 10 MB). Medido el 06-oct-2026 (CPU, 768x432, 1 paso): import de
  torch/diffusers ≈ 35 s en frío, carga 1-5 s (caché de disco caliente; 15-57 s en frío), generación
  **4-7 s** por portada (36 s la primera, en frío). Sin texto ni personas en las pruebas.
- ``SimianLuo/LCM_Dreamshaper_v7`` (alternativa por config): LCM de Dreamshaper v7, 4 pasos,
  licencia **MIT** en su *model card*, pero ≈ 4,3 GB (UNet fp32 de 3,4 GB) y más lenta; no medida
  (la red no dio para descargarla).
- ``stabilityai/sd-turbo`` (alternativa por config): ADD de SD 2.1, 1-4 pasos, descarga ≈ 2,6 GB
  (variante fp16). Licencia **Stability AI Community License**
  (https://huggingface.co/stabilityai/sd-turbo): comercial solo con registro en Stability, por
  debajo de 1 M$ de ingresos anuales y mostrando «Powered by Stability AI». Descartada como
  valor por defecto por la licencia (somos una startup); no medida.
- ``stabilityai/sdxl-turbo``: misma licencia, ≈ 7 GB (fp16) y demasiado lento en CPU.

Detalles:

- Carga **perezosa y una sola vez por proceso** (con *lock*: Streamlit atiende cada sesión en su
  hilo). float32 en CPU, float16 en CUDA. Se intenta la variante ``fp16`` de los pesos (descarga
  la mitad) y, si el repo no la tiene, los pesos normales.
- Pasos y *guidance* según la familia del modelo (``preset_for``); ``BRIEFER_SDXL_STEPS`` > 0 fuerza
  los pasos. Lienzo nativo 768x432 (16:9, múltiplo de 8); si el modelo devuelve otra proporción,
  Pillow recorta al centro a 16:9.
- Semilla fija derivada del prompt: el mismo día y sentimiento dan la misma portada.
- El prompt de CLIP se corta en 77 *tokens*: lo que pase de ahí se ignora (``diffusers`` avisa).
  El de Gemini (``media.cover.build_cover_prompt``, ~174 tokens) pierde el matiz del día y la
  paleta: para este proveedor conviene un prompt corto (``build_cover_prompt_local``).
  Con *guidance* 0 (turbo) o LCM el ``negative_prompt`` no tiene efecto; solo se pasa si el
  modelo usa CFG clásico (``NEGATIVE_PROMPT``).
- Sin ``torch``/``diffusers``: ``ImportError`` claro remitiendo a ``requirements-local.txt`` (el
  registry cae al mock si ``BRIEFER_FALLBACK_TO_MOCK=true``; el pipeline trata la portada como
  paso opcional). Coste: 0 € (solo CPU y tiempo).
"""

from __future__ import annotations

import hashlib
import importlib.util
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from briefer.config import Settings
from briefer.logging_utils import get_logger
from briefer.providers.base import ImageGenProvider

log = get_logger("providers.image.local")

#: Lienzo nativo (16:9, múltiplo de 8). ``media.cover`` lo amplía a 1024 px de ancho.
WIDTH, HEIGHT = 768, 432
ASPECT = 16 / 9

#: Solo se usa con modelos de CFG clásico (guidance > 1 y no LCM/turbo).
NEGATIVE_PROMPT = (
    "text, letters, words, numbers, watermark, logo, signature, people, faces, person, "
    "blurry, lowres, deformed, jpeg artifacts"
)


@dataclass(frozen=True)
class Preset:
    """Parámetros de inferencia de una familia de modelos."""

    steps: int
    guidance: float
    negative: bool  # ¿el modelo usa CFG clásico (y por tanto negative_prompt)?


def preset_for(model: str) -> Preset:
    """Pasos/guidance recomendados según el nombre del modelo."""
    name = model.lower()
    if "sdxs" in name:
        # SDXS: un solo paso, sin CFG (destilación a 1 paso con VAE tiny).
        return Preset(steps=1, guidance=0.0, negative=False)
    if "lcm" in name:
        # LCM: el guidance va embebido (w-embedding), no duplica el cómputo ni usa negativo.
        return Preset(steps=4, guidance=8.0, negative=False)
    if "turbo" in name:
        # ADD (sd-turbo / sdxl-turbo): sin CFG.
        return Preset(steps=2, guidance=0.0, negative=False)
    return Preset(steps=20, guidance=7.0, negative=True)  # SD clásico: lento en CPU


def diffusers_available() -> bool:
    """``True`` si ``torch`` y ``diffusers`` están instalados (no descarga nada)."""
    return all(importlib.util.find_spec(m) is not None for m in ("torch", "diffusers"))


def resolve_device(setting: str) -> str:
    """``auto`` -> ``cuda`` si hay GPU NVIDIA, si no ``cpu``; el resto tal cual."""
    if setting != "auto":
        return setting
    import torch

    return "cuda" if torch.cuda.is_available() else "cpu"


def seed_for(prompt: str) -> int:
    """Semilla estable (32 bits) a partir del prompt."""
    return int.from_bytes(hashlib.sha256(prompt.encode("utf-8")).digest()[:4], "big")


def crop_to_aspect(image: Any, aspect: float = ASPECT) -> Any:
    """Recorte centrado a la proporción ``aspect`` (ancho/alto) con Pillow."""
    w, h = image.size
    if not w or not h or abs(w / h - aspect) < 0.01:
        return image
    if w / h > aspect:  # demasiado ancha
        new_w = round(h * aspect)
        left = (w - new_w) // 2
        return image.crop((left, 0, left + new_w, h))
    new_h = round(w / aspect)
    top = (h - new_h) // 2
    return image.crop((0, top, w, top + new_h))


# Pipelines cargados por proceso: {(modelo, dispositivo): pipeline}.
_pipes: dict[tuple[str, str], Any] = {}
_pipes_lock = threading.Lock()
# Una inferencia a la vez por proceso: en CPU dos en paralelo solo se pisan los hilos.
_infer_lock = threading.Lock()


def _load_pipeline(model: str, device: str) -> Any:
    """Descarga (la primera vez) y carga el pipeline una sola vez por proceso."""
    key = (model, device)
    with _pipes_lock:
        if key in _pipes:
            return _pipes[key]
        if not diffusers_available():
            raise ImportError(
                "La portada local necesita torch y diffusers: pip install -r requirements-local.txt "
                "(o BRIEFER_IMAGE_GEN_PROVIDER=none)"
            )
        import torch
        from diffusers import AutoPipelineForText2Image

        dtype = torch.float16 if device == "cuda" else torch.float32
        kwargs: dict[str, Any] = {
            "torch_dtype": dtype,
            "safety_checker": None,  # prompt fijo de marca; evita 1,2 GB y falsos positivos en negro
            "requires_safety_checker": False,
        }
        start = time.perf_counter()
        try:
            pipe = AutoPipelineForText2Image.from_pretrained(model, variant="fp16", **kwargs)
        except (OSError, ValueError):  # el repo no publica variante fp16
            pipe = AutoPipelineForText2Image.from_pretrained(model, **kwargs)
        pipe = pipe.to(device)
        pipe.set_progress_bar_config(disable=True)
        _pipes[key] = pipe
        log.info("Modelo de imagen %s cargado en %s en %.1f s", model, device, time.perf_counter() - start)
        return pipe


class SDXLTurbo(ImageGenProvider):
    """Portada con un modelo abierto de Hugging Face, en local (CPU o GPU), 0 €."""

    provider_name = "sdxl_turbo"

    def __init__(self, settings: Settings, pipeline: Any = None) -> None:
        self.settings = settings
        self.model = settings.briefer_sdxl_model
        self.preset = preset_for(self.model)
        steps = int(getattr(settings, "briefer_sdxl_steps", 0) or 0)
        self.steps = steps if steps > 0 else self.preset.steps
        self._pipe = pipeline  # inyectable en tests (sin descarga)
        self._device = "cpu" if pipeline is not None else None
        self.last_timings: dict[str, float] = {}

    def _get_pipe(self) -> Any:
        if self._pipe is None:
            self._device = resolve_device(self.settings.briefer_local_device)
            if self._device == "cpu":
                log.info("Portada local en CPU: la primera vez descarga el modelo (varios GB)")
            self._pipe = _load_pipeline(self.model, self._device)
        return self._pipe

    def _generator(self, prompt: str) -> Any:
        try:
            import torch
        except ImportError:  # pipeline falso de tests sin torch
            return None
        return torch.Generator(device="cpu").manual_seed(seed_for(prompt))

    def generate(self, prompt: str, out_path: Path) -> Path:
        """Genera la imagen de ``prompt`` y la guarda como PNG 16:9 en ``out_path`` (.png)."""
        if not prompt or not prompt.strip():
            raise ValueError("SDXLTurbo.generate: el prompt está vacío")
        start = time.perf_counter()
        pipe = self._get_pipe()
        loaded = time.perf_counter()
        call: dict[str, Any] = {
            "prompt": prompt,
            "num_inference_steps": self.steps,
            "guidance_scale": self.preset.guidance,
            "width": WIDTH,
            "height": HEIGHT,
        }
        if self.preset.negative:
            call["negative_prompt"] = NEGATIVE_PROMPT
        generator = self._generator(prompt)
        if generator is not None:
            call["generator"] = generator
        with _infer_lock:
            result = pipe(**call)
        images = getattr(result, "images", None) or []
        if not images:
            raise RuntimeError(f"El modelo local {self.model} no devolvió ninguna imagen")
        image = crop_to_aspect(images[0].convert("RGB"))

        out = Path(out_path).with_suffix(".png")
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_name(f"{out.stem}.{os.getpid()}.{threading.get_ident()}.part")
        try:
            image.save(tmp, format="PNG")
            os.replace(tmp, out)
        finally:
            tmp.unlink(missing_ok=True)
        end = time.perf_counter()
        self.last_timings = {"load_s": loaded - start, "generate_s": end - loaded}
        log.info(
            "Portada local con %s (%d pasos, %dx%d) en %.1f s",
            self.model, self.steps, image.width, image.height, end - loaded,
        )
        return out


#: Alias con nombre más claro (el registry registra ``local`` -> esta misma clase).
LocalImageGen = SDXLTurbo

__all__ = [
    "HEIGHT",
    "NEGATIVE_PROMPT",
    "WIDTH",
    "LocalImageGen",
    "Preset",
    "SDXLTurbo",
    "crop_to_aspect",
    "diffusers_available",
    "preset_for",
    "resolve_device",
    "seed_for",
]
