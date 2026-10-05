# Datos de ejemplo

Ficheros pequeños y **ficticios** para desarrollar, hacer tests y ejecutar la demo sin red ni
claves (modo mock). No contienen datos reales de mercado ni datos personales.

| Fichero | Contenido | Formato / schema |
|---|---|---|
| `portfolio_ejemplo.csv` | Cartera de ejemplo con 7 valores (IBEX y EE. UU.) | Columnas `ticker,name,weight,quantity`; pesos en tanto por uno (suman 1). Se carga con `ingest.portfolio.load_portfolio_csv` → `Portfolio` |
| `noticias_ejemplo.json` | 5 noticias **inventadas**, marcadas con `[EJEMPLO FICTICIO]` | Lista de objetos `NewsItem` (ver `src/briefer/schemas.py`). Se carga con `ingest.news.load_sample_news` |

Reglas:
- Todo lo que se añada aquí debe ser ficticio o de licencia libre, y pequeño (< 1 MB).
- TODO: añadir una captura de gráfico de ejemplo (`grafico_ejemplo.png`) y un PDF corto de
  resultados de ejemplo (`resultados_ejemplo.pdf`) generados por nosotros, para la demo de
  lectura de imagen y PDF.
- Los tests (`tests/test_schemas.py`) validan que estos ficheros cumplen los schemas.
