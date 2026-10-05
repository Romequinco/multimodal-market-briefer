"""Normalización de texto para la locución (``media.speech`` / ``podcast.normalize_for_speech``)."""

from __future__ import annotations

from pathlib import Path

import pytest

from briefer.media import podcast
from briefer.media.speech import decimal_to_words, normalize_for_speech, number_to_words
from briefer.providers.mock import MockTTS
from briefer.schemas import PodcastScript, ScriptLine

# ── Números ────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "n,words",
    [
        (0, "cero"), (1, "uno"), (7, "siete"), (15, "quince"), (16, "dieciséis"), (21, "veintiuno"),
        (22, "veintidós"), (30, "treinta"), (31, "treinta y uno"), (99, "noventa y nueve"),
        (100, "cien"), (101, "ciento uno"), (115, "ciento quince"), (200, "doscientos"),
        (555, "quinientos cincuenta y cinco"), (1000, "mil"), (1001, "mil uno"),
        (2026, "dos mil veintiséis"), (21000, "veintiún mil"), (100000, "cien mil"),
        (1_000_000, "un millón"), (2_500_000, "dos millones quinientos mil"),
        (1_000_000_000, "mil millones"), (3_200_000_000, "tres mil doscientos millones"),
        (-5, "menos cinco"),
    ],
)
def test_number_to_words(n: int, words: str) -> None:
    assert number_to_words(n) == words


@pytest.mark.parametrize("n,words", [(1, "un"), (21, "veintiún"), (31, "treinta y un"), (101, "ciento un"),
                                     (5, "cinco")])
def test_number_to_words_apocope(n: int, words: str) -> None:
    assert number_to_words(n, apocope=True) == words


@pytest.mark.parametrize(
    "raw,words",
    [
        ("1,23", "uno coma veintitrés"), ("1,5", "uno coma cinco"), ("0,8", "cero coma ocho"),
        ("1,05", "uno coma cero cinco"), ("3,141", "tres coma uno cuatro uno"), ("1.5", "uno coma cinco"),
        ("0.81", "cero coma ochenta y uno"), ("1.200", "mil doscientos"), ("10.000", "diez mil"),
        ("1.234,5", "mil doscientos treinta y cuatro coma cinco"), ("2,00", "dos"), ("12", "doce"),
    ],
)
def test_decimal_to_words(raw: str, words: str) -> None:
    assert decimal_to_words(raw) == words


# ── Casos del roadmap y de la tarea ────────────────────────────────────────────────


@pytest.mark.parametrize(
    "text,expected",
    [
        # Tickers -> nombre de empresa (TICKER_UNIVERSE)
        ("SAN.MC sube", "Banco Santander sube"),
        ("ITX.MC e IBE.MC", "Inditex e Iberdrola"),
        ("$NVDA y AAPL", "Nvidia y Apple"),
        ("MSFT recupera", "Microsoft recupera"),
        ("Santander (SAN.MC) gana", "Santander gana"),
        ("el banco (SAN.MC) gana", "el banco (Banco Santander) gana"),
        ("El ^IBEX cede", "El Ibex 35 cede"),
        # Porcentajes con signo
        ("+1,23 %", "más uno coma veintitrés por ciento"),
        ("sube un +1,23 % hoy", "sube un más uno coma veintitrés por ciento hoy"),
        ("cae −0,8%", "cae menos cero coma ocho por ciento"),
        ("cae -3,5%,", "cae menos tres coma cinco por ciento,"),
        ("1,5 %", "uno coma cinco por ciento"),
        ("un 1.5%", "un uno coma cinco por ciento"),
        ("(+2%)", "(más dos por ciento)"),
        ("entre el 1-2 %", "entre el uno a dos por ciento"),
        ("un 100%", "un cien por ciento"),
        # Importes y magnitudes
        ("1.200 M€", "mil doscientos millones de euros"),
        ("1 M€", "un millón de euros"),
        ("21 M€", "veintiún millones de euros"),
        ("12,5 €", "doce coma cinco euros"),
        ("1 €", "un euro"),
        ("€12,5", "doce coma cinco euros"),
        ("$3bn", "tres mil millones de dólares"),
        ("35 bn $", "treinta y cinco mil millones de dólares"),
        ("3 bn", "tres mil millones"),
        ("2.000 MM€", "dos mil mil millones de euros"),
        ("500 k€", "quinientos mil euros"),
        ("1.000.000 €", "un millón de euros"),
        ("0,21 €", "cero coma veintiuno euros"),
        ("15 USD", "quince dólares"),
        ("+120 M€", "más ciento veinte millones de euros"),
        # Periodos
        ("3T 2026", "tercer trimestre de dos mil veintiséis"),
        ("en el 3T26", "en el tercer trimestre de dos mil veintiséis"),
        ("Q3 2026", "tercer trimestre de dos mil veintiséis"),
        ("el T4", "el cuarto trimestre"),
        ("1T", "primer trimestre"),
        ("1S 2026", "primer semestre de dos mil veintiséis"),
        ("H2 2025", "segundo semestre de dos mil veinticinco"),
        # Fechas
        ("05/10/2026", "cinco de octubre de dos mil veintiséis"),
        ("2026-10-01", "uno de octubre de dos mil veintiséis"),
        ("el 31/12/25", "el treinta y uno de diciembre de dos mil veinticinco"),
        # Abreviaturas
        ("El IBEX 35", "El Ibex 35"),
        ("el BCE y la Fed", "el Banco Central Europeo y la Reserva Federal"),
        ("EPS de", "beneficio por acción de"),
        ("BPA", "beneficio por acción"),
        ("margen EBITDA", "margen ebitda"),
        ("EE. UU. vs. UE", "Estados Unidos frente a Unión Europea"),
        ("EE.UU.", "Estados Unidos"),
        ("10 pb", "diez puntos básicos"),
        ("1 pb", "un punto básico"),
        ("0,5 pp", "cero coma cinco puntos porcentuales"),
        ("el CEO", "el consejero delegado"),
        ("crece un 5% a/a", "crece un cinco por ciento interanual"),
        # Números sueltos
        ("10.000 acciones", "10000 acciones"),
        ("cotiza a 15,32", "cotiza a quince coma treinta y dos"),
    ],
)
def test_normalize_for_speech(text: str, expected: str) -> None:
    assert normalize_for_speech(text) == expected


def test_roadmap_acceptance_examples() -> None:
    """Criterio de 05_roadmap: «SAN.MC» → Santander, «1,5 %» → uno coma cinco, «Q3» → tercer trimestre."""
    out = normalize_for_speech("SAN.MC sube un 1,5 % en el Q3.")
    assert "Santander" in out
    assert "uno coma cinco por ciento" in out
    assert "tercer trimestre" in out
    assert "SAN.MC" not in out and "%" not in out


def test_full_line() -> None:
    line = "Santander (SAN.MC) sube un +1,23 % tras ganar 3.250 M€ en el 3T 2026; el BCE decide el 15/10/2026."
    assert normalize_for_speech(line) == (
        "Santander sube un más uno coma veintitrés por ciento tras ganar tres mil doscientos cincuenta "
        "millones de euros en el tercer trimestre de dos mil veintiséis; el Banco Central Europeo decide "
        "el quince de octubre de dos mil veintiséis."
    )


@pytest.mark.parametrize(
    "text",
    [
        "Buenas noches, esto es el cierre del lunes.",
        "Hola, ¿qué tal? ¡Bien!",
        "San Sebastián y el sector de la banca.",
        "Meta de ventas y el santander de siempre.",
        "En 2026 hubo 3 subidas.",
        "Fecha imposible 45/13/2026.",
    ],
)
def test_text_without_patterns_is_unchanged(text: str) -> None:
    assert normalize_for_speech(text) == text


@pytest.mark.parametrize(
    "text",
    [
        "SAN.MC sube un +1,23 % y gana 1.200 M€ en el 3T 2026.",
        "$NVDA ingresó $35bn con un EPS de 0.81 dólares; EE. UU. vs. UE.",
        "El IBEX 35 y el BCE, 10 pb, 05/10/2026, Q3, H1 2026, 1.000.000 €.",
    ],
)
def test_idempotent(text: str) -> None:
    once = normalize_for_speech(text)
    assert normalize_for_speech(once) == once


@pytest.mark.parametrize("text", ["", "   "])
def test_empty_text_returned_as_is(text: str) -> None:
    assert normalize_for_speech(text) == text


def test_no_symbols_left_for_tts() -> None:
    out = normalize_for_speech("AAPL +2%, ITX.MC -0,8 %, 12 € y $5 · S&P 500 & Nasdaq")
    for symbol in ("%", "€", "$", "&", ".MC"):
        assert symbol not in out


def test_podcast_exports_normalize_for_speech() -> None:
    assert podcast.normalize_for_speech is normalize_for_speech


# ── Integración con synthesize_podcast ─────────────────────────────────────────────


class RecordingTTS(MockTTS):
    """``MockTTS`` que registra el texto recibido (lo que se «leería»)."""

    def __init__(self) -> None:
        super().__init__()
        self.texts: list[str] = []

    def synthesize(self, text: str, voice: str, out_path: Path) -> Path:
        self.texts.append(text)
        return super().synthesize(text, voice, out_path)


def _script() -> PodcastScript:
    return PodcastScript(
        title="Normalización",
        lines=[
            ScriptLine(speaker="A", text="SAN.MC sube un +1,23 %."),
            ScriptLine(speaker="B", text="Y AAPL gana $3bn en el Q3."),
        ],
    )


def test_synthesize_podcast_normalizes_tts_text_but_keeps_original_segments(tmp_path: Path) -> None:
    tts = RecordingTTS()
    audio = podcast.synthesize_podcast(_script(), tts, tmp_path, "a", "b", max_workers=1)
    assert tts.texts == [
        "Banco Santander sube un más uno coma veintitrés por ciento.",
        "Y Apple gana tres mil millones de dólares en el tercer trimestre.",
    ]
    # Transcripción/SRT: texto original del guion
    assert [s.text for s in audio.segments] == ["SAN.MC sube un +1,23 %.", "Y AAPL gana $3bn en el Q3."]


def test_synthesize_podcast_normalize_can_be_disabled(tmp_path: Path) -> None:
    tts = RecordingTTS()
    podcast.synthesize_podcast(_script(), tts, tmp_path, "a", "b", max_workers=1, normalize=False)
    assert tts.texts == ["SAN.MC sube un +1,23 %.", "Y AAPL gana $3bn en el Q3."]


def test_transcript_srt_keeps_original_text(tmp_path: Path) -> None:
    from briefer.media import transcript

    script = _script()
    audio = podcast.synthesize_podcast(script, MockTTS(), tmp_path, "a", "b")
    tr = transcript.build_transcript(script, audio.segments, tmp_path)
    srt = Path(tr.srt_path).read_text(encoding="utf-8")
    assert "SAN.MC sube un +1,23 %." in srt
    assert "SAN.MC" in tr.text
