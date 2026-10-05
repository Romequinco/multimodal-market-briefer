"""Lectura de capturas de gráficos (velas, líneas, tablas) con un modelo de visión.

Carril A. Entrada: bytes de una imagen subida. Salida: ``DocumentInsight(source_type="chart")``.
Cadena de modelos: (opcional) CLIP zero-shot para clasificar/enrutar (notebook 2) ->
VLM (Claude visión o Qwen2.5-VL local, notebook 3) para describir y extraer cifras.
"""

from __future__ import annotations

from briefer.providers.base import ImageClassifier, LLMProvider, VisionProvider
from briefer.schemas import DocumentInsight

# Etiquetas para el clasificador zero-shot.
CHART_LABELS: list[str] = [
    "gráfico de velas japonesas",
    "gráfico de líneas de cotización",
    "tabla de datos financieros",
    "otra imagen que no es financiera",
]

CHART_PROMPT = (
    "Eres analista financiero. Describe este gráfico en español: activo (si se ve), periodo, "
    "tendencia, máximos/mínimos, niveles relevantes y cualquier cifra legible. "
    "Si no es un gráfico financiero, dilo explícitamente."
)


def classify_image(image: bytes, classifier: ImageClassifier) -> tuple[str, float]:
    """Etiqueta más probable de ``CHART_LABELS`` y su probabilidad."""
    # TODO: probs = classifier.classify(image, CHART_LABELS); max(probs.items(), key=...).
    raise NotImplementedError("classify_image: pendiente (carril A, opcional)")


def read_chart(
    image: bytes,
    source_name: str,
    vision: VisionProvider,
    llm: LLMProvider | None = None,
    classifier: ImageClassifier | None = None,
) -> DocumentInsight:
    """Interpreta una captura de gráfico y devuelve un ``DocumentInsight``."""
    # TODO:
    # 1. Si hay classifier: label, p = classify_image(...); si es "otra imagen" con p > 0.6,
    #    devolver un DocumentInsight indicando que no parece un gráfico (sin llamar a visión).
    # 2. description = vision.describe(image, CHART_PROMPT (+ pista de la etiqueta)).
    # 3. Si hay llm: estructurar description en key_figures + summary
    #    (response_model=DocumentInsight); si no, key_figures={} y summary=primera frase.
    # Casos borde: imagen corrupta / formato no soportado (HEIC) -> ValueError para la UI.
    raise NotImplementedError("read_chart: pendiente (carril A)")
