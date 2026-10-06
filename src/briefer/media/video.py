"""Vídeo corto del briefing: imágenes (portada + gráficos) + audio del podcast + subtítulos.

Carril C (opcional). Entrada: ``AudioAsset`` (+ ``segments``), lista de imágenes PNG (portada y
gráficos de ``media.charts``), ``Transcript`` opcional. Salida: ``VideoAsset`` MP4 vertical 9:16
(720×1280 por defecto) que dura **todo** el episodio, apto para redes y para el móvil.

Decisiones:

- Sin ``moviepy``: cada fotograma fijo se compone con **Pillow** (un PNG del tamaño del vídeo por
  imagen, en una carpeta temporal) y ffmpeg (el de ``imageio-ffmpeg``) los une con el *concat
  demuxer* y sus duraciones. Es más simple y robusto que una cadena de filtros, y rápido: imagen
  fija + ``-tune stillimage`` + ``-preset veryfast`` + fps bajo (``DEFAULT_FPS``) codifican un
  episodio de 4 min en segundos.
- Encuadre: cada imagen (apaisada, 16:9) se encaja **sin deformarla** (*letterbox*) en una tarjeta
  sobre el fondo de la paleta «Noticiero nocturno» de la UI, con el logo de Briefly arriba, el titular
  debajo y una franja inferior fija con el rótulo de voz sintética.
- Reparto del tiempo «con sentido» (``plan_slides``): la primera imagen (portada si la hay, si no el
  gráfico general) abre el vídeo; cada gráfico de un valor entra cuando el audio menciona por
  primera vez su ticker o su empresa (``image_keywords``: nombre y alias de
  ``ingest.tickers.TICKER_UNIVERSE``); las imágenes sin mención parten el tramo más largo. Sin
  ``segments`` o sin menciones, reparto uniforme.
- Subtítulos quemados (``build_ass``): un fichero ASS con el nombre del locutor en su color
  (Toro en verde, Osa en coral) sobre el texto, troceado en bloques de 2 filas como el SRT. Se usa
  la fuente DejaVu Sans que trae matplotlib (``fontsdir``), así que se ve igual en Docker. ffmpeg se
  lanza con ``cwd`` en la carpeta temporal y el ASS se referencia por nombre relativo: así se evita
  el escapado de ``C:\\`` y ``:`` de Windows dentro del filtro.
- Transparencia (AI Act art. 50): rótulo fijo «Voces sintéticas generadas con IA» en todos los
  fotogramas y metadatos del MP4 equivalentes a ``podcast.AI_AUDIO_METADATA``.
- Ficheros temporales: la carpeta de trabajo se borra siempre, también si ffmpeg falla; ffmpeg se
  lanza sin ventana de consola en Windows y con un tiempo máximo proporcional a la duración.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unicodedata
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from briefer import brand
from briefer.logging_utils import get_logger
from briefer.media.podcast import AI_AUDIO_METADATA, ffmpeg_exe
from briefer.media.transcript import default_speaker_names
from briefer.schemas import AudioAsset, AudioSegment, Transcript, VideoAsset

if TYPE_CHECKING:
    from PIL import ImageDraw, ImageFont

log = get_logger("media.video")

DEFAULT_SIZE = (720, 1280)
DEFAULT_FPS = 12
#: Duración mínima de una diapositiva cuando se alinea con el audio (s).
MIN_SLIDE_S = 3.0
#: Rótulo fijo de compliance (misma frase que el pie de Telegram).
SYNTHETIC_VOICE_LABEL = "Voces sintéticas generadas con IA"
FOOTER_NOTE = "Información, no asesoramiento financiero"
# Subtítulos: filas por bloque y caracteres por fila (a 720 px de ancho y cuerpo 36).
SUB_MAX_CHARS_PER_ROW = 32
SUB_MAX_ROWS = 2
# Tiempo máximo de ffmpeg: base + proporcional a la duración del episodio.
FFMPEG_BASE_TIMEOUT_S = 120
FFMPEG_TIMEOUT_PER_AUDIO_S = 1.0

# Paleta «Noticiero nocturno» (mismos tokens que ``app/components/theme.py``; aquí sin Streamlit).
BG = "#0E1116"
SURFACE = "#12151B"
BORDER = "#2A313B"
TEXT = "#D6DEE8"
TEXT_MUTED = "#9A9992"
ACCENT = "#C0502A"
ACCENT_SOFT = "#F0997B"
UP = "#5DCAA5"
AMBER = "#EF9F27"
#: Color del nombre de cada locutor en los subtítulos (A = Toro, el optimista; B = Osa).
SPEAKER_COLORS = {"A": UP, "B": ACCENT_SOFT}

# Franjas verticales del fotograma (fracción del alto): tarjeta de la imagen y arranque de los subtítulos.
CARD_TOP = 0.20
CARD_BOTTOM = 0.62
SUBS_TOP = 0.645
FOOTER_TOP = 0.905

FONT_FAMILY = "DejaVu Sans"
LOGO_FILE = "briefly_logo_oscuro.png"

_SUFFIXES = ("_price", "_change", "_weights")
_PREFIXES = ("price_",)


# ── Reparto del tiempo entre imágenes ──────────────────────────────────────────────


def _fold(text: str) -> str:
    """Minúsculas y sin tildes (para buscar menciones)."""
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower()


def image_keywords(path: Path) -> list[str]:
    """Palabras que, dichas en el audio, señalan el momento de mostrar ``path``.

    El ticker sale del nombre del fichero (``SAN_MC_price.png`` o ``price_SAN.MC.png`` -> ``SAN.MC``)
    y se buscan su nombre y alias en ``TICKER_UNIVERSE`` («Santander», «Banco Santander»). Los
    tickers sin sufijo de mercado (``AAPL``) también cuentan como palabra. Los gráficos generales
    (``overview_change.png``, ``portfolio_weights.png``) y la portada no tienen palabras clave.
    """
    stem = Path(path).stem
    for prefix in _PREFIXES:
        if stem.lower().startswith(prefix):
            stem = stem[len(prefix):]
    for suffix in _SUFFIXES:
        if stem.lower().endswith(suffix):
            stem = stem[: -len(suffix)]
    if not stem or stem.lower() in {"overview", "portfolio", "cover", "portada"}:
        return []
    try:
        from briefer.ingest.tickers import TICKER_UNIVERSE
        from briefer.media.charts import safe_name
    except Exception:  # pragma: no cover - el universo es opcional para el vídeo
        return []
    for ticker, info in TICKER_UNIVERSE.items():
        if stem.upper() in {ticker.upper(), safe_name(ticker).upper()}:
            words = [str(info["name"]), *list(info["aliases"])]
            root = ticker.lstrip("^")
            if "." not in root:
                words.append(root)
            return list(dict.fromkeys(w for w in words if w))
    if "." not in stem and "_" not in stem and len(stem) >= 3:
        return [stem]  # ticker fuera del universo (p. ej. ``MSFT``): se busca tal cual
    return []


def first_mention(keywords: Sequence[str], segments: Sequence[AudioSegment]) -> float | None:
    """Segundo del audio en que se dice por primera vez alguna de ``keywords`` (o ``None``).

    Dentro de un segmento, el instante se interpola por la posición del carácter en el texto.
    """
    if not keywords:
        return None
    pattern = re.compile(r"\b(" + "|".join(re.escape(_fold(k)) for k in keywords) + r")\b")
    for seg in segments:
        text = _fold(seg.text)
        match = pattern.search(text)
        if match:
            span = max(0.0, seg.end_s - seg.start_s)
            return seg.start_s + span * match.start() / max(1, len(text))
    return None


def _uniform(images: Sequence[Path], duration_s: float) -> list[tuple[Path, float]]:
    return [(Path(img), duration_s / len(images)) for img in images]


def plan_slides(
    images: Sequence[Path],
    duration_s: float,
    segments: Sequence[AudioSegment] | None = None,
    *,
    min_slide_s: float = MIN_SLIDE_S,
) -> list[tuple[Path, float]]:
    """Reparte ``duration_s`` entre ``images`` y devuelve ``[(imagen, segundos), ...]`` en orden.

    - La primera imagen abre el vídeo y cubre al menos la primera intervención (la apertura).
    - Cada imagen con palabras clave (``image_keywords``) entra en su primera mención posterior a la
      apertura, respetando ``min_slide_s`` entre cambios.
    - Las imágenes sin mención (o que no caben) parten por la mitad el tramo más largo.
    - Sin ``segments``, sin ninguna mención o con un audio demasiado corto: reparto uniforme.

    La suma de duraciones es siempre ``duration_s``. Función pura (sin E/S salvo leer el universo).
    """
    if not images or duration_s <= 0:
        return []
    if len(images) == 1:
        return [(Path(images[0]), duration_s)]
    if not segments or duration_s < len(images) * min_slide_s:
        return _uniform(images, duration_s)
    # La apertura (primera intervención: saludo y titular) es siempre de la primera imagen.
    body = list(segments[1:]) if len(segments) > 1 else list(segments)
    anchors: dict[int, float] = {}
    for idx in range(1, len(images)):
        t = first_mention(image_keywords(images[idx]), body)
        if t is not None:
            anchors[idx] = t
    if not anchors:
        return _uniform(images, duration_s)

    starts: list[tuple[float, int]] = [(0.0, 0)]
    unplaced: list[int] = []
    for idx in sorted(anchors, key=lambda i: (anchors[i], i)):
        start = max(anchors[idx], starts[-1][0] + min_slide_s)
        if start > duration_s - min_slide_s:
            unplaced.append(idx)
            continue
        starts.append((start, idx))
    unplaced.extend(i for i in range(1, len(images)) if i not in anchors)
    unplaced.sort()

    for idx in unplaced:
        ends = [s for s, _ in starts[1:]] + [duration_s]
        lengths = [end - s for (s, _), end in zip(starts, ends, strict=True)]
        longest = max(range(len(starts)), key=lambda j: lengths[j])
        mid = starts[longest][0] + lengths[longest] / 2
        starts.insert(longest + 1, (mid, idx))

    ends = [s for s, _ in starts[1:]] + [duration_s]
    return [(Path(images[idx]), end - s) for (s, idx), end in zip(starts, ends, strict=True)]


# ── Subtítulos ASS ─────────────────────────────────────────────────────────────────


def ass_timestamp(seconds: float) -> str:
    """``3.5`` -> ``"0:00:03.50"`` (formato ASS, centésimas). Los negativos se recortan a 0."""
    total_cs = int(round(max(0.0, float(seconds)) * 100))
    hours, rest = divmod(total_cs, 360_000)
    minutes, rest = divmod(rest, 6_000)
    secs, cs = divmod(rest, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{cs:02d}"


def ass_escape(text: str) -> str:
    """Texto seguro para una línea ``Dialogue`` de ASS.

    Las llaves abren bloques de estilo y la barra invertida inicia códigos (``\\N``, ``\\h``…):
    se sustituyen por equivalentes visibles. Saltos de línea y espacios repetidos se aplanan.
    """
    cleaned = text.replace("\\", "/").replace("{", "(").replace("}", ")")
    return " ".join(cleaned.split())


def _ass_color(hex_color: str) -> str:
    """``#RRGGBB`` -> ``&H00BBGGRR`` (orden de ASS, alfa 00 = opaco)."""
    h = hex_color.lstrip("#")
    return f"&H00{h[4:6]}{h[2:4]}{h[0:2]}".upper()


def _split_rows(text: str, width: int = SUB_MAX_CHARS_PER_ROW, rows: int = SUB_MAX_ROWS) -> list[list[str]]:
    wrapped = textwrap.wrap(text, width=width, break_long_words=True) or [""]
    return [wrapped[i : i + rows] for i in range(0, len(wrapped), rows)]


def build_ass(
    segments: Sequence[AudioSegment],
    size: tuple[int, int] = DEFAULT_SIZE,
    speaker_names: dict[str, str] | None = None,
) -> str:
    """Fichero ASS con un bloque por trozo de cada intervención (nombre del locutor en color encima).

    Las intervenciones largas se trocean en bloques de ``SUB_MAX_ROWS`` filas y el tiempo del
    segmento se reparte en proporción a los caracteres de cada trozo (igual que el SRT).
    """
    width, height = size
    scale = width / DEFAULT_SIZE[0]
    names = dict(default_speaker_names() if speaker_names is None else speaker_names)
    font_size = round(36 * scale)
    name_size = round(28 * scale)
    margin_v = round(height * SUBS_TOP)  # alineado arriba, justo bajo la tarjeta de la imagen
    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {width}\n"
        f"PlayResY: {height}\n"
        "WrapStyle: 2\n"
        "ScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{FONT_FAMILY},{font_size},{_ass_color(TEXT)},{_ass_color(TEXT)},"
        f"{_ass_color(BG)},&H80000000,0,0,0,0,100,100,0,0,1,{max(1, round(2 * scale))},0,8,"
        f"{round(32 * scale)},{round(32 * scale)},{margin_v},1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    events: list[str] = []
    for seg in segments:
        body = ass_escape(seg.text)
        if not body:
            continue
        name = ass_escape(names.get(seg.speaker, seg.speaker))
        color = _ass_color(SPEAKER_COLORS.get(seg.speaker, ACCENT_SOFT))
        chunks = _split_rows(body)
        weights = [max(1, sum(len(r) for r in chunk)) for chunk in chunks]
        total_w = sum(weights)
        span = max(0.0, seg.end_s - seg.start_s)
        cursor = seg.start_s
        for chunk, w in zip(chunks, weights, strict=True):
            end = cursor + span * w / total_w
            label = f"{{\\fs{name_size}\\b1\\c{color}&}}{name.upper()}{{\\r}}"
            text = label + "\\N" + "\\N".join(chunk)
            events.append(f"Dialogue: 0,{ass_timestamp(cursor)},{ass_timestamp(end)},Default,,0,0,0,,{text}")
            cursor = end
    return header + "\n".join(events) + ("\n" if events else "")


# ── Fotogramas con Pillow ──────────────────────────────────────────────────────────


def font_path(bold: bool = False) -> Path:
    """Ruta a DejaVu Sans (la que trae matplotlib; no depende de las fuentes del sistema)."""
    import matplotlib

    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    return Path(matplotlib.get_data_path()) / "fonts" / "ttf" / name


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    from PIL import ImageFont

    try:
        return ImageFont.truetype(str(font_path(bold)), size)
    except OSError:  # pragma: no cover - matplotlib sin sus fuentes
        return ImageFont.load_default()


def _draw_centered(draw: ImageDraw.ImageDraw, text: str, y: int,
                   font: ImageFont.FreeTypeFont | ImageFont.ImageFont, fill: str, width: int) -> int:
    """Dibuja ``text`` centrado en ``y``; devuelve la ``y`` del final."""
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    draw.text(((width - (right - left)) / 2 - left, y - top), text, font=font, fill=fill)
    return y + round(bottom - top)


def _compose_frame(image: Path | None, out: Path, size: tuple[int, int], title: str | None) -> Path:
    """Fotograma vertical de marca: logo, titular, imagen encajada (o portada de marca) y rótulo."""
    from PIL import Image, ImageDraw

    width, height = size
    s = width / DEFAULT_SIZE[0]
    canvas = Image.new("RGB", size, BG)
    draw = ImageDraw.Draw(canvas)
    big = image is None  # sin imágenes: logo y titular grandes en el centro

    # Cabecera: logo (o nombre de marca) y titular.
    logo_w = round(width * (0.7 if big else 0.42))
    y = round(height * (0.30 if big else 0.035))
    logo_file = brand.ASSETS_DIR / LOGO_FILE
    try:
        logo = Image.open(logo_file).convert("RGBA")
        logo = logo.resize((logo_w, round(logo.height * logo_w / logo.width)), Image.Resampling.LANCZOS)
        canvas.paste(logo, ((width - logo.width) // 2, y), logo)
        y += logo.height
    except OSError:
        y = _draw_centered(draw, brand.BRAND_NAME, y, _font(round(72 * s * (1.4 if big else 1)), True),
                           TEXT, width)
    y += round(14 * s)
    if title:
        title_font = _font(round((34 if big else 26) * s), True)
        for row in textwrap.wrap(" ".join(title.split()), width=26 if big else 38)[:3 if big else 2]:
            y = _draw_centered(draw, row, y, title_font, ACCENT_SOFT, width) + round(8 * s)
    else:
        y = _draw_centered(draw, brand.TAGLINE, y, _font(round(24 * s)), TEXT_MUTED, width)

    # Imagen encajada sin deformar en una tarjeta.
    # La tarjeta se ajusta a la imagen y se centra en su franja (entre cabecera y subtítulos).
    if image is not None:
        margin, pad = round(24 * s), round(8 * s)
        area_top = max(y + round(24 * s), round(height * CARD_TOP))
        area_bottom = round(height * CARD_BOTTOM)
        with Image.open(image) as src:
            pic = src.convert("RGBA")
        ratio = min((width - 2 * margin - 2 * pad) / pic.width, (area_bottom - area_top - 2 * pad) / pic.height)
        pic = pic.resize((max(1, round(pic.width * ratio)), max(1, round(pic.height * ratio))),
                         Image.Resampling.LANCZOS)
        card_h = pic.height + 2 * pad
        top = area_top + (area_bottom - area_top - card_h) // 2
        box = ((width - pic.width) // 2 - pad, top, (width + pic.width) // 2 + pad, top + card_h)
        draw.rounded_rectangle(box, radius=round(14 * s), fill=SURFACE, outline=BORDER, width=max(1, round(2 * s)))
        canvas.paste(pic, (box[0] + pad, box[1] + pad), pic)

    # Franja inferior fija: rótulo de voz sintética (AI Act art. 50) y aviso.
    band_top = round(height * FOOTER_TOP)
    draw.line((round(width * 0.08), band_top, round(width * 0.92), band_top), fill=ACCENT, width=max(1, round(2 * s)))
    yb = _draw_centered(draw, SYNTHETIC_VOICE_LABEL, band_top + round(18 * s), _font(round(26 * s), True), AMBER, width)
    _draw_centered(draw, FOOTER_NOTE, yb + round(12 * s), _font(round(20 * s)), TEXT_MUTED, width)

    canvas.save(out, format="PNG")
    return out


# ── ffmpeg ─────────────────────────────────────────────────────────────────────────


def _run_ffmpeg(args: list[str], cwd: Path, timeout_s: float) -> None:
    """Ejecuta ffmpeg en ``cwd`` sin ventana ni stdin; ``RuntimeError`` con el final del log si falla."""
    cmd = [ffmpeg_exe(), "-hide_banner", "-nostdin", "-loglevel", "error", *args]
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
    try:
        proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=timeout_s, creationflags=flags)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"ffmpeg no terminó el vídeo en {timeout_s:.0f} s") from exc
    except OSError as exc:
        raise RuntimeError(f"No se pudo ejecutar ffmpeg: {exc}") from exc
    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.strip().splitlines()[-8:])
        raise RuntimeError(f"ffmpeg falló al montar el vídeo (código {proc.returncode}):\n{tail}")


def _concat_list(frames: list[tuple[str, float]]) -> str:
    """Lista del *concat demuxer*: cada fotograma con su duración; el último se repite (requisito)."""
    lines = ["ffconcat version 1.0"]
    for name, seconds in frames:
        lines += [f"file '{name}'", f"duration {seconds:.3f}"]
    lines.append(f"file '{frames[-1][0]}'")
    return "\n".join(lines) + "\n"


def make_video(
    audio: AudioAsset,
    images: list[Path],
    out_path: Path,
    transcript: Transcript | None = None,
    size: tuple[int, int] = DEFAULT_SIZE,
    fps: int = DEFAULT_FPS,
    *,
    title: str | None = None,
    speaker_names: dict[str, str] | None = None,
) -> VideoAsset:
    """Monta el MP4 vertical del episodio completo: diapositivas alineadas con el audio + subtítulos.

    Args:
        audio: podcast final; sus ``segments`` dan el reparto de imágenes y los subtítulos.
        images: PNG en orden (portada primero si la hay; luego gráficos). Las que no existan se omiten;
            sin ninguna, un fotograma liso de marca con el titular.
        out_path: fichero ``.mp4`` de salida (se crea la carpeta).
        transcript: se acepta por compatibilidad; los subtítulos salen de ``audio.segments`` (los
            tiempos del ``Transcript`` son los mismos). Sin segmentos no hay subtítulos.
        size: ``(ancho, alto)`` en píxeles, pares (``yuv420p``). Por defecto 720×1280 (9:16).
        fps: fotogramas por segundo (bajo: son imágenes fijas).
        title: titular del episodio bajo el logo (opcional).
        speaker_names: nombres de los locutores ``{"A": …, "B": …}`` (por defecto, los de la config).

    Raises:
        ValueError: audio inexistente o sin duración, o tamaño no válido.
        RuntimeError: ffmpeg no disponible o fallo al codificar (con el final de su log).
    """
    audio_path = Path(audio.path)
    if not audio_path.is_file():
        raise ValueError(f"No existe el audio del podcast: {audio_path}")
    if audio.duration_s <= 0:
        raise ValueError("El audio del podcast no tiene duración: no se puede montar el vídeo")
    width, height = size
    if width <= 0 or height <= 0 or width % 2 or height % 2:
        raise ValueError(f"Tamaño de vídeo no válido (deben ser pares y positivos): {size}")
    del transcript  # los subtítulos salen de ``audio.segments`` (mismos tiempos que el SRT)
    ffmpeg_exe()  # falla pronto con un mensaje claro si no hay ffmpeg

    usable = [Path(p) for p in images if p and Path(p).is_file()]
    if len(usable) < len(images):
        log.warning("Vídeo: %d imagen(es) no encontradas; se omiten", len(images) - len(usable))
    duration = float(audio.duration_s)
    plan: list[tuple[Path | None, float]] = list(plan_slides(usable, duration, audio.segments))
    if not plan:
        plan = [(None, duration)]

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="briefer_video_"))
    try:
        frames: list[tuple[str, float]] = []
        for i, (img, seconds) in enumerate(plan):
            name = f"slide_{i:03d}.png"
            _compose_frame(img, work / name, (width, height), title)
            frames.append((name, seconds))
        (work / "slides.txt").write_text(_concat_list(frames), encoding="utf-8")

        vfilter = f"fps={fps}"
        if audio.segments:
            (work / "subs.ass").write_text(build_ass(audio.segments, (width, height), speaker_names),
                                           encoding="utf-8")
            fonts = work / "fonts"
            fonts.mkdir()
            shutil.copy2(font_path(), fonts / font_path().name)
            shutil.copy2(font_path(bold=True), fonts / font_path(bold=True).name)
            vfilter += ",ass=subs.ass:fontsdir=fonts"
        vfilter += ",format=yuv420p"

        metadata = {**AI_AUDIO_METADATA, "title": title or brand.BRAND_NAME}
        meta_args = [arg for key, value in metadata.items() for arg in ("-metadata", f"{key}={value}")]
        tmp_out = work / "video.mp4"
        args = [
            "-y", "-f", "concat", "-safe", "0", "-i", "slides.txt",
            "-i", str(audio_path.resolve()),
            "-map", "0:v:0", "-map", "1:a:0",
            "-vf", vfilter,
            "-c:v", "libx264", "-preset", "veryfast", "-tune", "stillimage", "-crf", "23",
            "-pix_fmt", "yuv420p", "-r", str(fps), "-g", str(fps * 10),
            "-c:a", "aac", "-b:a", "96k",
            "-t", f"{duration:.3f}", "-shortest",
            "-movflags", "+faststart",
            *meta_args,
            tmp_out.name,
        ]
        timeout_s = FFMPEG_BASE_TIMEOUT_S + FFMPEG_TIMEOUT_PER_AUDIO_S * duration
        _run_ffmpeg(args, work, timeout_s)
        shutil.move(str(tmp_out), str(out_path))
    finally:
        shutil.rmtree(work, ignore_errors=True)
    log.info("Vídeo listo: %s (%d diapositivas, %.1f s)", out_path.name, len(plan), duration)
    return VideoAsset(path=out_path, duration_s=duration)


__all__ = [
    "DEFAULT_FPS",
    "DEFAULT_SIZE",
    "SYNTHETIC_VOICE_LABEL",
    "ass_escape",
    "ass_timestamp",
    "build_ass",
    "first_mention",
    "image_keywords",
    "make_video",
    "plan_slides",
]
