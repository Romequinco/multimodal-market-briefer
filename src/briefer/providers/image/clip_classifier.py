"""Clasificación zero-shot de imágenes con CLIP (o SigLIP) para enrutar capturas subidas.

Carril A (opcional). Implementa ``ImageClassifier.classify(image, labels) -> dict``.
Inspirado en el **notebook 2 de clase (jugando con CLIP)**: similitud imagen-texto con
``CLIPModel``/``CLIPProcessor`` y softmax sobre ``logits_per_image``.
Uso en ``ingest.chart_reader``: decidir si la imagen es "gráfico de velas", "gráfico de
líneas", "tabla financiera" u "otra cosa" antes de llamar al modelo de visión (más caro).
Modelo: ``BRIEFER_CLIP_MODEL``.
"""

from __future__ import annotations

from briefer.config import Settings
from briefer.providers.base import ImageClassifier


class CLIPClassifier(ImageClassifier):
    """CLIP zero-shot en local."""

    provider_name = "clip"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.model = settings.briefer_clip_model
        self._model = None
        self._processor = None

    def classify(self, image: bytes, labels: list[str]) -> dict[str, float]:
        """Probabilidad de cada etiqueta (softmax)."""
        # TODO:
        # 1. from transformers import CLIPModel, CLIPProcessor; from PIL import Image (perezoso).
        # 2. Cargar una vez (cachear en self._model / self._processor).
        # 3. Prompts: plantilla en inglés suele ir mejor ("a screenshot of a {label}");
        #    mantener el mapeo a la etiqueta original en español.
        # 4. inputs = processor(text=prompts, images=pil, return_tensors="pt", padding=True);
        #    probs = model(**inputs).logits_per_image.softmax(dim=1)[0].tolist().
        # 5. return dict(zip(labels, probs)).
        # Casos borde: labels vacío -> {}; imagen con canal alfa -> convertir a RGB.
        raise NotImplementedError("CLIPClassifier.classify: pendiente (carril A, opcional)")
