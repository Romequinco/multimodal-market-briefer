"""Clasificación zero-shot de imágenes con CLIP para enrutar capturas subidas.

Carril A (opcional, ``BRIEFER_IMAGE_CLASSIFIER_PROVIDER=clip``). Implementa
``ImageClassifier.classify(image, labels) -> dict``. Inspirado en el **notebook 2 de clase
(jugando con CLIP)**: similitud coseno imagen-texto y softmax, como ``logits_per_image``.

Mejoras sobre el notebook:

- **Plantillas en inglés por etiqueta** (``LABEL_PROMPTS``): CLIP se entrenó con textos en inglés,
  así que cada etiqueta en español se describe con varias frases en inglés y se **promedian sus
  embeddings** (*prompt ensembling*, como en el artículo de CLIP). Una etiqueta sin plantillas usa
  ``GENERIC_TEMPLATES`` con el texto tal cual.
- Los embeddings de texto se calculan una vez por juego de etiquetas y se reutilizan.
- Modelo y procesador se cargan **una sola vez por proceso** (perezoso, con *lock*: Streamlit
  atiende cada sesión en su hilo), en CPU. Patrón de ``ingest.sentiment`` (FinBERT).

Uso en ``ingest.chart_reader``: decidir si la imagen es un gráfico, una tabla, una captura de
cartera o algo no financiero **antes** de llamar al modelo de visión (más caro).
Modelo: ``BRIEFER_CLIP_MODEL`` (por defecto ``openai/clip-vit-base-patch32``, ~600 MB que se
descargan la primera vez a la caché de Hugging Face). Requiere ``torch`` + ``transformers``
(``requirements-local.txt``); sin ellos ``classify`` lanza ``ImportError`` con un mensaje claro y
``chart_reader`` sigue sin clasificar.
"""

from __future__ import annotations

import importlib.util
import io
import threading
import time
from typing import Any

from briefer.config import Settings
from briefer.logging_utils import get_logger
from briefer.providers.base import ImageClassifier

log = get_logger("providers.clip")

#: Plantillas genéricas para etiquetas sin descripción propia (``{}`` = la etiqueta).
GENERIC_TEMPLATES: tuple[str, ...] = ("a photo of {}.", "a screenshot of {}.", "an image of {}.")

#: Frases en inglés por etiqueta (claves = ``chart_reader.CHART_LABELS``; un test lo comprueba).
#: Se promedian los embeddings de cada grupo. Ajustadas con ``tests/fixtures/images``.
LABEL_PROMPTS: dict[str, tuple[str, ...]] = {
    "gráfico de velas japonesas": (
        "a candlestick chart of a stock price.",
        "a screenshot of a trading platform with a candlestick chart and volume bars.",
        "a financial chart with green and red candlesticks.",
    ),
    "gráfico de líneas de cotización": (
        "a line chart of a stock price over time.",
        "a graph of a share price with dates on the x axis.",
        "a financial line chart of a market index.",
    ),
    "tabla de datos financieros": (
        "a table of financial figures with rows and columns of numbers.",
        "an income statement table from an annual report.",
        "a spreadsheet with financial data.",
    ),
    "captura de cartera o posiciones de un bróker": (
        "a screenshot of a brokerage app showing a portfolio of stock positions.",
        "a mobile app screen listing stock holdings with their value and percentage change.",
        "a screenshot of an investment account with a list of shares and gains and losses.",
    ),
    "fotografía u otra imagen no financiera": (
        "a photo.",
        "a photograph of a landscape, people, animals, food or objects.",
        "a selfie.",
    ),
    "meme, dibujo o ilustración": (
        "a meme.",
        "a cartoon drawing or illustration.",
        "a painting or digital artwork.",
    ),
    "documento o texto no financiero": (
        "a scanned page of a text document.",
        "a screenshot of a chat conversation.",
        "a page of a letter or an essay.",
    ),
}


def clip_available() -> bool:
    """``True`` si ``transformers`` y ``torch`` están instalados (no descarga nada)."""
    return all(importlib.util.find_spec(m) is not None for m in ("transformers", "torch"))


# Modelos cargados por proceso: {nombre_modelo: (modelo, procesador)}.
_models: dict[str, tuple[Any, Any]] = {}
_models_lock = threading.Lock()


def _load(model_name: str) -> tuple[Any, Any]:
    """Carga CLIP una sola vez por proceso (CPU, modo evaluación)."""
    with _models_lock:
        if model_name not in _models:
            if not clip_available():
                raise ImportError(
                    "CLIP necesita torch y transformers: pip install -r requirements-local.txt "
                    "(o BRIEFER_IMAGE_CLASSIFIER_PROVIDER=none)"
                )
            from transformers import CLIPModel, CLIPProcessor

            start = time.perf_counter()
            model = CLIPModel.from_pretrained(model_name).eval()
            processor = CLIPProcessor.from_pretrained(model_name)
            _models[model_name] = (model, processor)
            log.info("CLIP %s cargado en %.1f s", model_name, time.perf_counter() - start)
        return _models[model_name]


def _features(out: Any) -> Any:
    """Tensor de embeddings (``transformers`` 5 devuelve un objeto con ``pooler_output``)."""
    return getattr(out, "pooler_output", out)


def prompts_for(label: str) -> tuple[str, ...]:
    """Frases en inglés que describen ``label`` (las de ``LABEL_PROMPTS`` o las genéricas)."""
    return LABEL_PROMPTS.get(label) or tuple(t.format(label) for t in GENERIC_TEMPLATES)


class CLIPClassifier(ImageClassifier):
    """CLIP zero-shot en local (CPU)."""

    provider_name = "clip"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.model = settings.briefer_clip_model
        self._text_cache: dict[tuple[str, ...], Any] = {}
        self._cache_lock = threading.Lock()

    def _text_embeddings(self, labels: tuple[str, ...]) -> Any:
        """Matriz ``[n_etiquetas, d]`` normalizada: media de los embeddings de sus plantillas."""
        with self._cache_lock:
            cached = self._text_cache.get(labels)
        if cached is not None:
            return cached
        model, processor = _load(self.model)
        import torch

        prompts = [p for label in labels for p in prompts_for(label)]
        sizes = [len(prompts_for(label)) for label in labels]
        with torch.no_grad():
            inputs = processor(text=prompts, return_tensors="pt", padding=True)
            emb = _features(model.get_text_features(**inputs))
        emb = emb / emb.norm(dim=-1, keepdim=True)
        rows = [chunk.mean(dim=0) for chunk in torch.split(emb, sizes)]
        text = torch.stack(rows)
        text = text / text.norm(dim=-1, keepdim=True)
        with self._cache_lock:
            self._text_cache[labels] = text
        return text

    def classify(self, image: bytes, labels: list[str]) -> dict[str, float]:
        """Probabilidad de cada etiqueta (softmax sobre la similitud imagen-texto).

        Raises:
            ImportError: faltan ``torch``/``transformers``.
            ValueError: la imagen no se puede abrir.
        """
        if not labels:
            return {}
        model, processor = _load(self.model)  # primero: error claro si faltan dependencias
        import torch
        from PIL import Image, UnidentifiedImageError

        try:
            with Image.open(io.BytesIO(image)) as img:
                pil = img.convert("RGB")  # quita el canal alfa / paleta
        except (UnidentifiedImageError, OSError) as exc:
            raise ValueError("CLIP no puede abrir la imagen") from exc

        keys = tuple(labels)
        text = self._text_embeddings(keys)
        with torch.no_grad():
            pixels = processor(images=pil, return_tensors="pt")
            img_emb = _features(model.get_image_features(**pixels))
            img_emb = img_emb / img_emb.norm(dim=-1, keepdim=True)
            logits = model.logit_scale.exp() * img_emb @ text.T
            probs = logits.softmax(dim=-1)[0].tolist()
        return {label: float(p) for label, p in zip(keys, probs, strict=True)}
