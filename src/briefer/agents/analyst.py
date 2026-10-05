"""Agente Analista: interpreta el contexto de mercado del día.

Carril B. Entrada: ``MarketContext`` (noticias filtradas, precios, insights de PDF/gráfico/voz,
cartera opcional). Salida: ``Analysis`` (titular, puntos clave con tickers, sentimiento y
fuentes, tono del mercado y disclaimer). Prompt: ``prompts/analyst.md``.
Patrón de agente del notebook 9 (Agents): rol + contexto + salida estructurada.
"""

from __future__ import annotations

from briefer.providers.base import LLMProvider
from briefer.schemas import Analysis, MarketContext


def build_user_message(context: MarketContext, max_chars: int = 40_000) -> str:
    """Serializa el contexto en un mensaje compacto y trazable para el LLM."""
    # TODO:
    # - Secciones: "## Precios" (ticker, último, % día), "## Noticias" (id, fuente, fecha,
    #   título, resumen), "## Documentos del usuario" (DocumentInsight.summary + key_figures),
    #   "## Cartera" (solo tickers y pesos; nunca datos personales adicionales).
    # - Incluir el id de cada noticia para que el LLM lo cite en KeyPoint.sources.
    # - Recortar resúmenes largos para no superar max_chars (prioridad: precios > noticias
    #   de la cartera > documentos > resto).
    raise NotImplementedError("build_user_message: pendiente (carril B)")


def analyze(context: MarketContext, llm: LLMProvider) -> Analysis:
    """Ejecuta el Agente Analista y devuelve un ``Analysis`` validado."""
    # TODO:
    # 1. system = load_prompt("analyst"); user = build_user_message(context).
    # 2. analysis = llm.complete(system, [{"role": "user", "content": user}],
    #    response_model=Analysis).
    # 3. Post-validación: date = context.date; disclaimer = DISCLAIMER_ES (no confiar en el
    #    LLM); descartar KeyPoint.sources que no existan en context (anti-alucinación);
    #    limitar a 3-6 puntos clave.
    # Casos borde: contexto sin noticias -> análisis "día sin novedades relevantes" basado
    # solo en precios; LLM devuelve recomendaciones de compra/venta -> el prompt lo prohíbe
    # y aquí se puede filtrar con una lista de expresiones ("compra", "vende"...).
    raise NotImplementedError("analyze: pendiente (carril B)")
