"""Lectura de PDFs de resultados: texto con ``pypdf`` + visión en páginas con gráficos/tablas.

Carril A. Entrada: ruta a un PDF subido. Salida: ``DocumentInsight(source_type="pdf")`` con
texto extraído, cifras clave (``key_figures``: "Ingresos" -> "12.345 M€"…) y resumen.
Encadena dos modelos especializados: extracción de texto (pypdf) + VLM para lo visual
(``VisionProvider``) + LLM para resumir y extraer cifras (``LLMProvider``).

Limitación conocida: ``pypdf`` no renderiza páginas, solo extrae imágenes embebidas. Un gráfico
vectorial (sin imagen raster) no llega al VLM. TODO (D2): renderizar la página completa con
``pypdfium2`` (``page.render(scale=2).to_pil()``) si se añade a ``requirements.txt``.
"""

from __future__ import annotations

from pathlib import Path

from briefer.logging_utils import get_logger
from briefer.providers.base import LLMProvider, VisionProvider
from briefer.schemas import DocumentInsight

log = get_logger("ingest.pdf")

# Máximo de páginas que se envían a visión (coste/latencia) y de caracteres que se mandan al LLM.
MAX_VISION_PAGES = 5
MAX_LLM_CHARS = 30_000
# Máximo de imágenes por página que se describen.
MAX_IMAGES_PER_PAGE = 2

PAGE_VISION_PROMPT = (
    "Eres analista financiero. Esta imagen procede de un informe de resultados. Describe en "
    "español qué muestra (gráfico, tabla…) y extrae las cifras clave legibles con sus unidades y "
    "periodos. No inventes cifras."
)

PDF_SYSTEM = (
    "Eres analista financiero. Recibes el texto de un PDF de resultados (y descripciones de sus "
    "gráficos). Devuelve un DocumentInsight en español: key_figures con las cifras clave "
    "(etiqueta -> valor con unidades y variación si aparece, máx. 10) y summary de 3-5 frases. "
    "Solo informa: sin recomendaciones de compra o venta. Si el documento indica que es ficticio "
    "o de ejemplo, dilo en el resumen."
)


def _open(path: Path):
    """Abre el PDF con ``pypdf``; intenta descifrar con contraseña vacía si está cifrado."""
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"No existe el PDF: {path}")
    try:
        reader = PdfReader(str(path))
    except (PdfReadError, OSError, ValueError) as exc:
        raise ValueError(f"No se puede leer el PDF {path.name}: fichero dañado o no es un PDF") from exc
    if reader.is_encrypted:
        try:
            ok = reader.decrypt("")
        except Exception:  # noqa: BLE001 - pypdf lanza distintos tipos según el cifrado
            ok = 0
        if not ok:
            raise ValueError(f"El PDF {path.name} está protegido con contraseña")
    return reader


def extract_page_texts(path: Path, max_pages: int = 30) -> list[str]:
    """Texto de cada página (lista indexada por página; ``""`` si la página no tiene texto).

    Raises:
        FileNotFoundError: si no existe el fichero.
        ValueError: PDF dañado o protegido con contraseña.
    """
    reader = _open(path)
    texts: list[str] = []
    for page in reader.pages[:max_pages]:
        try:
            texts.append((page.extract_text() or "").strip())
        except Exception as exc:  # noqa: BLE001 - una página rara no debe tumbar el documento
            log.warning("No se pudo extraer texto de una página de %s: %s", Path(path).name, exc)
            texts.append("")
    return texts


def pages_needing_vision(page_texts: list[str], min_chars: int = 200) -> list[int]:
    """Índices de páginas con poco texto (probablemente gráficos/tablas) a enviar a visión.

    Heurística: menos de ``min_chars`` caracteres de texto, o una página dominada por cifras
    sueltas (más del 35 % de los caracteres no blancos son dígitos: tabla volcada como texto).
    Se limita a ``MAX_VISION_PAGES`` páginas para controlar coste y latencia.
    """
    selected: list[int] = []
    for i, text in enumerate(page_texts):
        compact = "".join(text.split())
        digits = sum(c.isdigit() for c in compact)
        if len(compact) < min_chars or (compact and digits / len(compact) > 0.35):
            selected.append(i)
        if len(selected) >= MAX_VISION_PAGES:
            break
    return selected


def page_images(path: Path, page_index: int) -> list[bytes]:
    """Imágenes embebidas en una página (bytes PNG/JPEG tal como las exporta ``pypdf``).

    Devuelve ``[]`` si la página no tiene imágenes raster o no se pueden extraer.

    Raises:
        IndexError: si ``page_index`` no existe.
    """
    reader = _open(path)
    if not 0 <= page_index < len(reader.pages):
        raise IndexError(f"El PDF tiene {len(reader.pages)} páginas; no existe la página {page_index + 1}")
    try:
        return [img.data for img in reader.pages[page_index].images]
    except Exception as exc:  # noqa: BLE001 - filtros de imagen no soportados por pypdf/Pillow
        log.warning("No se pudieron extraer imágenes de la página %d: %s", page_index + 1, exc)
        return []


def read_pdf(
    path: Path,
    llm: LLMProvider,
    vision: VisionProvider | None = None,
    max_pages: int = 30,
) -> DocumentInsight:
    """Procesa un PDF completo y devuelve un ``DocumentInsight``.

    Cadena: pypdf (texto por página) -> VLM sobre las imágenes de las páginas con poco texto ->
    LLM que estructura cifras clave y resumen. ``source_type``/``source_name`` y
    ``extracted_text`` (texto real + descripciones, recortado) se fijan aquí, no los decide el LLM.

    Raises:
        FileNotFoundError, ValueError: ver ``extract_page_texts``.
    """
    path = Path(path)
    texts = extract_page_texts(path, max_pages)

    parts = [f"[Página {i + 1}]\n{t}" for i, t in enumerate(texts) if t]
    if vision is not None:
        for i in pages_needing_vision(texts):
            for n, image in enumerate(page_images(path, i)[:MAX_IMAGES_PER_PAGE], start=1):
                description = vision.describe(image, PAGE_VISION_PROMPT).strip()
                parts.append(f"[Página {i + 1} · imagen {n} (descripción por visión)]\n{description}")
    if not parts:
        raise ValueError(f"No se ha podido extraer contenido de {path.name} (¿PDF escaneado sin imágenes?)")

    content = "\n\n".join(parts)
    if len(content) > MAX_LLM_CHARS:
        content = content[:MAX_LLM_CHARS] + "\n[… recortado]"

    structured = llm.complete(
        PDF_SYSTEM,
        [{"role": "user", "content": f"Fichero: {path.name}\n\n{content}"}],
        response_model=DocumentInsight,
    )
    if not isinstance(structured, DocumentInsight):  # contrato: complete() devuelve el modelo pedido
        raise TypeError("El LLM no devolvió un DocumentInsight")
    return DocumentInsight(
        source_type="pdf",
        source_name=path.name,
        extracted_text=content,
        key_figures=dict(structured.key_figures),
        summary=structured.summary.strip(),
    )
