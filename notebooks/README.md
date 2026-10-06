# Notebooks de exploración

Cuadernos propios del grupo para probar modelos antes de llevarlos a `src/briefer/`.
No se copian aquí los notebooks de clase (están en `docs/raw/`, ignorado por git).

Convención de nombres: `<carril>_<nn>_<tema>.ipynb`, p. ej. `A_01_qwen_vl_graficos.ipynb`.
Antes de versionar un notebook: limpiar salidas pesadas y no dejar claves en las celdas.

Los cuadernos `00`-`02` son los de la entrega (caminos 6, 1 y 2 de `docs/05_roadmap_TODO.md`); los que
empiezan por letra son exploraciones de un carril. Kernel recomendado: «Briefly (.venv)» (o cualquier Python con
`pip install -e .`).

| Cuaderno | Qué muestra | Coste / red | Estado |
|---|---|---|---|
| [`00_recorrido_pipeline.ipynb`](00_recorrido_pipeline.ipynb) | Recorrido **paso a paso** de la cadena multi-modelo con las funciones reales de `src/briefer/`: noticias → filtro por tickers → precios → PDF y gráfico por visión (con router CLIP) → Analista → puertas de *grounding*/compliance → Guionista → normalización para voz → TTS a 2 voces → SRT → gráficos → vídeo → Q&A; entrada, salida tipada y `StepMetric` de cada paso, y al final `run_briefing(mode="mock")` con su traza «Cómo se hizo». Evidencia de orquestación para la rúbrica. | 0 €, sin red ni claves (mock, < 1 min); sección opcional `demo_voices` / `real` (≈ 0,05 €) | Hecho |
| [`01_evaluacion_briefings.ipynb`](01_evaluacion_briefings.ipynb) | Evaluación de N briefings reales: latencia y coste p50/p95, cifras trazables, frases con recomendación, fuentes por punto clave, duración del podcast, caídas a sustituto y LLM-juez (lógica en `scripts/evaluar_briefings.py`). | ~1 €, red y claves | En curso |
| `02_comparativa_modelos.ipynb` | Comparativa de modelos por agente (Sonnet, Haiku, Gemini) sobre el mismo `MarketContext`; decisión en `docs/decisiones/ADR-007`. | ~1 €, red y claves | En curso |
| [`A_01_ingesta_noticias_finbert.ipynb`](A_01_ingesta_noticias_finbert.ipynb) | Carril A (Daniel): calidad de la ingesta de noticias (URL real, extracto, relevancia por ticker) e «impacto de la noticia» con FinBERT. | Local (descarga el modelo la 1.ª vez) | Hecho |
