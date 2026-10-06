"""Envío del briefing por Telegram (Bot API vía ``requests``, sin librerías extra).

Carril C. Entrada: ``Briefing``. Salida: ``DeliveryResult``.
Config: ``TELEGRAM_BOT_TOKEN`` (de @BotFather) y ``TELEGRAM_CHAT_ID`` (``scripts/telegram_setup.py``
lo descubre y lo escribe en ``.env``).

Orden de envío: (1) ``sendMessage`` con el resumen (``build_caption``, HTML); (2) ``sendAudio`` con el
podcast; (3) ``sendPhoto`` con la portada o, si no hay, el gráfico general (``overview_bar``);
(4) ``sendVideo`` con el vídeo corto. Si el mensaje no llega, el envío falla (``ok=False``) y no se
sigue. Un fallo posterior (audio, imagen o vídeo) no invalida lo ya enviado: ``ok=True`` y ``detail``
dice qué faltó.

Seguridad: la URL de la Bot API lleva el token (``/bot<TOKEN>/método``) y las excepciones de
``requests`` la repiten. Ningún ``detail`` ni línea de log sale sin pasar por ``_redact``
(sustitución literal del token + ``logging_utils.redact_secrets``), y se redacta **antes** de recortar.
"""

from __future__ import annotations

import html
import time
from pathlib import Path
from typing import Any

import requests

from briefer.brand import BRAND_NAME
from briefer.config import ROOT_DIR, Settings, get_settings
from briefer.logging_utils import get_logger, redact_secrets
from briefer.schemas import DISCLAIMER_ES, Briefing, DeliveryResult

log = get_logger("delivery.telegram")

API_URL = "https://api.telegram.org/bot{token}/{method}"
SENTIMENT_ICON = {"positivo": "▲", "negativo": "▼", "neutral": "●"}

#: Límite de subida de ficheros de la Bot API pública (``sendAudio``/``sendVideo``).
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
#: ``sendPhoto`` admite como mucho 10 MB.
MAX_PHOTO_BYTES = 10 * 1024 * 1024
#: Longitud máxima de un ``sendMessage`` (el caption de un fichero es 1024).
MAX_MESSAGE_CHARS = 4096
#: Timeouts (s): (conexión, lectura). Las subidas de audio/vídeo necesitan más lectura.
TIMEOUT_TEXT: tuple[float, float] = (10.0, 30.0)
TIMEOUT_UPLOAD: tuple[float, float] = (10.0, 120.0)
#: 429 (``retry_after``): un único reintento si la espera pedida no supera este máximo (s).
MAX_RETRY_AFTER_S = 5.0
#: Intérprete en ``sendAudio``: deja claro que las voces son sintéticas (compliance).
AUDIO_PERFORMER = f"{BRAND_NAME} · voces sintéticas IA"
NOT_CONFIGURED = "Telegram no configurado"
_ERROR_CHARS = 160


def build_caption(briefing: Briefing, max_len: int = 1024) -> str:
    """Texto del mensaje: titular + puntos clave + disclaimer (límite de caption de Telegram).

    Función pura (formato HTML de Telegram: ``<b>``, ``<i>``). Se añaden puntos clave enteros
    mientras quepan; el aviso de voz sintética y el disclaimer se reservan siempre, así que el
    recorte nunca deja etiquetas HTML a medias ni elimina el aviso legal.
    """
    a = briefing.analysis
    tail = f"\n\n<i>Voces sintéticas generadas con IA.</i>\n<i>{html.escape(a.disclaimer or DISCLAIMER_ES)}</i>"
    head = (
        f"<b>{html.escape(a.headline)}</b>\n"
        f"<i>{BRAND_NAME} · {a.date:%d/%m/%Y} · {html.escape(a.market_mood)}</i>"
    )
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


# ── Bot API ────────────────────────────────────────────────────────────────────────


class TelegramError(RuntimeError):
    """Error de la Bot API (``ok: false``) o de red. El mensaje ya va redactado (sin token)."""

    def __init__(self, message: str, *, error_code: int | None = None) -> None:
        super().__init__(message)
        self.error_code = error_code


def _redact(text: object, token: str | None) -> str:
    """Quita el token (literal y por patrón) y cualquier secreto conocido. Nunca lanza."""
    try:
        out = str(text)
    except Exception:
        return "<error no representable>"
    if token:
        out = out.replace(token, "***")
    return redact_secrets(out, extra=[token] if token else None)


def _safe_error(exc: BaseException, token: str | None) -> str:
    """``"Tipo: mensaje"`` en una línea, redactado **antes** de recortar (un token partido no escapa)."""
    detail = " ".join(_redact(exc, token).split())[:_ERROR_CHARS]
    if isinstance(exc, TelegramError):
        return detail
    return f"{type(exc).__name__}: {detail}" if detail else type(exc).__name__


def _payload(resp: Any) -> dict[str, Any]:
    """JSON de la respuesta (dict vacío si no es JSON)."""
    try:
        data = resp.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def call_api(
    token: str,
    method: str,
    data: dict[str, Any] | None = None,
    *,
    file_field: str | None = None,
    file_path: Path | None = None,
    timeout: tuple[float, float] = TIMEOUT_TEXT,
) -> Any:
    """Llama a un método de la Bot API y devuelve su ``result``.

    Lanza ``TelegramError`` (mensaje sin token) si la API responde ``ok: false``, si la respuesta no
    es JSON o si falla la red. Ante un 429 con ``retry_after`` ≤ ``MAX_RETRY_AFTER_S`` espera y
    reintenta **una** vez. El fichero (si lo hay) se abre con ``with`` en cada intento.
    """
    url = API_URL.format(token=token, method=method)
    for attempt in range(2):
        try:
            if file_field and file_path is not None:
                with open(file_path, "rb") as fh:
                    resp = requests.post(
                        url, data=data or {}, files={file_field: (file_path.name, fh)}, timeout=timeout
                    )
            else:
                resp = requests.post(url, data=data or {}, timeout=timeout)
        except (requests.RequestException, OSError) as exc:
            raise TelegramError(f"{method}: {_safe_error(exc, token)}") from None
        payload = _payload(resp)
        status = getattr(resp, "status_code", None)
        if payload.get("ok") is True:
            return payload.get("result")
        code = payload.get("error_code", status)
        if code == 429 and attempt == 0:
            params = payload.get("parameters") or {}
            try:
                wait = float(params.get("retry_after", 1))
            except (TypeError, ValueError):
                wait = 1.0
            if 0 <= wait <= MAX_RETRY_AFTER_S:
                log.info("Telegram %s: límite de envíos (429); reintento en %.0f s", method, wait)
                time.sleep(wait)
                continue
        description = payload.get("description") or f"respuesta no válida (HTTP {status})"
        raise TelegramError(_redact(f"{method}: {description} (código {code})", token), error_code=code)
    raise TelegramError(f"{method}: límite de envíos (429) tras reintentar", error_code=429)  # pragma: no cover


# ── Envío del briefing ─────────────────────────────────────────────────────────────


def _token_of(settings: Settings) -> str:
    secret = settings.telegram_bot_token
    return (secret.get_secret_value() if secret is not None else "").strip()


def _resolve(path: Path | None, briefing: Briefing, settings: Settings) -> Path | None:
    """Ruta existente de un fichero del briefing (o ``None``).

    ``storage.load_briefing`` ya devuelve rutas absolutas; una ruta relativa (briefing construido a
    mano o exportado) se busca en la carpeta del briefing (``output_path/<id>``), en la raíz del repo
    y en el directorio actual, por ese orden.
    """
    if path is None:
        return None
    p = Path(path)
    candidates = [p] if p.is_absolute() else [settings.output_path / briefing.id / p, ROOT_DIR / p, p]
    for candidate in candidates:
        try:
            if candidate.is_file():
                return candidate
        except OSError:
            continue
    return None


def _picture(briefing: Briefing, settings: Settings) -> Path | None:
    """Portada si existe; si no, el gráfico general (``overview_bar``). Nunca el de cartera."""
    cover = _resolve(briefing.cover_path, briefing, settings)
    if cover is not None:
        return cover
    for chart in briefing.charts:
        if chart.kind == "overview_bar":
            found = _resolve(chart.path, briefing, settings)
            if found is not None:
                return found
    return None


def _mb(size: int) -> str:
    return f"{size / (1024 * 1024):.1f} MB".replace(".", ",")


def send_briefing_telegram(
    briefing: Briefing, chat_id: str | None = None, settings: Settings | None = None
) -> DeliveryResult:
    """Envía resumen (sendMessage) + podcast (sendAudio) + portada o gráfico (sendPhoto) + vídeo.

    Sin token o sin chat: ``ok=False, detail="Telegram no configurado"`` (sin excepción ni red).
    Nunca lanza: los errores quedan en ``detail``, siempre sin el token.
    """
    s = settings or get_settings()
    token = _token_of(s)
    chat = str(chat_id or s.telegram_chat_id or "").strip()
    if not token or not chat:
        return DeliveryResult(channel="telegram", ok=False, detail=NOT_CONFIGURED)

    day = f"{briefing.analysis.date:%d/%m/%Y}"
    try:
        call_api(token, "sendMessage", {
            "chat_id": chat,
            "text": build_caption(briefing, max_len=MAX_MESSAGE_CHARS),
            "parse_mode": "HTML",
            "disable_web_page_preview": "true",
        })
    except Exception as exc:
        detail = f"Error al enviar el mensaje: {_safe_error(exc, token)}"
        log.warning("Telegram: %s", detail)
        return DeliveryResult(channel="telegram", ok=False, detail=detail)

    sent = ["mensaje"]
    problems: list[str] = []

    def upload(label: str, method: str, field: str, path: Path, data: dict[str, Any], limit: int) -> None:
        try:
            size = path.stat().st_size
        except OSError as exc:
            problems.append(f"{label} no enviado ({_safe_error(exc, token)})")
            return
        if size > limit:
            problems.append(f"{label} omitido ({_mb(size)} > {limit // (1024 * 1024)} MB)")
            return
        try:
            call_api(token, method, {"chat_id": chat, **data}, file_field=field, file_path=path,
                     timeout=TIMEOUT_UPLOAD)
            sent.append(label)
        except Exception as exc:
            problems.append(f"{label} no enviado ({_safe_error(exc, token)})")

    if briefing.audio is not None:
        audio = _resolve(briefing.audio.path, briefing, s)
        if audio is not None:
            upload("audio", "sendAudio", "audio", audio, {
                "title": f"{BRAND_NAME} · {day}",
                "performer": AUDIO_PERFORMER,
                "duration": str(round(briefing.audio.duration_s)),
                "caption": "Podcast del cierre. Voces sintéticas generadas con IA.",
            }, MAX_UPLOAD_BYTES)

    picture = _picture(briefing, s)
    if picture is not None:
        upload("imagen", "sendPhoto", "photo", picture, {"caption": f"{BRAND_NAME} · {day}"}, MAX_PHOTO_BYTES)

    if briefing.video is not None:
        video = _resolve(briefing.video.path, briefing, s)
        if video is not None:
            upload("vídeo", "sendVideo", "video", video, {
                "supports_streaming": "true",
                "duration": str(round(briefing.video.duration_s)),
                "caption": f"{BRAND_NAME} · {day}. Voces sintéticas generadas con IA.",
            }, MAX_UPLOAD_BYTES)

    detail = "Enviado a Telegram: " + ", ".join(sent)
    if problems:
        detail += ". " + "; ".join(problems)
        log.warning("Telegram (envío parcial): %s", _redact("; ".join(problems), token))
    return DeliveryResult(channel="telegram", ok=True, detail=_redact(detail, token))


__all__ = [
    "API_URL",
    "MAX_UPLOAD_BYTES",
    "TelegramError",
    "build_caption",
    "call_api",
    "send_briefing_telegram",
]
