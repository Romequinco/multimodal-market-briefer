"""Entrega del briefing por canales externos (carril C).

- ``email_sender``: email HTML con resumen, gráficos y enlace/adjunto del audio (SMTP).
- ``telegram_sender``: mensaje + audio por la Bot API de Telegram (``requests``).

El canal "web" es la propia app Streamlit. Cada envío devuelve un ``DeliveryResult`` y
nunca lanza excepciones hacia el pipeline (un fallo de entrega no invalida el briefing).
"""
