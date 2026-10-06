"""Marca Briefly en el carril de locutores y salidas: Toro (A) abre, Osa (B) cierra (sin red)."""

from __future__ import annotations

from datetime import date

from briefer import brand
from briefer.agents import load_prompt, scriptwriter
from briefer.config import Settings
from briefer.delivery.telegram_sender import build_caption
from briefer.media import charts, podcast
from briefer.providers import mock
from briefer.schemas import Briefing, PodcastScript, ScriptLine


def test_default_speakers_come_from_brand() -> None:
    s = Settings(_env_file=None)
    assert (s.briefer_speaker_a_name, s.briefer_speaker_b_name) == (brand.SPEAKER_A_NAME, brand.SPEAKER_B_NAME)
    assert scriptwriter.DEFAULT_SPEAKERS == ("Toro", "Osa")
    # Voces de edge-tts (opción «B» de la cata): A masculina, B femenina, a +10 %.
    assert (s.briefer_voice_a, s.briefer_voice_b) == ("es-ES-AlvaroNeural", "es-ES-XimenaNeural")
    assert s.briefer_tts_rate == "+10%"


def test_prompt_has_night_edition_and_personas() -> None:
    system = scriptwriter._render_system(4.0, scriptwriter.DEFAULT_SPEAKERS)
    assert "{" not in system
    assert brand.BRAND_NAME in system and brand.GREETING in system and "edición de noche" in system
    assert brand.SPEAKER_A_ROLE in system and brand.SPEAKER_B_ROLE in system
    assert "Market Briefer" not in system
    # El cierre lo dice B y se mantienen las reglas de compliance.
    assert "la **última** es de **B — Osa**" in " ".join(system.split())
    assert "Prohibido recomendar" in system and "voces son sintéticas" in system
    # Nombres configurables: con otros nombres no queda rastro de los de la marca.
    other = scriptwriter._render_system(4.0, ("Ana", "Luis"))
    assert "Ana" in other and "Luis" in other and "Toro" not in other and "Osa" not in other


def test_analyst_and_qa_prompts_use_brand() -> None:
    for name in ("analyst", "qa"):
        text = load_prompt(name)
        assert "Briefly" in text and "Market Briefer" not in text
    assert "cada noche" in load_prompt("analyst")


def test_fallback_script_opens_with_night_greeting() -> None:
    analysis = mock.sample_analysis()
    script = scriptwriter.fallback_script(analysis)
    first = script.lines[0]
    assert first.speaker == "A" and first.text.startswith("Buenas noches, soy Toro")
    assert "Briefly" in first.text and "Osa" in script.lines[1].text
    assert script.title == brand.episode_title(analysis.date)


def test_closing_is_always_said_by_osa() -> None:
    analysis = mock.sample_analysis()
    ends_with_a = PodcastScript(title="", lines=[
        ScriptLine(speaker="A", text="Buenas noches, esto es Briefly."),
        ScriptLine(speaker="B", text="Hoy la banca sube."),
        ScriptLine(speaker="A", text="Y eso es todo por hoy."),
    ])
    out = scriptwriter._finalize(ends_with_a, analysis)
    assert out.lines[-1].speaker == "B" and out.lines[-1].text == scriptwriter.CLOSING_LINE_ES
    assert out.title == brand.episode_title(analysis.date)

    ends_with_b = PodcastScript(title="t", lines=[
        ScriptLine(speaker="A", text="Buenas noches, esto es Briefly."),
        ScriptLine(speaker="B", text="Hoy la banca sube."),
    ])
    out = scriptwriter._finalize(ends_with_b, analysis)
    assert [line.speaker for line in out.lines] == ["A", "B"]  # sin dos B seguidas añadidas
    assert out.lines[-1].text.endswith(scriptwriter.CLOSING_LINE_ES)
    assert scriptwriter._has_closing(out.lines)


def test_closing_line_still_detected() -> None:
    line = ScriptLine(speaker="B", text=scriptwriter.CLOSING_LINE_ES)
    assert scriptwriter._has_closing([line])
    assert "Buenas noches" in scriptwriter.CLOSING_LINE_ES


def test_mock_script_is_branded_and_valid() -> None:
    script = mock.sample_script()
    assert script.lines[0].text.startswith(f"{brand.GREETING}, soy {brand.SPEAKER_A_NAME}")
    assert script.lines[-1].speaker == "B" and scriptwriter._has_closing(script.lines)
    assert "Market Briefer" not in " ".join(line.text for line in script.lines)
    assert not scriptwriter.script_problems(script, 4.0, None, reference=scriptwriter.build_user_message(
        mock.sample_analysis()), analysis=mock.sample_analysis())


def test_outputs_carry_brand(sample_briefing: Briefing) -> None:
    assert podcast.AI_AUDIO_METADATA["album"] == "Briefly"
    assert podcast.AI_AUDIO_METADATA["artist"] == "Briefly (voces sintéticas IA)"
    assert charts.FOOTER_NOTE.startswith("Briefly · ")
    assert "Briefly · " in build_caption(sample_briefing)


def test_episode_title_format() -> None:
    assert brand.episode_title(date(2026, 10, 5)) == "Briefly · 05/10/2026"


def test_cartera_gender_agreement_is_fixed() -> None:
    """«vuestro cartera» (visto en real con Haiku) se marca y se corrige."""
    from briefer.agents.guardrails import fix_spoken_text, grammar_issues

    assert grammar_issues("Y en vuestro cartera, quien más brilla es Santander.")
    assert "vuestra cartera" in fix_spoken_text("Y en vuestro cartera, quien más brilla es Santander.")
