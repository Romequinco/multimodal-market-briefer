"""Transcripción del episodio en texto plano y subtítulos SRT.

Carril C. Entrada: ``PodcastScript`` + ``AudioAsset`` (con ``segments``). Salida:
``Transcript(text, srt_path)``. No necesita STT: los tiempos salen de la síntesis.

Los subtítulos siguen pautas de legibilidad habituales: como mucho 2 filas de 42 caracteres
por bloque; las intervenciones largas se trocean en varios bloques repartiendo el tiempo del
segmento en proporción a los caracteres de cada trozo.

Verificación opcional (``verify_podcast``): se transcribe el MP3 final con el STT y se compara
con el guion (WER por palabras). Así se detecta lo que la voz sintética lee mal (siglas,
cifras, nombres) sin escuchar el episodio entero.
"""

from __future__ import annotations

import re
import textwrap
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from briefer.providers.base import STTProvider
from briefer.schemas import AudioSegment, PodcastScript, Transcript

MAX_CHARS_PER_ROW = 42
MAX_ROWS = 2
FALLBACK_SPEAKER_NAMES = {"A": "Presentador", "B": "Analista"}


def default_speaker_names() -> dict[str, str]:
    """Nombres legibles de los locutores desde la configuración (o genéricos si falla)."""
    try:
        from briefer.config import get_settings

        s = get_settings()
        return {"A": s.briefer_speaker_a_name, "B": s.briefer_speaker_b_name}
    except Exception:  # pragma: no cover - .env mal formado
        return dict(FALLBACK_SPEAKER_NAMES)


def _names(speaker_names: dict[str, str] | None) -> dict[str, str]:
    names = dict(FALLBACK_SPEAKER_NAMES) if speaker_names is not None else default_speaker_names()
    names.update(speaker_names or {})
    return names


def format_srt_timestamp(seconds: float) -> str:
    """``3.5`` -> ``"00:00:03,500"`` (formato SRT). Los negativos se recortan a 0."""
    total_ms = int(round(max(0.0, float(seconds)) * 1000))
    hours, rest = divmod(total_ms, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    secs, ms = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def _split_caption(text: str, width: int = MAX_CHARS_PER_ROW, rows: int = MAX_ROWS) -> list[str]:
    """Trocea ``text`` en bloques de como mucho ``rows`` filas de ``width`` caracteres."""
    wrapped = textwrap.wrap(" ".join(text.split()), width=width, break_long_words=True) or [""]
    return ["\n".join(wrapped[i : i + rows]) for i in range(0, len(wrapped), rows)]


def segments_to_srt(segments: list[AudioSegment], speaker_names: dict[str, str] | None = None) -> str:
    """Texto SRT: índice, ``inicio --> fin`` y texto (prefijo con el nombre del hablante).

    El nombre del locutor solo aparece en el primer bloque de cada intervención para no
    restar espacio en pantalla.
    """
    names = _names(speaker_names)
    blocks: list[str] = []
    index = 1
    for seg in segments:
        name = names.get(seg.speaker, seg.speaker)
        chunks = _split_caption(f"{name}: {seg.text.strip()}")
        weights = [max(1, len(c.replace("\n", " "))) for c in chunks]
        total_w = sum(weights)
        span = max(0.0, seg.end_s - seg.start_s)
        cursor = seg.start_s
        for chunk, w in zip(chunks, weights, strict=True):
            end = cursor + span * w / total_w
            blocks.append(f"{index}\n{format_srt_timestamp(cursor)} --> {format_srt_timestamp(end)}\n{chunk}\n")
            index += 1
            cursor = end
    return "\n".join(blocks)


def build_transcript(
    script: PodcastScript,
    segments: list[AudioSegment],
    out_dir: Path,
    speaker_names: dict[str, str] | None = None,
) -> Transcript:
    """Genera la transcripción legible y escribe ``out_dir/podcast.srt``.

    ``text`` usa una línea por intervención con el nombre del locutor (``"Toro: …"``),
    separadas por una línea en blanco. Si ``segments`` está vacío (sin audio) no hay SRT.
    """
    names = _names(speaker_names)
    source = segments or script.lines
    text = "\n\n".join(
        f"{names.get(item.speaker, item.speaker)}: {item.text.strip()}" for item in source if item.text.strip()
    )
    if not segments:
        return Transcript(text=text, srt_path=None)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    srt_path = out_dir / "podcast.srt"
    srt_path.write_text(segments_to_srt(segments, names), encoding="utf-8")
    return Transcript(text=text, srt_path=srt_path)


# ── Verificación del podcast con STT (WER frente al guion) ─────────────────────────

#: Intervenciones con más errores que se devuelven en ``PodcastVerification.worst_lines``.
WORST_LINES = 3
_TOKEN = re.compile(r"[a-z0-9ñ]+")
_DIGITS = re.compile(r"\d+")


def wer_tokens(text: str) -> list[str]:
    """Palabras comparables de ``text`` para el WER.

    Se aplica ``normalize_for_speech`` (igual al guion y a la transcripción: «0,53 %» y «cero
    coma cincuenta y tres por ciento» acaban igual), se pasan a palabras los enteros que queden
    («2026»), y se quitan mayúsculas, tildes y puntuación (la «ñ» se conserva).
    """
    from briefer.media.speech import normalize_for_speech, number_to_words

    spoken = normalize_for_speech(text or "")
    spoken = _DIGITS.sub(lambda m: f" {number_to_words(int(m.group(0)))} " if len(m.group(0)) <= 15 else " ", spoken)
    spoken = spoken.casefold().replace("ñ", "\0")
    folded = "".join(c for c in unicodedata.normalize("NFKD", spoken) if not unicodedata.combining(c))
    return _TOKEN.findall(folded.replace("\0", "ñ"))


def align_words(ref: list[str], hyp: list[str]) -> tuple[int, list[int]]:
    """Distancia de edición por palabras (sustituciones + borrados + inserciones) entre ``ref``
    y ``hyp``, y errores atribuidos a cada palabra de ``ref`` (una inserción cuenta para la
    palabra de referencia siguiente, o la última)."""
    n, m = len(ref), len(hyp)
    # dp[i][j]: distancia entre ref[:i] y hyp[:j]
    dp = [list(range(m + 1))] + [[i] + [0] * m for i in range(1, n + 1)]
    for i in range(1, n + 1):
        row, prev, r = dp[i], dp[i - 1], ref[i - 1]
        for j in range(1, m + 1):
            row[j] = min(prev[j - 1] + (r != hyp[j - 1]), prev[j] + 1, row[j - 1] + 1)
    per_word = [0] * n
    i, j = n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0 and dp[i][j] == dp[i - 1][j - 1] + (ref[i - 1] != hyp[j - 1]):
            per_word[i - 1] += int(ref[i - 1] != hyp[j - 1])
            i, j = i - 1, j - 1
        elif i > 0 and dp[i][j] == dp[i - 1][j] + 1:  # borrado (la voz no lo dijo o el STT no lo oyó)
            per_word[i - 1] += 1
            i -= 1
        else:  # inserción
            if n:
                per_word[min(i, n - 1)] += 1
            j -= 1
    return dp[n][m], per_word


def word_error_rate(reference: str, hypothesis: str) -> float:
    """WER (0-1+) de ``hypothesis`` frente a ``reference`` con la normalización de ``wer_tokens``."""
    ref, hyp = wer_tokens(reference), wer_tokens(hypothesis)
    if not ref:
        return 0.0 if not hyp else 1.0
    return align_words(ref, hyp)[0] / len(ref)


@dataclass
class LineError:
    """Errores del STT atribuidos a una intervención del guion."""

    index: int  # posición en ``script.lines`` (0-based)
    speaker: str
    text: str
    errors: int
    words: int

    @property
    def wer(self) -> float:
        return self.errors / max(1, self.words)


@dataclass
class PodcastVerification:
    """Resultado de ``verify_podcast``.

    ``simulated`` es ``True`` si el STT es el mock (su transcripción es inventada y el WER no
    significa nada: la UI no debe presentarlo como medido).
    """

    wer: float
    errors: int
    ref_words: int
    hyp_words: int
    hypothesis: str
    provider: str
    model: str
    simulated: bool = False
    duration_s: float = 0.0
    worst_lines: list[LineError] = field(default_factory=list)

    def summary(self) -> str:
        """Texto para ``StepMetric.detail``: «WER 4,2 % frente al guion (33/780 palabras)…»."""
        pct = f"{self.wer * 100:.1f}".replace(".", ",")
        text = f"WER {pct} % frente al guion ({self.errors}/{self.ref_words} palabras)"
        if self.simulated:
            return text + " [simulado: STT mock]"
        if self.worst_lines:
            worst = "; ".join(
                f"línea {w.index + 1} ({w.errors} err.): «{w.text[:60]}{'…' if len(w.text) > 60 else ''}»"
                for w in self.worst_lines
            )
            text += f"; peores: {worst}"
        return text


def verify_podcast(
    audio_path: Path,
    script: PodcastScript,
    stt: STTProvider,
    *,
    language: str = "es",
    worst: int = WORST_LINES,
) -> PodcastVerification:
    """Transcribe el podcast final con ``stt`` y mide el WER frente al texto del guion.

    El guion y la transcripción pasan por la misma normalización (``wer_tokens``), de modo que
    solo cuentan como error las palabras que la voz leyó (o el STT oyó) distinto. Los errores se
    atribuyen a cada intervención para devolver las ``worst`` peores.

    Raises:
        FileNotFoundError / ValueError: audio inexistente, vacío o > 25 MB (lo valida el STT real).
        Cualquier error del proveedor STT (el pipeline lo trata como paso opcional).
    """
    hypothesis = stt.transcribe(Path(audio_path), language)
    simulated = getattr(stt, "provider_name", "") == "mock"
    line_tokens = [wer_tokens(line.text) for line in script.lines]
    ref = [tok for toks in line_tokens for tok in toks]
    hyp = wer_tokens(hypothesis)
    errors, per_word = align_words(ref, hyp) if ref else (len(hyp), [])
    worst_lines: list[LineError] = []
    pos = 0
    for idx, (line, toks) in enumerate(zip(script.lines, line_tokens, strict=True)):
        n_err = sum(per_word[pos : pos + len(toks)])
        pos += len(toks)
        if n_err:
            worst_lines.append(LineError(idx, line.speaker, line.text, n_err, len(toks)))
    worst_lines.sort(key=lambda w: (-w.errors, -w.wer, w.index))
    return PodcastVerification(
        wer=round(errors / len(ref), 4) if ref else (0.0 if not hyp else 1.0),
        errors=errors,
        ref_words=len(ref),
        hyp_words=len(hyp),
        hypothesis=hypothesis,
        provider=getattr(stt, "provider_name", "-"),
        model=getattr(stt, "model", "-"),
        simulated=simulated,
        duration_s=float(getattr(stt, "last_duration_s", 0.0) or 0.0),
        worst_lines=worst_lines[: max(0, worst)],
    )


__all__ = [
    "LineError",
    "PodcastVerification",
    "WORST_LINES",
    "align_words",
    "build_transcript",
    "default_speaker_names",
    "format_srt_timestamp",
    "segments_to_srt",
    "verify_podcast",
    "wer_tokens",
    "word_error_rate",
]
