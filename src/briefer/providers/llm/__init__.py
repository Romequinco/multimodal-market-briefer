"""Implementaciones reales de ``LLMProvider`` (carril B).

- ``anthropic_llm.AnthropicLLM``: Claude (por defecto; ``claude-sonnet-5-5`` / Haiku barato).
- ``gemini_llm.GeminiLLM``: Google Gemini (``google-genai``).
- ``openai_llm.OpenAILLM``: OpenAI (``openai``); con ``base_url`` sirve también para Ollama local.

Se cargan de forma perezosa desde ``providers.registry``; no importes SDKs a nivel de módulo.
"""
