"""Envío del briefing por Telegram (Bot API vía ``requests``, sin librerías extra).

Carril C. Entrada: ``Briefing``. Salida: ``DeliveryResult``.
Config: ``TELEGRAM_BOT_TOKEN`` (de @BotFather) y ``TELEGRAM_CHAT_ID``.
"""

from __future__ import annotations

import html

from briefer.config import Settings
from briefer.schemas import DISCLAIMER_ES, Briefing, DeliveryResult

API_URL = "https://api.telegram.org/bot{token}/{method}"
SENTIMENT_ICON = {"positivo": "▲", "negativo": "▼", "neutral": "●"}


def build_caption(briefing: Briefing, max_len: int = 1024) -> str:
    """Texto del mensaje: titular + puntos clave + disclaimer (límite de caption de Telegram).

    Función pura (formato HTML de Telegram: ``<b>``, ``<i>``). Se añaden puntos clave enteros
    mientras quepan; el aviso de voz sintética y el disclaimer se reservan siempre, así que el
    recorte nunca deja etiquetas HTML a medias ni elimina el aviso legal.
    """
    a = briefing.analysis
    tail = f"\n\n<i>Voces sintéticas generadas con IA.</i>\n<i>{html.escape(a.disclaimer or DISCLAIMER_ES)}</i>"
    head = f"<b>{html.escape(a.headline)}</b>\n<i>{a.date:%d/%m/%Y} · {html.escape(a.market_mood)}</i>"
    if len(head) + len(tail) > max_len:
        # Caso extremo (titular larguísimo o max_len pequeño): titular recortado sin formato.
        room = max(0, max_len - len(tail) - 1)
        return (html.escape(a.headline)[:room] + "…" + tail)[:max_len]
    body = head
    for kp in a.key_points:
        tickers = f" ({html.escape(', '.join(kp.tickers))})" if kp.tickers else ""
        icon = SENTIMENT_ICON.get(kp.sentiment, "•")
        line = f"\n\n{icon} <b>{html.escape(kp.title)}</b>{tickers}\n{html.escape(kp.explanation)}"
        if len(body) + len(line) + len(tail) > max_len:
            break
        body += line
    return body + tail


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
