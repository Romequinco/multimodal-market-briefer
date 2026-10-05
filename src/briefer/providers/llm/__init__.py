"""Implementaciones reales de ``LLMProvider`` (carril B).

- ``anthropic_llm.AnthropicLLM``: Claude (por defecto; ``claude-sonnet-5-5`` / Haiku barato).
- ``gemini_llm.GeminiLLM``: Google Gemini (``google-genai``), LLM alternativo del MVP.
- ``openai_llm.OpenAILLM``: stub documentado (recorte: un solo LLM alternativo).
- ``_anthropic_common``: cliente, ``usage`` y texto de respuesta compartidos con ``ClaudeVision``.
- ``_structured``: JSON -> Pydantic con 1 reintento autocorrectivo (común a Anthropic y Gemini).

Se cargan de forma perezosa desde ``providers.registry``; no importes SDKs a nivel de módulo.
"""
