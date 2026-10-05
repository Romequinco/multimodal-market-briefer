"""Calidad del podcast (carril B), sin red:

- ritmo de locución calibrado con el pregenerado (``WORDS_PER_MINUTE``);
- regionalismos ajenos al español de España en el guion;
- lecturas que edge-tts hacía mal (detectadas con STT sobre el pregenerado);
- verificación del podcast con STT (``transcript.verify_podcast``) y su paso opcional en el pipeline.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from briefer import pipeline
from briefer.agents import scriptwriter
from briefer.config import Settings
from briefer.logging_utils import step_failed
from briefer.media import transcript
from briefer.media.speech import normalize_for_speech
from briefer.providers.base import STTProvider
from briefer.providers.mock import MockSTT
from briefer.schemas import AudioAsset, PodcastScript, ScriptLine, StepMetric

DEMO = Path(__file__).resolve().parents[1] / "data" / "samples" / "demo_briefing"


# ── 7. Ritmo de locución ─────────────────────────────────────────────────────────


def _demo() -> dict:
    return json.loads((DEMO / "briefing.json").read_text(encoding="utf-8"))


def test_words_per_minute_matches_pregenerated_podcast() -> None:
    """La estimación de duración del pregenerado cae a menos de un 3 % de su duración real."""
    data = _demo()
    script = PodcastScript.model_validate(data["script"])
    real = data["audio"]["duration_s"]  # 5:27 medido en el MP3
    estimate = scriptwriter.estimate_duration_s(script.lines)
    assert abs(estimate - real) / real < 0.03
    # Con el ritmo antiguo (150 ppm sobre texto escrito) se estimaban ~4,5 min: fuera de la puerta.
    assert scriptwriter.written_word_count(script.lines) / 150 * 60 < real * 0.85


def test_duration_gate_flags_the_pregenerated_podcast_as_too_long() -> None:
    script = PodcastScript.model_validate(_demo()["script"])
    problems = scriptwriter.script_problems(script, 4.0)
    assert any("duración estimada" in p and "(resume)" in p for p in problems)


def test_estimate_counts_spoken_words_not_written() -> None:
    lines = [ScriptLine(speaker="A", text="Sube un 0,53 %")]  # 4 escritas, 9 habladas
    assert scriptwriter.spoken_word_count(lines[0].text) == 9
    assert scriptwriter.estimate_duration_s(lines, wpm=60) == 9.0


def test_prompt_asks_for_written_words_at_measured_pace() -> None:
    system = scriptwriter._render_system(4.0, ("Álvaro", "Elvira"))
    assert scriptwriter.target_written_words(4.0) == 500
    assert "500 palabras" in system and "125 palabras" in system
    assert "{" not in system.replace("{}", "")  # sin marcadores sin sustituir


# ── 8. Regionalismos ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("text", "fixed"),
    [
        ("El mercado ya lo había precificado.", "El mercado ya lo había descontado."),
        ("Las subidas están precificadas.", "Las subidas están descontadas."),
        ("Es difícil precificar el riesgo.", "Es difícil descontar el riesgo."),
        ("El mercado precifica dos bajadas.", "El mercado descuenta dos bajadas."),
        ("¿Qué ha pasado allá?", "¿Qué ha pasado allí?"),
        ("Acá en Europa el día fue tranquilo.", "Aquí en Europa el día fue tranquilo."),
        ("Ahorita lo vemos.", "Ahora mismo lo vemos."),
        ("Vamos a platicar de Nvidia.", "Vamos a charlar de Nvidia."),
        ("Vende más computadoras.", "Vende más ordenadores."),
        ("La demanda de computadora personal.", "La demanda de ordenador personal."),
        ("Vende el celular más caro.", "Vende el móvil más caro."),
        ("El teléfono celular de Apple.", "El teléfono móvil de Apple."),
        ("Hay que checar los datos.", "Hay que comprobar los datos."),
    ],
)
def test_regionalisms_are_detected_and_fixed(text: str, fixed: str) -> None:
    assert scriptwriter.regionalisms(text)
    assert scriptwriter.fix_regionalisms(text) == fixed


@pytest.mark.parametrize(
    "text",
    [
        "Más allá del dato, el tono es positivo.",
        "Allá por 2008 la crisis fue distinta.",
        "Una empresa de terapia celular.",
        "Ahora mismo lo vemos aquí.",
    ],
)
def test_spain_spanish_is_left_alone(text: str) -> None:
    assert scriptwriter.regionalisms(text) == []
    assert scriptwriter.fix_regionalisms(text) == text


def test_regionalisms_are_a_script_problem_and_get_repaired() -> None:
    script = PodcastScript(
        title="t",
        lines=[
            ScriptLine(speaker="A", text="¿Qué ha pasado allá?"),
            ScriptLine(speaker="B", text="El mercado ya lo había precificado."),
        ],
    )
    problems = scriptwriter.script_problems(script, 4.0, length_tolerance=None)
    assert any("otras variantes del español" in p and "«precificado»" in p for p in problems)
    repaired = scriptwriter._repair(script.lines)
    assert [line.text for line in repaired] == ["¿Qué ha pasado allí?", "El mercado ya lo había descontado."]


def test_prompt_asks_for_spain_spanish() -> None:
    system = scriptwriter._render_system(4.0, ("Álvaro", "Elvira"))
    assert "español de España" in system and "precificar" in system and "ahorita" in system


# ── 9. Lecturas que la voz hacía mal (STT sobre el pregenerado) ──────────────────


def test_speech_standard_and_poors_keeps_and() -> None:
    # Sin la regla, «&» se leía «y»: «Standard y Poor's».
    assert normalize_for_speech("El Standard & Poor's 500 sube") == "El Standard and Poor's 500 sube"
    assert normalize_for_speech("Standard&Poors") == "Standard and Poor's"


def test_speech_redeia_pronunciation() -> None:
    # Sin tilde la voz decía «Re-de-i-a» (el STT oía «red y a»).
    assert normalize_for_speech("quitar a Redeia el monopolio") == "quitar a Redéia el monopolio"


def test_speech_invezz_pronunciation() -> None:
    # «Invezz» se leía «Inbex».
    assert normalize_for_speech("Invezz advierte de que") == "Ínvez advierte de que"


def test_speech_pronunciations_are_idempotent() -> None:
    text = "Redeia, Invezz y Standard & Poor's"
    once = normalize_for_speech(text)
    assert normalize_for_speech(once) == once


# ── 10. Verificación del podcast con STT ─────────────────────────────────────────


class FakeSTT(STTProvider):
    """STT «real» falso: devuelve un texto fijo y una duración (para el coste)."""

    provider_name = "openai"

    def __init__(self, text: str, model: str = "gpt-4o-mini-transcribe", fail: bool = False) -> None:
        self.text, self.model, self.fail = text, model, fail
        self.last_duration_s = 0.0
        self.calls: list[Path] = []

    def transcribe(self, audio_path: Path, language: str = "es") -> str:
        self.calls.append(Path(audio_path))
        if self.fail:
            raise ConnectionError("STT caído")
        self.last_duration_s = 300.0
        return self.text


SCRIPT = PodcastScript(
    title="t",
    lines=[
        ScriptLine(speaker="A", text="Hola, esto es Market Briefer."),
        ScriptLine(speaker="B", text="El IBEX 35 sube un 0,53 % y Redeia cae."),
        ScriptLine(speaker="A", text="Gracias por escucharnos."),
    ],
)


def test_wer_tokens_normalize_digits_case_accents_and_punctuation() -> None:
    assert transcript.wer_tokens("El IBEX sube un 0,53%.") == transcript.wer_tokens(
        "el ibex sube un cero coma cincuenta y tres por ciento"
    )
    assert transcript.wer_tokens("En 2026, España") == ["en", "dos", "mil", "veintiseis", "españa"]


def test_word_error_rate_counts_substitutions_deletions_insertions() -> None:
    assert transcript.word_error_rate("uno dos tres cuatro", "uno dos tres cuatro") == 0.0
    assert transcript.word_error_rate("uno dos tres cuatro", "uno tres cuatro") == 0.25  # borrado
    assert transcript.word_error_rate("uno dos tres cuatro", "uno dos dos tres cuatro") == 0.25  # inserción
    assert transcript.word_error_rate("uno dos tres cuatro", "uno seis tres cuatro") == 0.25  # sustitución
    assert transcript.word_error_rate("", "") == 0.0


def test_verify_podcast_perfect_transcription(tmp_path: Path) -> None:
    # El STT escribe cifras y el nombre «real»: la misma normalización a los dos lados.
    stt = FakeSTT("Hola, esto es Market Briefer. El Ibex 35 sube un 0,53% y Redeia cae. Gracias por escucharnos.")
    result = transcript.verify_podcast(tmp_path / "podcast.mp3", SCRIPT, stt)
    assert result.wer == 0.0 and result.errors == 0 and not result.worst_lines
    assert not result.simulated and result.duration_s == 300.0
    assert result.summary().startswith("WER 0,0 % frente al guion")
    assert stt.calls == [tmp_path / "podcast.mp3"]


def test_verify_podcast_reports_worst_lines() -> None:
    stt = FakeSTT("Hola, esto es Market Briefer. El Ibex 35 sube un 0,53% y red y a cae. Gracias por escucharnos.")
    result = transcript.verify_podcast(Path("p.mp3"), SCRIPT, stt)
    assert result.errors == 3  # «redeia» -> «red y a»: 1 sustitución + 2 inserciones
    assert result.wer == round(3 / result.ref_words, 4)
    assert [w.index for w in result.worst_lines] == [1]
    assert result.worst_lines[0].speaker == "B"
    detail = result.summary()
    assert "WER" in detail and "frente al guion" in detail and "línea 2 (3 err.)" in detail


def test_verify_podcast_with_mock_stt_is_marked_simulated() -> None:
    result = transcript.verify_podcast(Path("p.mp3"), SCRIPT, MockSTT())
    assert result.simulated and result.provider == "mock"
    assert "[simulado: STT mock]" in result.summary()


# ── Paso opcional ``media.verify`` en el pipeline ────────────────────────────────


def _settings(tmp_path: Path, **kw) -> Settings:
    return Settings(_env_file=None, briefer_output_dir=tmp_path / "out", briefer_cache_dir=tmp_path / "c", **kw)


def _podcast_metrics(provider: str = "edge") -> list[StepMetric]:
    return [StepMetric(step="media.podcast", provider=provider, model="-", latency_s=1.0)]


AUDIO = AudioAsset(path=Path("podcast.mp3"), duration_s=300.0)


def test_pipeline_verification_records_wer_and_cost(tmp_path: Path) -> None:
    stt = FakeSTT("Hola, esto es Market Briefer. El Ibex 35 sube un 0,53% y Redeia cae. Gracias por escucharnos.")
    future = pipeline._start_podcast_verification(
        _settings(tmp_path), "real", stt, AUDIO, SCRIPT, _podcast_metrics()
    )
    assert future is not None
    (metric,) = future.result(timeout=10)
    assert metric.step == "media.verify" and metric.provider == "openai"
    assert metric.detail.startswith("WER 0,0 % frente al guion")
    assert metric.est_cost_eur > 0 and not step_failed(metric)


def test_pipeline_verification_failure_never_breaks_the_briefing(tmp_path: Path) -> None:
    stt = FakeSTT("", fail=True)
    future = pipeline._start_podcast_verification(
        _settings(tmp_path), "real", stt, AUDIO, SCRIPT, _podcast_metrics()
    )
    (metric,) = future.result(timeout=10)
    assert step_failed(metric) and "ConnectionError" in metric.error


@pytest.mark.parametrize(
    ("mode", "stt", "podcast_provider", "flag"),
    [
        ("mock", FakeSTT("x"), "edge", True),           # modo mock
        ("demo_voices", FakeSTT("x"), "edge", True),    # modo sin claves
        ("real", MockSTT(), "edge", True),              # STT mock
        ("real", FakeSTT("x"), "mock", True),           # el podcast cayó a MockTTS
        ("real", FakeSTT("x"), "edge", False),          # BRIEFER_VERIFY_PODCAST=false
    ],
)
def test_pipeline_verification_is_skipped(tmp_path: Path, mode, stt, podcast_provider, flag) -> None:
    s = _settings(tmp_path, briefer_verify_podcast=flag)
    assert pipeline._start_podcast_verification(s, mode, stt, AUDIO, SCRIPT, _podcast_metrics(podcast_provider)) is None


def test_mock_briefing_has_no_verify_step(tmp_path: Path) -> None:
    briefing = pipeline.run_briefing(["SAN.MC"], settings=_settings(tmp_path), mode="mock")
    assert "media.verify" not in {m.step for m in briefing.metrics}


def test_write_script_does_not_retry_on_auth_error() -> None:
    """Una clave inválida (401) no se arregla reintentando: una sola llamada y guion de respaldo."""
    from briefer.agents import scriptwriter
    from briefer.providers.mock import MockLLM

    class AuthenticationError(Exception):
        status_code = 401

    class FailingLLM(MockLLM):
        calls = 0

        def complete(self, *args, **kwargs):
            FailingLLM.calls += 1
            raise AuthenticationError("invalid x-api-key")

    analysis = MockLLM().complete("", [], response_model=scriptwriter.Analysis)
    trace: list[str] = []
    script = scriptwriter.write_script(analysis, FailingLLM(), max_retries=2, trace=trace)
    assert FailingLLM.calls == 1
    assert script.lines and scriptwriter.FALLBACK_NOTE in trace
    assert any("sin reintento" in note for note in trace)
