"""Envío del briefing por email (SMTP, stdlib ``smtplib`` + ``email.message``).

Carril C. Entrada: ``Briefing`` + destinatarios (``SMTP_TO``). Salida: ``DeliveryResult``.
Config: ``SMTP_HOST``, ``SMTP_PORT``, ``SMTP_USER``, ``SMTP_PASSWORD``, ``SMTP_FROM``, ``SMTP_USE_TLS``.
"""

from __future__ import annotations

from briefer.config import Settings
from briefer.schemas import Briefing, DeliveryResult


def build_email_html(briefing: Briefing) -> str:
    """Cuerpo HTML: titular, puntos clave con sentimiento, gráficos inline y disclaimer."""
    # TODO: plantilla HTML sencilla (estilos inline, compatibles con clientes de correo);
    # escapar texto con html.escape; imágenes por CID (cid:chart0...) para incrustarlas.
    raise NotImplementedError("build_email_html: pendiente (carril C)")


def send_briefing_email(
    briefing: Briefing, to: list[str] | None = None, settings: Settings | None = None
) -> DeliveryResult:
    """Envía el email; devuelve ``DeliveryResult(channel="email", ...)`` sin lanzar excepciones."""
    # TODO:
    # 1. s = settings or get_settings(); to = to or s.smtp_recipients; si faltan host/from/to
    #    -> DeliveryResult(ok=False, detail="SMTP no configurado").
    # 2. EmailMessage: Subject = f"Market Briefer · {analysis.headline}", texto plano +
    #    add_alternative(html); adjuntar gráficos (related, CID) y el MP3 si < 10 MB.
    # 3. smtplib.SMTP(host, port) + starttls() si smtp_use_tls; login; send_message.
    # 4. try/except Exception -> ok=False, detail=str(e) (sin incluir credenciales).
    # RGPD: no incluir la cartera completa del usuario en el email salvo que lo pida.
    raise NotImplementedError("send_briefing_email: pendiente (carril C)")
