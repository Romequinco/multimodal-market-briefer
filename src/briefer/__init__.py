"""Market Briefer: briefing de mercados multimodal (noticias -> análisis -> podcast a 2 voces).

Paquetes:
- ``ingest``    (carril A): noticias, precios, cartera, PDF, capturas de gráfico, voz.
- ``agents``    (carril B): Agente Analista, Agente Guionista y Agente Q&A.
- ``media``     (carril C): gráficos, podcast, transcripción, portada y vídeo.
- ``delivery``  (carril C): email y Telegram.
- ``providers`` (todos): capa de conexión con modelos IA intercambiables.
- ``pipeline``  (carril B): orquestación de extremo a extremo.

Contenido informativo: no es asesoramiento financiero (MiFID II).
"""

__version__ = "0.1.0"
