# Datos de ejemplo

Ficheros pequeños y **ficticios** para desarrollar, hacer tests y ejecutar la demo sin red ni
claves (modo mock). No contienen datos reales de mercado ni datos personales.

| Fichero | Contenido | Formato / schema |
|---|---|---|
| `portfolio_ejemplo.csv` | Cartera de ejemplo con 7 valores (IBEX y EE. UU.) | Columnas `ticker,name,weight,quantity`; pesos en tanto por uno (suman 1). Se carga con `ingest.portfolio.load_portfolio_csv` → `Portfolio` |
| `noticias_ejemplo.json` | 5 noticias **inventadas**, marcadas con `[EJEMPLO FICTICIO]` | Lista de objetos `NewsItem` (ver `src/briefer/schemas.py`). Se carga con `ingest.news.load_sample_news` |
| `grafico_ejemplo.png` | Captura simulada de un gráfico de velas diario con volumen de un valor **inventado** (`EJMP`, «Ejemplo Industrial S.A.»), con el aviso «EJEMPLO FICTICIO» | PNG 1100×660. Entrada de `ingest.chart_reader.read_chart` (subida de imagen en la UI) |
| `resultados_ejemplo.pdf` | 3 páginas de resultados trimestrales **inventados** de la misma empresa: resumen con cifras, tabla de magnitudes y una página con el gráfico embebido como imagen | PDF con capa de texto (pypdf la extrae). La página 3 tiene poco texto y una imagen raster, así que `ingest.pdf_reader.read_pdf` la manda al modelo de visión |
| `generar_muestras.py` | Script que genera el PNG y el PDF anteriores con matplotlib (sin dependencias nuevas, determinista) | `python data/samples/generar_muestras.py` |

Reglas:
- Todo lo que se añada aquí debe ser ficticio o de licencia libre, y pequeño (< 1 MB).
- El PNG y el PDF se versionan (la demo los usa directamente); si se cambia el script, regenerarlos.
- Los tests (`tests/test_schemas.py`, `tests/test_ingest_mock.py`) validan que estos ficheros cumplen
  los schemas y que los lectores de `ingest/` los procesan en modo mock.
