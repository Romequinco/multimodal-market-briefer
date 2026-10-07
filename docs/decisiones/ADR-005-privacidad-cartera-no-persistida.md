# ADR-005 · Privacidad: la cartera no se persiste

- **Estado:** Aceptado
- **Fecha:** 05-oct-2026
- **Ámbito:** `src/briefer/storage.py` (`save_briefing`, `export_briefing`), `src/briefer/pipeline.py`
  (gráfico de cartera temporal), `app/pages/3_Mi_cartera.py` (desde el 07-oct, sección «Tu cartera» de
  `app/components/new_briefing.py`); contrato v0.3.1
  ([03](../03_contratos_modulos.md#registro-de-cambios-de-contrato)). Transversal

## Contexto

- La auditoría de la revisión F0-F1 encontró que la UI afirmaba «la cartera no se guarda en disco» y no era
  verdad: `Briefing.context.portfolio` (tickers, pesos **y cantidades**) iba entero a
  `data/outputs/<id>/briefing.json`, junto con `portfolio_weights.png`, y «Histórico» y la portada se lo
  enseñaban a cualquier visitante de la app.
- La cartera es un dato personal y financiero (RGPD). El MVP no tiene usuarios ni autenticación, así que no hay
  forma de restringir quién ve un briefing guardado, y no hay tiempo de montar consentimiento y borrado antes de
  la entrega.
- El Analista sí necesita la cartera **en memoria**: sus tickers filtran las noticias y los pesos dan contexto.

## Decisión

**La cartera nunca se escribe en disco.** `save_briefing` y `export_briefing` guardan una copia del briefing con
`context.portfolio = null` y sin el gráfico `portfolio_pie`; el objeto en memoria no cambia.

- Los tickers de la cartera sí quedan en `context.tickers`: son el filtro del briefing, no revelan pesos ni
  cantidades.
- El gráfico de cartera se dibuja en `<tmp>/briefer_cartera/` (fuera de `data/`) y se borra a las
  `PORTFOLIO_CHART_TTL_H = 12` horas. Solo lo ve la sesión que generó el briefing.
- El LLM recibe en memoria **tickers y pesos** (no cantidades ni datos identificativos). Los textos de la UI y
  de [04](../04_viabilidad_costes_latencia_compliance.md#rgpd--datos-de-cartera) lo dicen así.

## Alternativas consideradas

| Opción | A favor | En contra |
| --- | --- | --- |
| Persistir con casilla de consentimiento | Histórico completo con cartera | Sin usuarios ni autenticación, cualquiera ve el histórico; consentimiento, borrado y retención no caben en el plazo |
| Persistir solo tickers y pesos, sin cantidades | Gráfico de cartera reabrible | Los pesos siguen siendo datos financieros personales; mismo problema de acceso |
| No guardar el briefing cuando hay cartera | Simple | Se pierden histórico, exportación y portada justo en el caso de uso principal |
| **No persistir la cartera (elegida)** | Cumple lo que dice la UI; sin cambios de schema; el histórico sigue funcionando | El histórico no puede volver a dibujar el reparto de la cartera |

## Consecuencias

- Positivas: la afirmación de privacidad de la UI es cierta y se comprueba con tests; el pregenerado
  (`data/samples/demo_briefing/briefing.json`) lleva `portfolio: null`; un ZIP exportado no contiene datos de la
  cartera.
- Negativas / deuda: un briefing reabierto desde el histórico no tiene el gráfico de cartera ni los pesos. El
  audio de las **respuestas** del Q&A sí se guarda en `data/outputs/<id>/qa/` (voz sintética, sin cartera).
- Para revertirla: añadir usuarios y autenticación, consentimiento explícito y borrado, y quitar la copia sin
  cartera en `storage._persistable`. Sería un cambio de semántica del contrato.
