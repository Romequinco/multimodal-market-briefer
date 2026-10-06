"""Entrega del briefing por canales externos (carril C).

- ``telegram_sender``: mensaje + audio por la Bot API de Telegram (``requests``).

El canal "web" es la propia app Streamlit. Cada envío devuelve un ``DeliveryResult`` y
nunca lanza excepciones hacia el pipeline (un fallo de entrega no invalida el briefing).
"""
