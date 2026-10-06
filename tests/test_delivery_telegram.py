"""Envío por Telegram (``delivery.telegram_sender``) y ``scripts/telegram_setup.py``, sin red.

``requests.post`` se sustituye por un falso que registra método, datos y fichero subido. Se comprueba
que el token (que va en la URL) nunca aparece en ``detail``, en los mensajes de error ni en el log.
"""

from __future__ import annotations

import importlib.util
import logging
import sys
from pathlib import Path
from typing import Any

import pytest
import requests
from pydantic import SecretStr

from briefer.config import ROOT_DIR, Settings
from briefer.delivery import telegram_sender as tg
from briefer.schemas import Briefing, ChartAsset

TOKEN = "123456789:AAEabcdefghijklmnopqrstuvwxyz0123456"
CHAT = "987654321"


class FakeResp:
    def __init__(self, payload: Any, status: int = 200) -> None:
        self._payload = payload
        self.status_code = status

    def json(self) -> Any:
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeTelegram:
    """Sustituto de ``requests.post``: responde por método (lista de respuestas o callable)."""

    def __init__(self, responses: dict[str, list[Any]] | None = None) -> None:
        self.responses = responses or {}
        self.calls: list[dict[str, Any]] = []

    def __call__(self, url: str, data: Any = None, files: Any = None, timeout: Any = None) -> FakeResp:
        method = url.rsplit("/", 1)[-1]
        call = {"url": url, "method": method, "data": dict(data or {}), "timeout": timeout, "file": None}
        if files:
            (field, (name, fh)), = files.items()
            call["file"] = (field, name, fh.read())
        self.calls.append(call)
        queue = self.responses.get(method)
        if queue:
            item = queue.pop(0)
            if isinstance(item, Exception):
                raise item
            return item
        return FakeResp({"ok": True, "result": {"message_id": len(self.calls)}})

    @property
    def methods(self) -> list[str]:
        return [c["method"] for c in self.calls]


def _settings(tmp_path: Path, token: str | None = TOKEN, chat: str | None = CHAT) -> Settings:
    return Settings(
        _env_file=None,
        telegram_bot_token=SecretStr(token) if token is not None else None,
        telegram_chat_id=chat,
        briefer_output_dir=tmp_path / "outputs",
        briefer_cache_dir=tmp_path / "cache",
    )


def _with_files(b: Briefing, tmp_path: Path, *, cover: bool = True) -> Briefing:
    """Crea en disco los ficheros del briefing de ejemplo (+ portada y gráfico general)."""
    assert b.audio is not None and b.video is not None
    b.audio.path.write_bytes(b"ID3audio")
    b.video.path.write_bytes(b"mp4video")
    overview = tmp_path / "overview_change.png"
    overview.write_bytes(b"PNGoverview")
    b.charts = [*b.charts, ChartAsset(path=overview, kind="overview_bar")]
    if cover:
        b.cover_path = tmp_path / "cover.png"
        b.cover_path.write_bytes(b"PNGcover")
    return b


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeTelegram:
    f = FakeTelegram()
    monkeypatch.setattr(tg.requests, "post", f)
    monkeypatch.setattr(tg.time, "sleep", lambda s: None)
    return f


# ── No configurado ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(("token", "chat"), [(None, CHAT), (TOKEN, None), ("", CHAT), (TOKEN, "  ")])
def test_not_configured_returns_result_without_network(sample_briefing, tmp_path, fake, token, chat):
    r = tg.send_briefing_telegram(sample_briefing, settings=_settings(tmp_path, token, chat))
    assert (r.channel, r.ok, r.detail) == ("telegram", False, "Telegram no configurado")
    assert fake.calls == []


def test_chat_id_argument_overrides_settings(sample_briefing, tmp_path, fake):
    r = tg.send_briefing_telegram(sample_briefing, chat_id="42", settings=_settings(tmp_path, chat=None))
    assert r.ok
    assert fake.calls[0]["data"]["chat_id"] == "42"


# ── Envío completo ─────────────────────────────────────────────────────────────────


def test_full_send_message_audio_photo_video(sample_briefing, tmp_path, fake):
    b = _with_files(sample_briefing, tmp_path)
    r = tg.send_briefing_telegram(b, settings=_settings(tmp_path))

    assert r.ok and r.channel == "telegram"
    assert r.detail == "Enviado a Telegram: mensaje, audio, imagen, vídeo"
    assert fake.methods == ["sendMessage", "sendAudio", "sendPhoto", "sendVideo"]
    msg, audio, photo, video = fake.calls
    assert all(c["url"].startswith("https://api.telegram.org/bot") for c in fake.calls)
    assert all(c["data"]["chat_id"] == CHAT and c["timeout"] for c in fake.calls)

    assert msg["data"]["parse_mode"] == "HTML"
    assert msg["data"]["text"] == tg.build_caption(b, max_len=tg.MAX_MESSAGE_CHARS)
    assert "Voces sintéticas" in msg["data"]["text"] and "<b>Titular</b>" in msg["data"]["text"]

    assert audio["file"] == ("audio", "podcast.mp3", b"ID3audio")
    assert audio["data"]["title"] == "Briefly · 05/10/2026"
    assert audio["data"]["performer"] == "Briefly · voces sintéticas IA"
    assert audio["data"]["duration"] == "2"

    assert photo["file"] == ("photo", "cover.png", b"PNGcover")  # la portada gana al gráfico
    assert "Imagen generada por IA" in photo["data"]["caption"]  # AI Act art. 50
    assert video["file"] == ("video", "v.mp4", b"mp4video")
    assert video["data"]["supports_streaming"] == "true"


def test_photo_falls_back_to_overview_chart(sample_briefing, tmp_path, fake):
    b = _with_files(sample_briefing, tmp_path, cover=False)
    tg.send_briefing_telegram(b, settings=_settings(tmp_path))
    photo = next(c for c in fake.calls if c["method"] == "sendPhoto")
    assert photo["file"] == ("photo", "overview_change.png", b"PNGoverview")
    assert "generada por IA" not in photo["data"]["caption"]  # el gráfico no es imagen generativa


def test_missing_files_are_skipped_silently(sample_briefing, tmp_path, fake):
    # Los ficheros del briefing de ejemplo no existen y no hay gráfico general: solo el mensaje.
    r = tg.send_briefing_telegram(sample_briefing, settings=_settings(tmp_path))
    assert r.ok and r.detail == "Enviado a Telegram: mensaje"
    assert fake.methods == ["sendMessage"]


def test_relative_paths_resolve_against_briefing_folder(sample_briefing, tmp_path, fake):
    s = _settings(tmp_path)
    folder = s.output_path / sample_briefing.id
    folder.mkdir(parents=True)
    (folder / "podcast.mp3").write_bytes(b"rel")
    assert sample_briefing.audio is not None
    sample_briefing.audio.path = Path("podcast.mp3")
    sample_briefing.video = None
    tg.send_briefing_telegram(sample_briefing, settings=s)
    assert fake.methods == ["sendMessage", "sendAudio"]
    assert fake.calls[1]["file"][2] == b"rel"


# ── Fallos ─────────────────────────────────────────────────────────────────────────


def test_partial_failure_keeps_ok_and_reports(sample_briefing, tmp_path, fake):
    b = _with_files(sample_briefing, tmp_path)
    fake.responses["sendVideo"] = [FakeResp({"ok": False, "error_code": 400, "description": "Bad Request: wrong file"}, 400)]
    fake.responses["sendPhoto"] = [requests.ConnectionError(f"https://api.telegram.org/bot{TOKEN}/sendPhoto caído")]
    r = tg.send_briefing_telegram(b, settings=_settings(tmp_path))
    assert r.ok
    assert r.detail.startswith("Enviado a Telegram: mensaje, audio.")
    assert "imagen no enviado" in r.detail and "vídeo no enviado" in r.detail and "wrong file" in r.detail
    assert TOKEN not in r.detail and TOKEN.split(":")[1] not in r.detail


def test_message_failure_is_not_ok_and_stops(sample_briefing, tmp_path, fake):
    b = _with_files(sample_briefing, tmp_path)
    fake.responses["sendMessage"] = [FakeResp({"ok": False, "error_code": 403, "description": "Forbidden: bot was blocked by the user"}, 403)]
    r = tg.send_briefing_telegram(b, settings=_settings(tmp_path))
    assert not r.ok and "Error al enviar el mensaje" in r.detail and "blocked" in r.detail
    assert fake.methods == ["sendMessage"]


def test_non_json_response_is_an_error(sample_briefing, tmp_path, fake):
    fake.responses["sendMessage"] = [FakeResp(ValueError("no json"), 502)]
    r = tg.send_briefing_telegram(sample_briefing, settings=_settings(tmp_path))
    assert not r.ok and "HTTP 502" in r.detail


def test_429_retries_once_after_retry_after(sample_briefing, tmp_path, fake, monkeypatch):
    waits: list[float] = []
    monkeypatch.setattr(tg.time, "sleep", waits.append)
    fake.responses["sendMessage"] = [
        FakeResp({"ok": False, "error_code": 429, "description": "Too Many Requests: retry after 2",
                  "parameters": {"retry_after": 2}}, 429),
    ]
    r = tg.send_briefing_telegram(sample_briefing, settings=_settings(tmp_path))
    assert r.ok and waits == [2.0]
    assert fake.methods == ["sendMessage", "sendMessage"]


def test_429_twice_or_long_wait_gives_up(sample_briefing, tmp_path, fake, monkeypatch):
    waits: list[float] = []
    monkeypatch.setattr(tg.time, "sleep", waits.append)
    too_many = {"ok": False, "error_code": 429, "description": "Too Many Requests", "parameters": {"retry_after": 1}}
    fake.responses["sendMessage"] = [FakeResp(too_many, 429), FakeResp(too_many, 429)]
    r = tg.send_briefing_telegram(sample_briefing, settings=_settings(tmp_path))
    assert not r.ok and "429" in r.detail and len(fake.calls) == 2 and waits == [1.0]

    fake.calls.clear()
    waits.clear()
    fake.responses["sendMessage"] = [FakeResp({**too_many, "parameters": {"retry_after": 600}}, 429)]
    r = tg.send_briefing_telegram(sample_briefing, settings=_settings(tmp_path))
    assert not r.ok and len(fake.calls) == 1 and waits == []


def test_retry_reopens_file(sample_briefing, tmp_path, fake):
    b = _with_files(sample_briefing, tmp_path)
    fake.responses["sendAudio"] = [FakeResp({"ok": False, "error_code": 429, "parameters": {"retry_after": 0}}, 429)]
    r = tg.send_briefing_telegram(b, settings=_settings(tmp_path))
    audios = [c for c in fake.calls if c["method"] == "sendAudio"]
    assert r.ok and len(audios) == 2 and audios[1]["file"][2] == b"ID3audio"


def test_audio_over_50mb_is_skipped(sample_briefing, tmp_path, fake, monkeypatch):
    b = _with_files(sample_briefing, tmp_path)
    monkeypatch.setattr(tg, "MAX_UPLOAD_BYTES", 4)  # el audio (8 bytes) y el vídeo no caben
    r = tg.send_briefing_telegram(b, settings=_settings(tmp_path))
    assert r.ok
    assert "sendAudio" not in fake.methods and "sendVideo" not in fake.methods
    assert "audio omitido" in r.detail and "vídeo omitido" in r.detail
    assert "sendPhoto" in fake.methods  # la imagen tiene su propio límite (10 MB)


def test_audio_over_limit_real_constant(sample_briefing, tmp_path, fake):
    b = _with_files(sample_briefing, tmp_path)
    assert b.audio is not None
    with open(b.audio.path, "wb") as fh:  # fichero disperso de 51 MB (no ocupa disco real)
        fh.seek(51 * 1024 * 1024)
        fh.write(b"\0")
    r = tg.send_briefing_telegram(b, settings=_settings(tmp_path))
    assert r.ok and "sendAudio" not in fake.methods
    assert "audio omitido (51,0 MB > 50 MB)" in r.detail
    assert "sendVideo" in fake.methods


# ── El token nunca sale ────────────────────────────────────────────────────────────


def test_token_never_in_detail_or_log(sample_briefing, tmp_path, fake, caplog):
    b = _with_files(sample_briefing, tmp_path)
    url = f"https://api.telegram.org/bot{TOKEN}"
    fake.responses["sendAudio"] = [requests.ConnectionError(f"Max retries exceeded with url: {url}/sendAudio")]
    fake.responses["sendPhoto"] = [FakeResp({"ok": False, "error_code": 400, "description": f"echo {TOKEN}"}, 400)]
    fake.responses["sendVideo"] = [requests.Timeout(f"{url}/sendVideo " + "x" * 150 + TOKEN)]
    with caplog.at_level(logging.DEBUG, logger="briefer"):
        r = tg.send_briefing_telegram(b, settings=_settings(tmp_path))
    assert r.ok and "audio no enviado" in r.detail and "ConnectionError" in r.detail
    secret_part = TOKEN.split(":")[1]
    for text in (r.detail, caplog.text):
        assert TOKEN not in text and secret_part not in text

    fake.responses["sendMessage"] = [requests.ConnectionError(f"{url}/sendMessage refused")]
    with caplog.at_level(logging.DEBUG, logger="briefer"):
        r = tg.send_briefing_telegram(b, settings=_settings(tmp_path))
    assert not r.ok
    for text in (r.detail, caplog.text):
        assert TOKEN not in text and secret_part not in text


def test_token_redacted_even_with_unusual_format(sample_briefing, tmp_path, fake):
    odd = "token-raro-sin-formato-de-bot"  # no lo cubre ningún patrón: se quita por valor literal
    fake.responses["sendMessage"] = [requests.ConnectionError(f"https://api.telegram.org/bot{odd}/sendMessage")]
    r = tg.send_briefing_telegram(sample_briefing, settings=_settings(tmp_path, token=odd))
    assert not r.ok and odd not in r.detail


# ── scripts/telegram_setup.py ──────────────────────────────────────────────────────


@pytest.fixture
def setup_mod():
    path = ROOT_DIR / "scripts" / "telegram_setup.py"
    spec = importlib.util.spec_from_file_location("telegram_setup_test", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    try:
        spec.loader.exec_module(mod)
        yield mod
    finally:
        sys.modules.pop(spec.name, None)


UPDATES = [
    {"update_id": 1, "message": {"chat": {"id": 111, "type": "private", "first_name": "Ana", "last_name": "Gil",
                                          "username": "anagil"}, "text": "/start"}},
    {"update_id": 2, "message": {"chat": {"id": -100222, "type": "supergroup", "title": "Club MIAX"}, "text": "hola"}},
    {"update_id": 3, "edited_message": {"chat": {"id": 111, "type": "private", "first_name": "Ana"}}},
    {"update_id": 4, "my_chat_member": {"chat": {"id": -333, "type": "group", "title": "Grupo"}}},
    {"update_id": 5, "callback_query": {"message": {"chat": {"id": 444, "type": "private", "username": "solo"}}}},
    {"update_id": 6, "poll": {"id": "x"}},
]


def test_parse_chats(setup_mod):
    chats = setup_mod.parse_chats(UPDATES)
    by_id = {c.id: c for c in chats}
    assert set(by_id) == {"111", "-100222", "-333", "444"}
    assert by_id["-100222"].type == "supergroup" and by_id["-100222"].name == "Club MIAX"
    assert by_id["444"].name == "@solo"
    assert chats[-1].id == "444"
    assert setup_mod.parse_chats([]) == []


def test_write_env_value_preserves_other_lines(setup_mod, tmp_path):
    env = tmp_path / ".env"
    env.write_text("# comentario\nANTHROPIC_API_KEY=sk-x\n# TELEGRAM_CHAT_ID=viejo\nTELEGRAM_CHAT_ID=\nOTRA=1", encoding="utf-8")
    setup_mod.write_env_value(env, "TELEGRAM_CHAT_ID", "111")
    assert env.read_text(encoding="utf-8") == (
        "# comentario\nANTHROPIC_API_KEY=sk-x\n# TELEGRAM_CHAT_ID=viejo\nTELEGRAM_CHAT_ID=111\nOTRA=1"
    )
    other = tmp_path / "otro.env"
    other.write_bytes(b"A=1\r\nB=2")
    setup_mod.write_env_value(other, "TELEGRAM_CHAT_ID", "-5")
    assert other.read_bytes() == b"A=1\r\nB=2\r\nTELEGRAM_CHAT_ID=-5\r\n"


def _patch_api(monkeypatch, updates):
    fake = FakeTelegram({
        "getMe": [FakeResp({"ok": True, "result": {"username": "briefly_bot", "first_name": "Briefly"}})],
        "getUpdates": [FakeResp({"ok": True, "result": updates})],
    })
    monkeypatch.setattr(tg.requests, "post", fake)
    return fake


def test_setup_write_single_chat(setup_mod, tmp_path, monkeypatch, capsys):
    env = tmp_path / ".env"
    env.write_text(f"TELEGRAM_BOT_TOKEN={TOKEN}\nTELEGRAM_CHAT_ID=\n", encoding="utf-8")
    fake = _patch_api(monkeypatch, UPDATES[:1])
    code = setup_mod.main(["--write", "--test", "--env-file", str(env)], settings=_settings(tmp_path, chat=None))
    out = capsys.readouterr().out
    assert code == 0
    assert env.read_text(encoding="utf-8") == f"TELEGRAM_BOT_TOKEN={TOKEN}\nTELEGRAM_CHAT_ID=111\n"
    assert fake.methods == ["getMe", "getUpdates", "sendMessage"]
    assert fake.calls[-1]["data"]["chat_id"] == "111"
    assert "@briefly_bot" in out and "Ana Gil (@anagil)" in out
    assert TOKEN not in out and TOKEN.split(":")[1] not in out


def test_setup_several_chats_needs_chat_id(setup_mod, tmp_path, monkeypatch, capsys):
    env = tmp_path / ".env"
    env.write_text("X=1\n", encoding="utf-8")
    _patch_api(monkeypatch, UPDATES)
    assert setup_mod.main(["--write", "--env-file", str(env)], settings=_settings(tmp_path)) == 1
    assert env.read_text(encoding="utf-8") == "X=1\n"
    assert "--chat-id" in capsys.readouterr().out

    _patch_api(monkeypatch, UPDATES)
    assert setup_mod.main(["--write", "--chat-id", "-100222", "--env-file", str(env)], settings=_settings(tmp_path)) == 0
    assert env.read_text(encoding="utf-8") == "X=1\nTELEGRAM_CHAT_ID=-100222\n"


def test_setup_without_token_or_with_bad_token(setup_mod, tmp_path, monkeypatch, capsys):
    fake = FakeTelegram()
    monkeypatch.setattr(tg.requests, "post", fake)
    assert setup_mod.main([], settings=_settings(tmp_path, token=None)) == 1
    assert fake.calls == [] and "BotFather" in capsys.readouterr().out

    fake.responses["getMe"] = [FakeResp({"ok": False, "error_code": 401, "description": "Unauthorized"}, 401)]
    assert setup_mod.main([], settings=_settings(tmp_path)) == 1
    out = capsys.readouterr().out
    assert "no es válido" in out and TOKEN not in out


def test_setup_list_only_has_no_side_effects(setup_mod, tmp_path, monkeypatch, capsys):
    fake = _patch_api(monkeypatch, [])
    assert setup_mod.main(["--env-file", str(tmp_path / "nada.env")], settings=_settings(tmp_path)) == 0
    assert fake.methods == ["getMe", "getUpdates"]
    assert not (tmp_path / "nada.env").exists()
    assert "/start" in capsys.readouterr().out
