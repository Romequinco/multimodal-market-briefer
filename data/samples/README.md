# Datos de ejemplo

Ficheros pequeños y **ficticios** para desarrollar, hacer tests y ejecutar la demo sin red ni
claves (modo mock). No contienen datos reales de mercado ni datos personales.

| Fichero | Contenido | Formato / schema |
|---|---|---|
| `portfolio_ejemplo.csv` | Cartera de ejemplo con 7 valores (IBEX y EE. UU.) | Columnas `ticker,name,weight,quantity`; pesos en tanto por uno (suman 1). Se carga con `ingest.portfolio.load_portfolio_csv` → `Portfolio` |
| `noticias_ejemplo.json` | 5 noticias **inventadas**, marcadas con `[EJEMPLO FICTICIO]` | Lista de objetos `NewsItem` (ver `src/briefer/schemas.py`). Se carga con `ingest.news.load_sample_news` |
| `grafico_ejemplo.png` | Captura simulada de un gráfico de velas diario con volumen de un valor **inventado** (`EJMP`, «Ejemplo Industrial S.A.»), con el aviso «EJEMPLO FICTICIO» | PNG 1100×660. Entrada de `ingest.chart_reader.read_chart` (subida de imagen en la UI) |
| `cartera_ejemplo.png` | Captura **ficticia** de la pantalla «Mis posiciones» de una app de broker genérica (sin marcas reales): Banco Santander, Inditex, Iberdrola, Apple y NVIDIA con títulos, precio, importe y peso, marcada «Ejemplo ficticio» | PNG 1000×620 (≈ 50 KB). Entrada de `ingest.portfolio.portfolio_from_image` (botón «Usar captura de ejemplo» de la sección «Tu cartera» del diálogo «Nuevo briefing») |
| `resultados_ejemplo.pdf` | 3 páginas de resultados trimestrales **inventados** de la misma empresa: resumen con cifras, tabla de magnitudes y una página con el gráfico embebido como imagen | PDF con capa de texto (pypdf la extrae). La página 3 tiene poco texto y una imagen raster, así que `ingest.pdf_reader.read_pdf` la manda al modelo de visión |
| `demo_briefing/` | **Briefing real pregenerado** (05-oct-2026): 5 tickers por defecto + índices de contexto, con el PDF y el PNG de arriba leídos por visión real, análisis de Claude, guion y podcast con edge-tts. La portada lo muestra si no hay briefings guardados | `briefing.json` (contrato v0.3, rutas relativas) + `podcast.mp3` (voces sintéticas, con metadatos ID3 de IA) + `podcast.srt` + `charts/*.png`. Se regenera con `storage.export_briefing(briefing, storage.demo_briefing_dir())` |
| `generar_muestras.py` | Script que genera los PNG y el PDF anteriores con matplotlib y Pillow (sin dependencias nuevas, determinista) | `python data/samples/generar_muestras.py` |
| `qa_example/` | Conversación **preparada**, con tres respuestas sobre Santander y Apple basadas en el briefing guardado del 06-oct-2026: explicación, seguimiento y comparación. No es una ejecución grabada de un LLM ni información actual | `conversation.json` con contexto propio, fuentes y rutas relativas + tres MP3 de voz sintética. «Ver ejemplo completo» en Preguntar los reproduce sin red ni claves. Para regenerar solo la voz: `python scripts/generar_ejemplo_qa.py` (edge-tts, requiere red, sin claves) |

Reglas:
- Todo lo que se añada aquí debe ser ficticio o de licencia libre, y pequeño (< 5 MB en total por
  carpeta; `demo_briefing/` ocupa ≈ 2,8 MB). Excepción: `demo_briefing/` es un briefing **real**
  (titulares y resúmenes breves de noticias públicas con su enlace y fuente, precios de Yahoo
  Finance); sus documentos de usuario siguen siendo los ficticios de esta carpeta.
- `.gitignore` ignora `*.mp3`/`*.wav`/`*.mp4`, pero `!data/samples/**` los vuelve a incluir aquí.
- El PNG y el PDF se versionan (la demo los usa directamente); si se cambia el script, regenerarlos.
- Los tests (`tests/test_schemas.py`, `tests/test_ingest_mock.py`) validan que estos ficheros cumplen
  los schemas y que los lectores de `ingest/` los procesan en modo mock.

Modo real (sin estos ficheros): `ingest.news.fetch_news` (Google News y Bing News RSS en español por
empresa, RSS de Yahoo Finance, yfinance y feeds de mercados; después, `ingest.article_meta` busca la
URL final del medio y su `og:description` cuando el feed no trae extracto) e
`ingest.prices.get_price_snapshots` (yfinance). De cada noticia solo se guarda titular, extracto breve
(≤ 200 caracteres, `news.SUMMARY_MAX_CHARS`), fuente y enlace. Las respuestas se cachean en
`data/cache/` (`BRIEFER_CACHE_DIR`, ignorado por git; se limpian solas a los 7 días): no se versionan
ni se copian aquí, porque son contenido de terceros. Los tests sin red usan fixtures inline en
`tests/test_ingest_real.py`, `tests/test_ingest_news_quality.py` y `tests/test_ingest_robustness.py`.
