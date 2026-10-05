"""Lectura de PDFs de resultados: texto con ``pypdf`` + visión en páginas con gráficos/tablas.

Carril A. Entrada: ruta a un PDF subido. Salida: ``DocumentInsight(source_type="pdf")`` con
texto extraído, cifras clave (``key_figures``: "Ingresos" -> "12.345 M€"…) y resumen.
Encadena dos modelos especializados: extracción de texto (pypdf) + VLM para lo visual
(``VisionProvider``) + LLM para resumir y extraer cifras (``LLMProvider``).
"""

from __future__ import annotations

from pathlib import Path

from briefer.providers.base import LLMProvider, VisionProvider
from briefer.schemas import DocumentInsight


def extract_page_texts(path: Path, max_pages: int = 30) -> list[str]:
    """Texto de cada página (lista indexada por página)."""
    # TODO: from pypdf import PdfReader; [p.extract_text() or "" for p in reader.pages[:max_pages]].
    # Casos borde: PDF cifrado (reader.is_encrypted -> intentar decrypt("") o error claro);
    # PDF escaneado sin capa de texto (todas las páginas vacías -> todas a visión).
    raise NotImplementedError("extract_page_texts: pendiente (carril A)")


def pages_needing_vision(page_texts: list[str], min_chars: int = 200) -> list[int]:
    """Índices de páginas con poco texto (probablemente gráficos/tablas) a enviar a visión."""
    # TODO: heurística: len(texto) < min_chars o muchas cifras sueltas; limitar a 5 páginas
    # para controlar coste/latencia.
    raise NotImplementedError("pages_needing_vision: pendiente (carril A)")


def page_images(path: Path, page_index: int) -> list[bytes]:
    """Imágenes embebidas en una página (PNG/JPEG en bytes)."""
    # TODO: pypdf no renderiza páginas; usar reader.pages[i].images -> img.data.
    # Alternativa para renderizar la página completa: pypdfium2 (añadir a requirements si
    # se usa) -> page.render(scale=2).to_pil().
    raise NotImplementedError("page_images: pendiente (carril A)")


def read_pdf(
    path: Path,
    llm: LLMProvider,
    vision: VisionProvider | None = None,
    max_pages: int = 30,
) -> DocumentInsight:
    """Procesa un PDF completo y devuelve un ``DocumentInsight``."""
    # TODO:
    # 1. texts = extract_page_texts(path, max_pages).
    # 2. Si hay vision: para i in pages_needing_vision(texts): describir page_images(path, i)
    #    con un prompt tipo "Extrae las cifras clave de este gráfico/tabla financiera".
    # 3. Unir texto + descripciones (recortar a ~30k caracteres) y pedir al LLM un
    #    DocumentInsight (response_model=DocumentInsight) con source_type="pdf",
    #    source_name=path.name, key_figures y summary en español.
    # 4. Forzar source_type/source_name tras la respuesta (no fiarse del LLM).
    raise NotImplementedError("read_pdf: pendiente (carril A)")
