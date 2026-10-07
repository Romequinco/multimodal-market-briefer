"""Armazón de la app (``components/shell.py``): vistas registradas, chip del modo, «Quiénes somos», pie
con el aviso legal una sola vez; helpers puros de ``views/archivo.py``. AppTest, sin red ni claves."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("streamlit")

from ui_helpers import APP_DIR, ARCHIVE, ASK, HOY, MAIN, app, disclaimers, html, load_view  # noqa: E402

from briefer import brand  # noqa: E402
from briefer.config import Settings  # noqa: E402
from components import players, shell  # noqa: E402,I001

# ── Vistas registradas ─────────────────────────────────────────────────────────────


def test_three_views_registered_in_order() -> None:
    assert [(title, slug) for _, title, slug, _ in shell.VIEWS] == [
        ("Hoy", "hoy"), ("Preguntar", "preguntar"), ("Archivo", "archivo")]
    assert [path for path, *_ in shell.VIEWS] == [shell.VIEW_HOY, shell.VIEW_ASK, shell.VIEW_ARCHIVE]
    for path, *_ in shell.VIEWS:
        assert (APP_DIR / path).is_file(), path
    # Las rutas de navegación de ``players`` (callbacks) apuntan a las mismas vistas.
    assert (players.PAGE_HOY, players.PAGE_ASK, players.PAGE_HISTORY) == (
        shell.VIEW_HOY, shell.VIEW_ASK, shell.VIEW_ARCHIVE)
    assert not (APP_DIR / "pages").exists(), "sin páginas sueltas: la navegación es st.navigation"


def test_main_has_topbar_tabs_and_no_sidebar() -> None:
    at = app(MAIN).run()
    assert not at.exception
    links = at.get("page_link")
    labels = [p.proto.label for p in links]
    assert labels[:3] == ["Hoy", "Preguntar", "Archivo"]
    assert "Privacidad y mis datos" in labels  # menú ⚙ → Archivo (borrado RGPD)
    assert not at.sidebar.children, "el rediseño no usa barra lateral"
    assert "mb-brand" in html(at)


@pytest.mark.parametrize("view", [HOY, ASK, ARCHIVE])
def test_disclaimer_once_on_every_view(view: str) -> None:
    at = app(MAIN).run()
    at.switch_page(view).run()
    assert not at.exception, at.exception
    assert disclaimers(at) == 1, "el aviso legal (MiFID II) va una sola vez, en el pie"
    footer = "\n".join(c.value for c in at.caption)
    assert brand.COMPLIANCE_MOTTO in footer and "no son personas reales" in footer


@pytest.mark.parametrize("view", [HOY, ASK, ARCHIVE])
def test_views_do_not_repeat_shell_parts(view: str) -> None:
    """Las vistas no pintan disclaimer, tema ni barra lateral: lo hace el armazón."""
    source = (APP_DIR / view).read_text(encoding="utf-8")
    for name in ("show_disclaimer", "apply_theme", "sidebar_mode", "setup_page", "handle_navigation"):
        assert f"{name}(" not in source, f"{view} no debe llamar a {name}"
    at = app(view).run()
    assert not at.exception
    assert disclaimers(at) == 0


# ── Modo de ejecución ──────────────────────────────────────────────────────────────


def test_mode_options_with_and_without_real() -> None:
    assert shell.mode_options(True) == ["real", "demo_voices", "mock"]
    assert shell.mode_options(False) == ["demo_voices", "mock"]
    assert set(shell.MODE_CHIP) == set(players.MODE_LABELS) == {"real", "demo_voices", "mock"}


def test_default_demo_mode_depends_on_explicit_mock_tts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BRIEFER_TTS_PROVIDER", raising=False)
    assert players.default_demo_mode(Settings(_env_file=None)) == "demo_voices"
    assert players.default_demo_mode(Settings(_env_file=None, briefer_tts_provider="mock")) == "mock"


def _mode_script(app_dir: str) -> None:
    import sys

    if app_dir not in sys.path:
        sys.path.insert(0, app_dir)
    import streamlit as st

    from components.shell import current_mode

    st.write(current_mode())


def _current_mode(state: dict | None = None) -> str:
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_function(_mode_script, args=(str(APP_DIR),), default_timeout=30)
    for k, v in (state or {}).items():
        at.session_state[k] = v
    at.run()
    assert not at.exception
    return at.markdown[0].value


def test_current_mode_default_and_session() -> None:
    assert _current_mode() == "mock"  # BRIEFER_TTS_PROVIDER=mock explícito (tests): demo offline
    assert _current_mode({"run_mode": "demo_voices"}) == "demo_voices"
    assert _current_mode({"run_mode": "real"}) == "real"
    assert _current_mode({"run_mode": "inventado"}) == "mock"


def test_mode_chip_real_when_keys_available(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shell, "real_mode_available", lambda: (True, ""))
    at = app(MAIN).run()
    radio = at.radio(key="mb_mode_choice")
    assert radio.options[0] == players.MODE_LABELS["real"]
    assert radio.value == "mock"  # se empieza en demo aunque haya claves
    radio.set_value("real").run()
    assert not at.exception
    assert at.session_state["run_mode"] == "real" and at.session_state["use_mock"] is False
    assert at.get("popover")[0].proto.popover.label == "Real"


def test_real_password_pure_helpers() -> None:
    locked = Settings(briefer_real_mode_password="s3creta")
    assert shell.real_password_required(locked)
    assert shell.check_real_password("s3creta", locked)
    assert shell.check_real_password("  s3creta ", locked)  # espacios al copiar y pegar
    assert not shell.check_real_password("otra", locked)
    open_ = Settings(briefer_real_mode_password="")
    assert not shell.real_password_required(open_)
    assert not shell.check_real_password("", open_)  # sin contraseña configurada nunca «acierta»


@pytest.fixture
def real_password(monkeypatch: pytest.MonkeyPatch):
    from briefer.config import reset_settings_cache

    monkeypatch.setattr(shell, "real_mode_available", lambda: (True, ""))
    monkeypatch.setenv("BRIEFER_REAL_MODE_PASSWORD", "s3creta")
    reset_settings_cache()
    yield "s3creta"
    monkeypatch.delenv("BRIEFER_REAL_MODE_PASSWORD")
    reset_settings_cache()


def test_real_mode_needs_password_when_configured(real_password: str) -> None:
    at = app(MAIN).run()
    at.radio(key="mb_mode_choice").set_value("real").run()
    assert not at.exception
    # Elegido «Real» pero bloqueado: se sigue en demo y aparece el campo de contraseña.
    assert at.session_state["run_mode"] == "mock" and at.session_state["use_mock"] is True
    assert at.get("popover")[0].proto.popover.label == "Demo offline"
    at.text_input(key="mb_real_pwd").input("mala")
    at.button(key="mb_real_unlock").click().run()
    assert at.session_state["run_mode"] == "mock"
    assert any("Contraseña incorrecta" in c.value for c in at.caption)
    at.text_input(key="mb_real_pwd").input(real_password)
    at.button(key="mb_real_unlock").click().run()
    assert not at.exception
    assert at.session_state["run_mode"] == "real" and at.session_state["use_mock"] is False
    assert at.get("popover")[0].proto.popover.label == "Real"
    assert at.session_state["mb_real_pwd"] == ""  # la contraseña no se queda en el campo


def test_real_password_attempts_are_limited(real_password: str) -> None:
    at = app(MAIN).run()
    at.radio(key="mb_mode_choice").set_value("real").run()
    for _ in range(shell.MAX_REAL_ATTEMPTS):
        at.text_input(key="mb_real_pwd").input("mala")
        at.button(key="mb_real_unlock").click().run()
    assert not at.exception
    assert any("Demasiados intentos" in e.value for e in at.error)
    assert all(field.key != "mb_real_pwd" for field in at.text_input)  # el formulario de contraseña desaparece
    assert at.session_state["run_mode"] == "mock"


def test_mode_chip_survives_view_changes() -> None:
    at = app(MAIN).run()
    at.radio(key="mb_mode_choice").set_value("demo_voices").run()
    at.switch_page(ARCHIVE).run()
    assert not at.exception
    assert at.session_state["run_mode"] == "demo_voices"
    assert at.get("popover")[0].proto.popover.label == "Demo · voces reales"


# ── Quiénes somos ──────────────────────────────────────────────────────────────────


def test_about_hosts_are_toro_and_osa_with_synthetic_voice() -> None:
    names = [h[0] for h in shell.ABOUT_HOSTS]
    assert names == [brand.SPEAKER_A_NAME, brand.SPEAKER_B_NAME] == ["Toro", "Osa"]
    cards = [shell.host_html(*h) for h in shell.ABOUT_HOSTS]
    assert all("sintética (IA)" in c for c in cards)
    assert "mb-host__badge--b" in cards[1] and "mb-host__badge--b" not in cards[0]
    assert brand.COMPLIANCE_MOTTO in [t for t, _ in shell.ABOUT_VALUES]


# ── Archivo: helpers puros ─────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def archivo() -> dict:
    return load_view(ARCHIVE)


def _summary(archivo: dict, **kw):
    storage = archivo["storage"]
    base = dict(path=Path("x/briefing.json"), id="20261006-160000-aaaaaa", created_at="2026-10-06T16:00:00",
                headline="Iberdrola sube", tickers=["IBE.MC"], duration_s=125.0, has_audio=True, demo=False)
    base.update(kw)
    return storage.BriefingSummary(**base)


def test_filter_summaries_by_text_and_kind(archivo: dict) -> None:
    f = archivo["filter_summaries"]
    real = _summary(archivo)
    demo = _summary(archivo, id="20261005-090000-bbbbbb", created_at="2026-10-05T09:00:00",
                    headline="Miércoles tranquilo en Wall Street", tickers=["AAPL", "NVDA"], demo=True)
    mute = _summary(archivo, id="20261004-090000-cccccc", created_at="2026-10-04T09:00:00",
                    headline="Sin voz", has_audio=False)
    broken = _summary(archivo, id="20261003-090000-dddddd", created_at="", headline="", tickers=[],
                      error="ValueError: x")
    items = [real, demo, mute, broken]
    assert f(items, "", "Todos") == items and f(items, "", None) == items
    assert f(items, "IBERDROLA", "Todos") == [real]               # sin distinguir mayúsculas
    assert f(items, "miercoles", None) == [demo]                   # ni tildes
    assert f(items, "nvda wall", None) == [demo]                   # todas las palabras
    assert f(items, "nvda iberdrola", None) == []
    assert f(items, "06/10/2026", None) == [real]                  # por fecha
    assert f(items, "2026-10-05", None) == [demo]
    assert f(items, "", "Con audio") == [real, demo]               # sin roto ni sin audio
    assert f(items, "", "Demo") == [demo]


def test_card_html_escapes_and_tags(archivo: dict) -> None:
    card = archivo["card_html"]
    evil = _summary(archivo, headline="<script>x</script>", tickers=[f"T{i}" for i in range(10)], demo=True,
                    has_audio=False)
    out = card(evil, active=True)
    assert "<script>" not in out and "&lt;script&gt;" in out
    assert "Sin audio" in out and "Demo" in out and "● abierto" in out
    assert "+2" in out  # más de 8 valores: se resumen
    assert "MAR · 06/10/2026 · 16:00" in card(_summary(archivo), active=False)
    assert "2:05 min" in card(_summary(archivo), active=False)
    broken = card(_summary(archivo, error="ValueError: x"), active=False)
    assert "Briefing no disponible" in broken and "No disponible" in broken and "Puedes borrarlo" in broken
