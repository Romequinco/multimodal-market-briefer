"""Envío del briefing por Telegram (Bot API vía ``requests``, sin librerías extra).

Carril C. Entrada: ``Briefing``. Salida: ``DeliveryResult``.
Config: ``TELEGRAM_BOT_TOKEN`` (de @BotFather) y ``TELEGRAM_CHAT_ID``.
"""

from __future__ import annotations

from briefer.config import Settings
from briefer.schemas import Briefing, DeliveryResult

API_URL = "https://api.telegram.org/bot{token}/{method}"


def build_caption(briefing: Briefing, max_len: int = 1024) -> str:
    """Texto del mensaje: titular + puntos clave + disclaimer (límite de caption de Telegram)."""
    # TODO: formato HTML de Telegram (<b>, <i>) con html.escape; recortar a max_len.
    raise NotImplementedError("build_caption: pendiente (carril C)")


def send_briefing_telegram(
    briefing: Briefing, chat_id: str | None = None, settings: Settings | None = None
) -> DeliveryResult:
    """Envía resumen + audio (sendAudio) + gráfico principal (sendPhoto)."""
    # TODO:
    # 1. s = settings or get_settings(); token/chat_id ausentes -> ok=False, "Telegram no configurado".
    # 2. requests.post(API_URL.format(token=..., method="sendMessage"), data={chat_id, text,
    #    parse_mode="HTML"}, timeout=30).
    # 3. sendAudio con files={"audio": open(mp3, "rb")} (límite 50 MB) y title.
    # 4. sendPhoto con el gráfico overview si existe.
    # 5. Comprobar resp.json()["ok"]; try/except -> ok=False (sin exponer el token en detail).
    raise NotImplementedError("send_briefing_telegram: pendiente (carril C)")
