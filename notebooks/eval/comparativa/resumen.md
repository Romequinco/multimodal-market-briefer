# Camino 2 · Resumen modelo × agente

Generado por `notebooks/02_comparativa_modelos.ipynb`. Gasto total: 0.5462 € (agentes 0.3992 € + juez 0.1470 €). Coste = tokens reales × tarifas de `briefer.costs`.

| agente | modelo | n | coste_€ | latencia_s | JSON_1ª | reintentos | cifras_no_traz_1ª | consejo_final | juez_fidelidad | juez_claridad | juez_naturalidad | juez_sin_consejo |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Analista | Claude Sonnet 5.5 | 2/2 | 0.0264 | 14.96 | 2/2 | 0.0000 | 0.0000 | 0.0000 | 4.50 | 4.50 | - | 4.25 |
| Analista | Claude Haiku 4.5 | 2/2 | 0.0096 | 16.92 | 2/2 | 0.0000 | 0.0000 | 0.0000 | 2.00 | 4.00 | - | 3.25 |
| Analista | Gemini (gemini-2.5-flash) | 2/2 | 0.0148 | 32.91 | 2/2 | 2.0000 | 1.0000 | 0.0000 | 3.00 | 4.00 | - | 4.00 |
| Guionista | Claude Sonnet 5.5 | 4/4 | 0.0349 | 21.11 | 4/4 | 1.0000 | - | 0.0000 | 4.25 | 4.50 | 3.50 | 5.00 |
| Guionista | Claude Haiku 4.5 | 4/4 | 0.0109 | 14.88 | 4/4 | 1.0000 | - | 0.0000 | 3.50 | 4.00 | 3.50 | 4.25 |
| Guionista | Gemini (gemini-2.5-flash) | 4/4 | 0.0074 | 15.54 | 4/4 | 3.0000 | - | 0.0000 | 4.00 | 4.00 | 3.50 | 4.25 |
| Q&A | Claude Sonnet 5.5 | 2.0000 | 0.0110 | 2.52 | - | - | - | 0.0000 | - | - | - | - |
| Q&A | Claude Haiku 4.5 | 2.0000 | 0.0044 | 3.84 | - | - | - | 0.0000 | - | - | - | - |
| Q&A | Gemini (gemini-2.5-flash) | 2.0000 | 0.0018 | 3.11 | - | - | - | 0.0000 | - | - | - | - |
