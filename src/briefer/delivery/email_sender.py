"""Envío del briefing por email (SMTP, stdlib ``smtplib`` + ``email.message``).

Carril C. Entrada: ``Briefing`` + destinatarios (``SMTP_TO``). Salida: ``DeliveryResult``.
Config: ``SMTP_HOST``, ``SMTP_PORT``, ``SMTP_USER``, ``SMTP_PASSWORD``, ``SMTP_FROM``, ``SMTP_USE_TLS``.
"""

from __future__ import annotations

import html

from briefer.brand import BRAND_NAME, EDITION
from briefer.config import Settings
from briefer.schemas import DISCLAIMER_ES, Briefing, DeliveryResult

SENTIMENT_STYLE = {
    "positivo": ("▲ positivo", "#1c5cab"),
    "negativo": ("▼ negativo", "#b3302f"),
    "neutral": ("● neutral", "#52514e"),
}
SYNTHETIC_VOICE_NOTE = "El audio del podcast está generado con voces sintéticas (IA), no son personas reales."


def _source_html(source: str, briefing: Briefing) -> str:
    """Enlace a la noticia citada (por id o URL) o el nombre del documento."""
    news = {n.id: n for n in briefing.context.news} | {n.url: n for n in briefing.context.news}
    item = news.get(source)
    if item is not None:
        return (
            f'<a href="{html.escape(item.url, quote=True)}" style="color:#1c5cab;">'
            f"{html.escape(item.title)}</a> ({html.escape(item.source)})"
        )
    if source.startswith(("http://", "https://")):
        return f'<a href="{html.escape(source, quote=True)}" style="color:#1c5cab;">{html.escape(source)}</a>'
    return html.escape(source)


CHART_ALT = {"overview_bar": "Variación del día", "price_line": "Cotización", "portfolio_pie": "Reparto de la cartera"}


def _chart_alt(chart) -> str:
    """Texto alternativo legible del gráfico (accesibilidad y clientes que bloquean imágenes)."""
    label = CHART_ALT.get(chart.kind, chart.kind)
    return f"{label} · {chart.ticker}" if chart.ticker else label


def build_email_html(briefing: Briefing, chart_cids: list[str] | None = None) -> str:
    """Cuerpo HTML: titular, puntos clave con sentimiento, gráficos inline y disclaimer.

    Función pura (sin red). Estilos inline para clientes de correo. ``chart_cids`` son los
    Content-ID de las imágenes adjuntas (por defecto ``chart0``, ``chart1``… uno por
    ``briefing.charts``); el envío (``send_briefing_email``) debe adjuntar los PNG con esos CID.
    """
    a = briefing.analysis
    cids = chart_cids if chart_cids is not None else [f"chart{i}" for i in range(len(briefing.charts))]
    rows: list[str] = []
    for kp in a.key_points:
        label, color = SENTIMENT_STYLE.get(kp.sentiment, (kp.sentiment, "#52514e"))
        sources = "; ".join(_source_html(s, briefing) for s in kp.sources)
        tickers = ", ".join(kp.tickers)
        cell = (
            f'<div style="font-size:16px;font-weight:bold;color:#0b0b0b;">{html.escape(kp.title)} '
            f'<span style="font-size:13px;color:{color};">{html.escape(label)}</span></div>'
            f'<div style="font-size:14px;color:#0b0b0b;margin-top:4px;">{html.escape(kp.explanation)}</div>'
        )
        if tickers:
            cell += f'<div style="font-size:12px;color:#52514e;margin-top:4px;">Valores: {html.escape(tickers)}</div>'
        if sources:
            cell += f'<div style="font-size:12px;color:#52514e;margin-top:2px;">Fuentes: {sources}</div>'
        rows.append(f'<tr><td style="padding:12px 0;border-bottom:1px solid #e4e3df;">{cell}</td></tr>')
    charts = "".join(
        f'<img src="cid:{html.escape(cid, quote=True)}" alt="{html.escape(_chart_alt(chart), quote=True)}" '
        'width="560" style="display:block;width:100%;max-width:560px;margin:12px 0;border-radius:6px;">'
        for cid, chart in zip(cids, briefing.charts, strict=False)
    )
    duration = ""
    if briefing.audio:
        mins, secs = divmod(int(round(briefing.audio.duration_s)), 60)
        duration = f" · podcast de {mins}:{secs:02d} min"
    return (
        '<!doctype html><html lang="es"><head><meta charset="utf-8">'
        f"<title>{html.escape(a.headline)}</title></head>"
        '<body style="margin:0;padding:0;background:#f4f3f0;font-family:Arial,Helvetica,sans-serif;">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><td align="center">'
        '<table role="presentation" width="600" cellpadding="0" cellspacing="0" '
        'style="max-width:600px;background:#fcfcfb;padding:24px;">'
        '<tr><td style="font-size:12px;color:#52514e;text-transform:uppercase;letter-spacing:1px;">'
        f"{BRAND_NAME} · {EDITION} · {a.date:%d/%m/%Y}{duration}</td></tr>"
        '<tr><td style="font-size:24px;font-weight:bold;color:#0b0b0b;padding:8px 0;">'
        f"{html.escape(a.headline)}</td></tr>"
        '<tr><td style="font-size:14px;color:#52514e;padding-bottom:8px;">Tono del mercado: '
        f"{html.escape(a.market_mood)}</td></tr>"
        + "".join(rows)
        + (f"<tr><td>{charts}</td></tr>" if charts else "")
        + '<tr><td style="font-size:12px;color:#52514e;padding-top:16px;">'
        f"{html.escape(SYNTHETIC_VOICE_NOTE)}</td></tr>"
        '<tr><td style="font-size:12px;color:#52514e;padding-top:8px;border-top:1px solid #e4e3df;">'
        f"<strong>Aviso:</strong> {html.escape(a.disclaimer or DISCLAIMER_ES)}</td></tr>"
        "</table></td></tr></table></body></html>"
    )


def send_briefing_email(
    briefing: Briefing, to: list[str] | None = None, settings: Settings | None = None
) -> DeliveryResult:
    """Envía el email; devuelve ``DeliveryResult(channel="email", ...)`` sin lanzar excepciones."""
    # TODO:
    # 1. s = settings or get_settings(); to = to or s.smtp_recipients; si faltan host/from/to
    #    -> DeliveryResult(ok=False, detail="SMTP no configurado").
    # 2. EmailMessage: Subject = f"{BRAND_NAME} · {analysis.headline}", texto plano +
    #    add_alternative(html); adjuntar gráficos (related, CID) y el MP3 si < 10 MB.
    # 3. smtplib.SMTP(host, port) + starttls() si smtp_use_tls; login; send_message.
    # 4. try/except Exception -> ok=False, detail=str(e) (sin incluir credenciales).
    # RGPD: no incluir la cartera completa del usuario en el email salvo que lo pida.
    raise NotImplementedError("send_briefing_email: pendiente (carril C)")
