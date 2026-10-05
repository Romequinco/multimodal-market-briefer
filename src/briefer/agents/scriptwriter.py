"""Agente Guionista: convierte el análisis en un diálogo de podcast a 2 voces.

Carril B. Entrada: ``Analysis``. Salida: ``PodcastScript`` (líneas con ``speaker`` "A"/"B",
~3-5 min, cierre con el disclaimer hablado y el aviso de voz sintética). Prompt:
``prompts/scriptwriter.md``. Edición de noche de Briefly (``briefer.brand``): A = Toro, el optimista
que abre y se fija primero en lo que sube; B = Osa, la prudente que pone contexto y riesgos y cierra
con el aviso legal. Personalidad solo en el tono, nunca opiniones (nombres configurables en ``.env``).

Robustez: el guion del LLM se valida (líneas vacías, un solo locutor, tramos del mismo
locutor, duración fuera de 3-5 min, cifras que no están en el análisis, recomendaciones de
inversión, palabras con letras de otros alfabetos, errores gramaticales recurrentes y
regionalismos ajenos al español de España). Si hay
problemas se pide **una** reescritura con las correcciones; después, lo que quede se repara de
forma determinista (nunca se devuelve un guion inválido): homoglifos, gramática y regionalismos
corregidos,
palabras raras y frases con cifras no trazables o recomendaciones eliminadas, cierre añadido.
Si el LLM no da nada aprovechable, se genera un guion mínimo a partir del propio análisis.
"""

from __future__ import annotations

import re
from typing import Literal

from briefer import brand
from briefer.agents import load_prompt
from briefer.agents.guardrails import (
    contains_advice,
    extract_figures,
    fix_spoken_text,
    grammar_issues,
    odd_words,
    shared_figures,
    strip_advice,
    strip_figures,
    unhedged_causal_claims,
    untraceable_figures,
)
from briefer.logging_utils import error_text, get_logger
from briefer.providers.base import LLMProvider
from briefer.schemas import Analysis, PodcastScript, ScriptLine

log = get_logger("agents.scriptwriter")

#: Ritmo real de edge-tts (voces es-ES, pausas entre intervenciones incluidas) en palabras
#: **habladas** por minuto, es decir, contadas tras ``normalize_for_speech`` («0,53 %» son 5
#: palabras). Medido el 05-oct-2026 con el pregenerado (``data/samples/demo_briefing``): 780
#: palabras habladas en 326,9 s (5:27) -> 143,1 ppm. Antes era 150 sobre el texto escrito, que
#: estimaba 4,5 min para un episodio de 5,45 min.
WORDS_PER_MINUTE = 143
#: El mismo ritmo en palabras **escritas** del guion (cifras sin desarrollar): 681 palabras en
#: 326,9 s -> 125 ppm. Solo para decirle al LLM cuántas palabras escribir.
WRITTEN_WORDS_PER_MINUTE = 125
LENGTH_TOLERANCE = 0.4  # desviación relativa de duración que dispara una reescritura
#: Duración aceptable del episodio (producto: 3-5 min). Si el objetivo está dentro de este
#: rango, la comprobación de duración usa el rango; si no, la tolerancia relativa.
MIN_MINUTES, MAX_MINUTES = 3.0, 5.0
MAX_SAME_SPEAKER_RUN = 2  # intervenciones seguidas del mismo locutor que se toleran
#: Nota que ``write_script`` añade a ``trace`` cuando usa ``fallback_script`` (el pipeline la
#: detecta para marcar el paso como fallback).
FALLBACK_NOTE = "guion: respaldo determinista (el LLM no devolvió un guion válido)"

CLOSING_LINE_ES = (
    "Y antes de despedirnos, un recordatorio importante: este episodio lo ha generado "
    "automáticamente un sistema de inteligencia artificial y nuestras voces son sintéticas. "
    "Es información con fines divulgativos, no asesoramiento financiero ni una recomendación "
    "de inversión. Contrastad siempre con fuentes oficiales. Buenas noches y ¡hasta mañana!"
)
#: Locutores por defecto (marca): A = Toro, B = Osa. El pipeline pasa los de ``Settings``.
DEFAULT_SPEAKERS: tuple[str, str] = (brand.SPEAKER_A_NAME, brand.SPEAKER_B_NAME)

_DISCLAIMER_HINTS = ("asesoramiento", "recomendación de inversión", "no es una recomendación")
_SYNTHETIC_HINTS = ("sintétic", "inteligencia artificial", " ia ", "generad")


def spoken_word_count(text: str) -> int:
    """Palabras que dirá la voz: se cuentan tras ``normalize_for_speech`` (las cifras, siglas y
    tickers se desarrollan). Si la normalización fallara, cuenta las palabras escritas."""
    try:
        from briefer.media.speech import normalize_for_speech

        return len(normalize_for_speech(text).split())
    except Exception:  # pragma: no cover - la normalización es pura; por si acaso
        return len(text.split())


def written_word_count(lines: list[ScriptLine]) -> int:
    """Palabras escritas del guion (lo que cuenta el LLM)."""
    return sum(len(line.text.split()) for line in lines)


def target_written_words(target_minutes: float) -> int:
    """Palabras escritas que se piden al LLM para ``target_minutes`` (4 min -> 500)."""
    return int(target_minutes * WRITTEN_WORDS_PER_MINUTE)


def estimate_duration_s(lines: list[ScriptLine], wpm: int = WORDS_PER_MINUTE) -> float:
    """Duración estimada del guion en segundos: palabras habladas (tras ``normalize_for_speech``)
    al ritmo medido de edge-tts (``WORDS_PER_MINUTE`` ≈ 143 ppm)."""
    words = sum(spoken_word_count(line.text) for line in lines)
    return round(words / max(1, wpm) * 60, 1)


def _render_system(target_minutes: float, speaker_names: tuple[str, str]) -> str:
    target_words = target_written_words(target_minutes)
    return (
        load_prompt("scriptwriter")
        .replace("{target_minutes}", f"{target_minutes:g}")
        .replace("{target_words}", str(target_words))
        .replace("{words_per_minute}", str(WRITTEN_WORDS_PER_MINUTE))
        .replace("{speaker_a}", speaker_names[0])
        .replace("{speaker_b}", speaker_names[1])
        .replace("{speaker_a_role}", brand.SPEAKER_A_ROLE)
        .replace("{speaker_b_role}", brand.SPEAKER_B_ROLE)
        .replace("{brand}", brand.BRAND_NAME)
        .replace("{greeting}", brand.GREETING)
    )


def _ticker_names(analysis: Analysis) -> dict[str, str]:
    try:
        from briefer.ingest.tickers import TICKER_UNIVERSE
    except Exception:
        return {}
    tickers = {t for kp in analysis.key_points for t in kp.tickers}
    return {t: str(TICKER_UNIVERSE[t].get("name", t)) for t in tickers if t in TICKER_UNIVERSE}


def build_user_message(analysis: Analysis) -> str:
    """Mensaje de usuario: el análisis en JSON + nombres de empresa para leer en voz alta."""
    names = _ticker_names(analysis)
    parts = ["# Análisis del día (única fuente de información)", analysis.model_dump_json(indent=2)]
    if names:
        parts.append("# Nombres para leer en voz alta (no digas el ticker)")
        parts.extend(f"- {t} -> {n}" for t, n in sorted(names.items()))
    return "\n".join(parts)


def _has_closing(lines: list[ScriptLine]) -> bool:
    tail = " ".join(line.text for line in lines[-2:]).lower()
    return any(h in tail for h in _DISCLAIMER_HINTS) and any(h in f" {tail} " for h in _SYNTHETIC_HINTS)


def same_speaker_runs(lines: list[ScriptLine], min_len: int = MAX_SAME_SPEAKER_RUN + 1) -> list[tuple[int, int]]:
    """Tramos ``(inicio, longitud)`` con ``min_len`` o más intervenciones seguidas del mismo locutor."""
    runs: list[tuple[int, int]] = []
    start = 0
    for i in range(1, len(lines) + 1):
        if i == len(lines) or lines[i].speaker != lines[start].speaker:
            if i - start >= min_len:
                runs.append((start, i - start))
            start = i
    return runs


def merge_long_runs(lines: list[ScriptLine], max_run: int = MAX_SAME_SPEAKER_RUN) -> list[ScriptLine]:
    """Reparación determinista: une en una sola intervención cada tramo de más de ``max_run``
    líneas seguidas del mismo locutor (el diálogo vuelve a alternar)."""
    runs = same_speaker_runs(lines, max_run + 1)
    if not runs:
        return lines
    out: list[ScriptLine] = []
    i = 0
    run_starts = {start: length for start, length in runs}
    while i < len(lines):
        length = run_starts.get(i)
        if length:
            text = " ".join(line.text.strip() for line in lines[i : i + length])
            out.append(ScriptLine(speaker=lines[i].speaker, text=text))
            i += length
        else:
            out.append(lines[i])
            i += 1
    return out


def duration_bounds_s(target_minutes: float, length_tolerance: float) -> tuple[float, float]:
    """Duración aceptable (s): la banda ±``length_tolerance`` recortada a 3-5 min si el
    objetivo está en ese rango (p. ej. objetivo 4 min -> 3-5 min)."""
    low, high = target_minutes * (1 - length_tolerance), target_minutes * (1 + length_tolerance)
    if MIN_MINUTES <= target_minutes <= MAX_MINUTES:
        low, high = max(low, MIN_MINUTES), min(high, MAX_MINUTES)
    return low * 60, high * 60


def script_text(script: PodcastScript) -> str:
    """Texto hablado del guion (una intervención por línea)."""
    return "\n".join(line.text for line in script.lines)


def missing_key_points(script: PodcastScript, analysis: Analysis) -> list[str]:
    """Títulos de los puntos clave del análisis que el guion no trata.

    Heurística por cifras: un punto con cifras se da por tratado si al menos una de ellas
    (admitiendo redondeo) aparece en el guion; los puntos sin cifras no se comprueban.
    """
    text = script_text(script)
    missing: list[str] = []
    for kp in analysis.key_points:
        figures = extract_figures(kp.explanation)
        if figures and not shared_figures(kp.explanation, text):
            missing.append(kp.title)
    return missing


def script_problems(
    script: PodcastScript,
    target_minutes: float,
    length_tolerance: float | None = LENGTH_TOLERANCE,
    *,
    reference: str | None = None,
    analysis: Analysis | None = None,
) -> list[str]:
    """Lista de problemas del guion (vacía si es válido). Textos pensados para el LLM.

    ``reference``: texto del ``Analysis`` (``build_user_message``); si se indica, las cifras del
    guion que no aparezcan en él son un problema (*grounding* del guion).
    ``analysis``: si se indica, cada punto clave debe estar tratado (``missing_key_points``).
    """
    problems: list[str] = []
    lines = script.lines
    if len(lines) < 2:
        problems.append("El guion tiene menos de dos intervenciones.")
    if any(not line.text.strip() for line in lines):
        problems.append("Hay intervenciones vacías; todas deben tener texto.")
    speakers = {line.speaker for line in lines if line.text.strip()}
    if lines and speakers != {"A", "B"}:
        problems.append('Solo habla un locutor; deben alternarse "A" y "B".')
    elif runs := same_speaker_runs(lines):
        where = ", ".join(f"líneas {s + 1}-{s + n}" for s, n in runs[:5])
        problems.append(
            f"Hay {len(runs)} tramo(s) con 3 o más intervenciones seguidas del mismo locutor ({where}); "
            "alterna A y B."
        )
    if length_tolerance is not None and lines:
        low_s, high_s = duration_bounds_s(target_minutes, length_tolerance)
        duration = estimate_duration_s(lines)
        if not low_s <= duration <= high_s:
            words = target_written_words(target_minutes)
            have = written_word_count(lines)
            problems.append(
                f"La duración estimada es {duration / 60:.1f} min ({have} palabras) y debe estar entre "
                f"{low_s / 60:g} y {high_s / 60:g} min: apunta a unas {words} palabras en total"
                + (" (desarrolla más cada punto clave con su contexto)." if duration < low_s else " (resume).")
            )
    text = script_text(script)
    if reference is not None and (missing := untraceable_figures(text, reference)):
        problems.append(
            "Estas cifras no aparecen en el análisis: " + ", ".join(missing[:8])
            + ". Usa solo cifras del análisis (puedes redondear) o quita esas frases."
        )
    if analysis is not None and (skipped := missing_key_points(script, analysis)):
        problems.append(
            "Faltan puntos clave del análisis: " + ", ".join(f"«{t}»" for t in skipped)
            + ". Dedica un bloque a cada uno (también a los documentos del oyente)."
        )
    if contains_advice(text):
        problems.append("Hay frases que suenan a recomendación de inversión: elimínalas (MiFID II).")
    if odd := odd_words(text):
        problems.append(
            "Hay palabras con caracteres de otros alfabetos o invisibles que la voz leerá mal: "
            + ", ".join(odd[:5]) + ". Escríbelas solo con letras españolas."
        )
    if bad := grammar_issues(text):
        problems.append(
            "Errores gramaticales: " + ", ".join(f"«{b}»" for b in bad[:5])
            + " (con «para que» va subjuntivo: «para que veáis»)."
        )
    if regional := regionalisms(text):
        problems.append(
            "Palabras de otras variantes del español: " + ", ".join(f"«{w}»" for w in regional[:5])
            + ". Escribe en español de España («descontado», «allí», «aquí», «ahora mismo», «charlar», "
            "«ordenador», «móvil»)."
        )
    return problems


# ── Regionalismos ──────────────────────────────────────────────────────────────────
# Palabras de otras variantes del español (o calcos) que chirrían en un podcast de España.
# Solo casos seguros: «más allá», «allá por 2008» o «membrana celular» no se tocan.
_ARTICLE = r"\b(el|un|los|unos|su|sus|del|tu|mi) "
REGIONALISM_FIXES: list[tuple[re.Pattern[str], str, str]] = [
    # (patrón, sustitución, palabra para el aviso al LLM)
    *[
        (re.compile(rf"\b{wrong}\b", re.IGNORECASE), right, wrong)
        for wrong, right in (
            ("precificado", "descontado"), ("precificada", "descontada"),
            ("precificados", "descontados"), ("precificadas", "descontadas"),
            ("precificar", "descontar"), ("precificando", "descontando"),
            ("precifica", "descuenta"), ("precifican", "descuentan"),
        )
    ],
    (re.compile(r"\bprecificación\b", re.IGNORECASE), "valoración", "precificación"),
    (re.compile(r"(?<!\bmás )(?<!\bpara )\ballá\b(?! por\b)", re.IGNORECASE), "allí", "allá"),
    (re.compile(r"(?<!\bpara )\bacá\b", re.IGNORECASE), "aquí", "acá"),
    (re.compile(r"\bahorita\b", re.IGNORECASE), "ahora mismo", "ahorita"),
    *[
        (re.compile(rf"\bplatic{a}\b", re.IGNORECASE), f"charl{b}", f"platic{a}")
        for a, b in (("ar", "ar"), ("amos", "amos"), ("ando", "ando"), ("ado", "ado"), ("a", "a"))
    ],
    (re.compile(r"\bplática\b", re.IGNORECASE), "charla", "plática"),
    (re.compile(r"\bcomputadoras\b", re.IGNORECASE), "ordenadores", "computadoras"),
    (re.compile(r"\bcomputadora\b", re.IGNORECASE), "ordenador", "computadora"),
    # «celular» solo como sustantivo (tras artículo o «teléfono»): «terapia celular» es correcto.
    (re.compile(r"\bteléfonos celulares\b", re.IGNORECASE), "teléfonos móviles", "celulares"),
    (re.compile(r"\bteléfono celular\b", re.IGNORECASE), "teléfono móvil", "celular"),
    (re.compile(_ARTICLE + r"celulares\b", re.IGNORECASE), r"\1 móviles", "celulares"),
    (re.compile(_ARTICLE + r"celular\b", re.IGNORECASE), r"\1 móvil", "celular"),
    (re.compile(r"\bchec(ar|amos|ad)\b", re.IGNORECASE), "comprob\\1", "checar"),
]


def _keep_case(found: str, fixed: str) -> str:
    return fixed[0].upper() + fixed[1:] if found[:1].isupper() else fixed


def regionalisms(text: str) -> list[str]:
    """Regionalismos de ``REGIONALISM_FIXES`` presentes en ``text`` (sin repetir)."""
    found = [word for pattern, _fix, word in REGIONALISM_FIXES if pattern.search(text or "")]
    return list(dict.fromkeys(found))


def fix_regionalisms(text: str) -> str:
    """Sustituye los regionalismos por la palabra de España («precificado» -> «descontado»)."""
    for pattern, fix, _word in REGIONALISM_FIXES:
        def _sub(m: re.Match[str], f: str = fix) -> str:
            return _keep_case(m.group(0), m.expand(f))

        text = pattern.sub(_sub, text)
    return text


# Homoglifos cirílicos que a veces cuela el LLM barato en palabras españolas («suба»): el TTS
# los leería mal. Se sustituyen por su letra latina equivalente.
_HOMOGLYPHS = str.maketrans({
    "а": "a", "б": "b", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y", "х": "x", "і": "i",
    "А": "A", "Е": "E", "О": "O", "Р": "P", "С": "C", "Т": "T", "Н": "H", "К": "K", "М": "M", "В": "B",
})


def fix_homoglyphs(text: str) -> str:
    """Sustituye letras cirílicas con aspecto latino por las latinas (``"suба"`` -> ``"suba"``)."""
    return text.translate(_HOMOGLYPHS)


def _repair(lines: list[ScriptLine], untraceable: list[str] | None = None) -> list[ScriptLine]:
    """Reparación determinista: homoglifos, gramática, regionalismos y palabras raras, vacíos,
    frases de recomendación, frases con cifras no trazables (``untraceable``) y 2 locutores."""
    cleaned: list[ScriptLine] = []
    for line in lines:
        text = fix_regionalisms(fix_spoken_text(" ".join(fix_homoglyphs(line.text).split())))
        text, changed = strip_advice(text)
        if changed:
            log.warning("Guionista: eliminada una frase con recomendación de inversión")
        if untraceable:
            text, cut = strip_figures(text, untraceable)
            if cut:
                log.warning("Guionista: eliminada una frase con cifras no trazables %s", untraceable)
        if text:
            cleaned.append(ScriptLine(speaker=line.speaker, text=text))
    if len({line.speaker for line in cleaned}) < 2 and len(cleaned) >= 2:
        log.warning("Guionista: un solo locutor; se reasignan las voces alternando A/B")
        cleaned = [
            ScriptLine(speaker="A" if i % 2 == 0 else "B", text=line.text)
            for i, line in enumerate(cleaned)
        ]
    return cleaned


def fallback_script(analysis: Analysis, speaker_names: tuple[str, str] = DEFAULT_SPEAKERS) -> PodcastScript:
    """Guion mínimo y determinista construido solo con el análisis (si el LLM falla).

    Termina con A; ``_finalize`` añade el cierre en boca de B (Osa)."""
    a, b = speaker_names
    lines = [
        ScriptLine(
            speaker="A",
            text=f"{brand.GREETING}, soy {a} y esto es {brand.BRAND_NAME}, el cierre del día.",
        ),
        ScriptLine(speaker="B", text=f"Y yo soy {b}. El titular de hoy: {analysis.headline}."),
    ]
    for kp in analysis.key_points:
        lines.append(ScriptLine(speaker="A", text=f"Vamos con otro tema: {kp.title}. ¿Qué ha pasado?"))
        lines.append(ScriptLine(speaker="B", text=kp.explanation))
    lines.append(ScriptLine(speaker="A", text=f"¿Y el tono general del mercado? {analysis.market_mood}"))
    return PodcastScript(title=brand.episode_title(analysis.date), lines=lines)


def _finalize(
    script: PodcastScript,
    analysis: Analysis,
    untraceable: list[str] | None = None,
    speaker_names: tuple[str, str] = DEFAULT_SPEAKERS,
) -> PodcastScript:
    """Repara, añade el cierre obligatorio si falta y recalcula la duración.

    El cierre lo dice siempre B (Osa, la prudente): si la última intervención ya es de B, el
    aviso se añade a esa intervención para no romper la alternancia de locutores."""
    lines = merge_long_runs(_repair(script.lines, untraceable))
    if not lines:
        log.warning("Guionista: guion vacío tras reparar; se usa el guion de respaldo")
        lines = _repair(fallback_script(analysis, speaker_names).lines)
    if not _has_closing(lines):
        closer: Literal["A", "B"] = "B"
        if lines[-1].speaker == closer:
            lines[-1] = ScriptLine(speaker=closer, text=f"{lines[-1].text} {CLOSING_LINE_ES}")
        else:
            lines.append(ScriptLine(speaker=closer, text=CLOSING_LINE_ES))
    title = re.sub(r"\s+", " ", script.title or "").strip() or brand.episode_title(analysis.date)
    return PodcastScript(title=title, lines=lines, est_duration_s=estimate_duration_s(lines))


#: Errores del proveedor que no se arreglan reintentando (clave inválida, sin permiso, modelo
#: inexistente): no se gasta una segunda llamada.
_NON_RETRYABLE_STATUS = frozenset({401, 403, 404})
_NON_RETRYABLE_NAMES = frozenset({"AuthenticationError", "PermissionDeniedError", "NotFoundError"})


class _NonRetryableLLMError(Exception):
    """El LLM falló por una causa que un reintento no cambia."""


def _is_non_retryable(exc: BaseException) -> bool:
    status = getattr(exc, "status_code", None)
    return type(exc).__name__ in _NON_RETRYABLE_NAMES or status in _NON_RETRYABLE_STATUS


def _call(llm: LLMProvider, system: str, messages: list[dict]) -> PodcastScript | None:
    try:
        result = llm.complete(system, messages, response_model=PodcastScript)
    except Exception as exc:  # salida no válida del LLM: se reintenta / se usa respaldo
        log.warning("Guionista: el LLM no devolvió un guion válido (%s)", error_text(exc))
        if _is_non_retryable(exc):
            raise _NonRetryableLLMError(type(exc).__name__) from exc
        return None
    if isinstance(result, PodcastScript):
        return result
    try:
        return (
            PodcastScript.model_validate_json(result)
            if isinstance(result, str)
            else PodcastScript.model_validate(result)
        )
    except Exception as exc:
        log.warning("Guionista: respuesta no convertible a PodcastScript (%s)", exc)
        return None


def write_script(
    analysis: Analysis,
    llm: LLMProvider,
    target_minutes: float = 4.0,
    speaker_names: tuple[str, str] = DEFAULT_SPEAKERS,
    *,
    max_retries: int = 1,
    length_tolerance: float | None = LENGTH_TOLERANCE,
    trace: list[str] | None = None,
    check_figures: bool = True,
) -> PodcastScript:
    """Genera el guion del episodio (A/B alternando, apertura y cierre con disclaimer).

    Args:
        analysis: salida del Agente Analista.
        llm: proveedor LLM inyectado.
        target_minutes: duración objetivo (≈143 palabras habladas por minuto).
        speaker_names: nombres de los locutores A y B (solo para el texto del guion).
        max_retries: reescrituras como máximo si el guion tiene problemas (por defecto 1).
        length_tolerance: desviación relativa de duración tolerada; ``None`` desactiva esa
            comprobación (útil con ``MockLLM``, que devuelve un guion fijo corto).
        trace: lista opcional donde se añaden notas de calidad (reintentos, respaldo); el
            pipeline las guarda en ``StepMetric.detail``.
        check_figures: *grounding* del guion: toda cifra debe estar en el ``Analysis``; si no,
            cuenta como problema (reintento) y lo que quede se elimina al reparar.
    """
    notes = trace if trace is not None else []
    system = _render_system(target_minutes, speaker_names)
    user = build_user_message(analysis)
    reference = user if check_figures else None
    messages: list[dict] = [{"role": "user", "content": user}]
    best: PodcastScript | None = None
    best_score: tuple[int, float] | None = None
    for attempt in range(max_retries + 1):
        try:
            script = _call(llm, system, messages)
        except _NonRetryableLLMError as exc:
            notes.append(f"guion: sin reintento ({exc}: un reintento no lo arregla)")
            break
        if script is None:
            problems = ["La respuesta no tenía el formato estructurado pedido."]
        else:
            problems = script_problems(
                script, target_minutes, length_tolerance, reference=reference,
                analysis=analysis if check_figures else None,
            )
            score = (len(problems), abs(estimate_duration_s(script.lines) - target_minutes * 60))
            if best_score is None or score < best_score:
                best, best_score = script, score
        if not problems:
            break
        if attempt < max_retries:
            log.warning("Guionista: reintento %d por: %s", attempt + 1, " ".join(problems))
            notes.append(f"guion: reintento {attempt + 1} ({' '.join(problems)[:200]})")
            messages = messages[:1] + [
                {
                    "role": "assistant",
                    "content": script.model_dump_json() if script is not None else "(respuesta inválida)",
                },
                {
                    "role": "user",
                    "content": "Reescribe el guion completo corrigiendo esto: " + " ".join(problems),
                },
            ]
    if best is None:
        log.warning("Guionista: sin guion del LLM; se usa el guion de respaldo")
        notes.append(FALLBACK_NOTE)
        best = fallback_script(analysis, speaker_names)
    untraceable = untraceable_figures(script_text(best), reference) if reference is not None else []
    if untraceable:
        notes.append(f"guion: eliminadas frases con cifras no trazables ({', '.join(untraceable[:6])})")
    elif reference is not None:
        notes.append("guion: cifras trazables al análisis")
    final = _finalize(best, analysis, untraceable, speaker_names)
    if causal := unhedged_causal_claims(script_text(final)):
        notes.append(f"guion: {len(causal)} frase(s) con causa no matizada")
    notes.append(f"guion: {len(final.lines)} intervenciones, ~{final.est_duration_s / 60:.1f} min")
    return final


__all__ = [
    "CLOSING_LINE_ES",
    "DEFAULT_SPEAKERS",
    "FALLBACK_NOTE",
    "LENGTH_TOLERANCE",
    "MAX_MINUTES",
    "MAX_SAME_SPEAKER_RUN",
    "MIN_MINUTES",
    "REGIONALISM_FIXES",
    "WORDS_PER_MINUTE",
    "WRITTEN_WORDS_PER_MINUTE",
    "build_user_message",
    "duration_bounds_s",
    "estimate_duration_s",
    "fallback_script",
    "fix_regionalisms",
    "merge_long_runs",
    "missing_key_points",
    "regionalisms",
    "same_speaker_runs",
    "script_problems",
    "script_text",
    "spoken_word_count",
    "target_written_words",
    "write_script",
    "written_word_count",
]
