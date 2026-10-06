# Evaluación de briefings reales (06-10-2026)

Generado por `notebooks/01_evaluacion_briefings.ipynb`.

| métrica                      | valor           |
|:-----------------------------|:----------------|
| N briefings                  | 6               |
| pared p50 / p95 (s)          | 52.7 / 68.2     |
| coste p50 / p95 (€)          | 0.0337 / 0.0620 |
| cifras trazables (%)         | 100.0           |
| frases con recomendación     | 0               |
| pasos caídos a sustituto     | 0               |
| pasos con error              | 0               |
| podcasts en 3-5 min          | 6/6             |
| puntos clave con fuente      | 35/35           |
| fuentes inválidas            | 0               |
| juez fidelidad (media 1-5)   | 3.33            |
| juez claridad (media 1-5)    | 4.0             |
| juez sin_consejo (media 1-5) | 4.17            |
| juez utilidad (media 1-5)    | 3.33            |
| gasto total evaluación (€)   | 0.4146          |

## Por briefing

| escenario                 |   pared s |   suma pasos s |   coste € |   noticias | cifras análisis (traz.)   | cifras guion (traz.)   |   recom. análisis |   recom. guion |   puntos clave |   con fuente |   fuentes inválidas |   podcast min | en 3-5 min   |   reint. analista |   reint. guionista |   sustitutos |   errores |
|:--------------------------|----------:|---------------:|----------:|-----------:|:--------------------------|:-----------------------|------------------:|---------------:|---------------:|-------------:|--------------------:|--------------:|:-------------|------------------:|-------------------:|-------------:|----------:|
| cartera_banca_es          |     70.75 |          77.17 |    0.0339 |         18 | 27/27                     | 21/21                  |                 0 |              0 |              6 |            6 |                   0 |          3.55 | True         |                 0 |                  0 |            0 |         0 |
| cartera_tech_usa          |     53.66 |          54.48 |    0.0406 |         18 | 20/20                     | 19/19                  |                 0 |              0 |              6 |            6 |                   0 |          3.29 | True         |                 0 |                  1 |            0 |         0 |
| cartera_mixta_defensiva   |     51.79 |          51.97 |    0.0336 |         20 | 18/18                     | 17/17                  |                 0 |              0 |              6 |            6 |                   0 |          3.47 | True         |                 0 |                  0 |            0 |         0 |
| tickers_ibex_varios       |     49.83 |          52.48 |    0.0327 |         17 | 18/18                     | 17/17                  |                 0 |              0 |              6 |            6 |                   0 |          3.51 | True         |                 0 |                  0 |            0 |         0 |
| tickers_usa_megacaps      |     47.2  |          53.29 |    0.0319 |         20 | 19/19                     | 19/19                  |                 0 |              0 |              5 |            5 |                   0 |          3.68 | True         |                 0 |                  0 |            0 |         0 |
| tickers_con_pdf_y_grafico |     60.48 |          81.58 |    0.0691 |         17 | 23/23                     | 14/14                  |                 0 |              0 |              6 |            6 |                   0 |          3.17 | True         |                 0 |                  0 |            0 |         0 |

## Agregados

|                                 |   N |     p50 |     p95 |   media |     mín |     máx |
|:--------------------------------|----:|--------:|--------:|--------:|--------:|--------:|
| pared medida (s)                |   6 | 52.725  | 68.1825 | 55.6183 | 47.2    | 70.75   |
| pared aprox. metrics_report (s) |   6 | 53.416  | 68.3458 | 56.0132 | 47.389  | 70.835  |
| suma de pasos (s)               |   6 | 53.885  | 80.4775 | 61.8283 | 51.97   | 81.58   |
| coste (€)                       |   6 |  0.0337 |  0.062  |  0.0403 |  0.0319 |  0.0691 |
| coste sin subidas (€)           |   5 |  0.0336 |  0.0392 |  0.0345 |  0.0319 |  0.0406 |

## Por paso

| paso                | proveedor                           |   N |   lat p50 s |   lat p95 s |   coste p50 € |   coste p95 € |   coste total € |
|:--------------------|:------------------------------------|----:|------------:|------------:|--------------:|--------------:|----------------:|
| ingest.news         | yfinance+rss                        |   6 |      5.5813 |      8.4043 |        0      |        0      |          0      |
| ingest.prices       | yfinance                            |   6 |      1.7916 |     17.4264 |        0      |        0      |          0      |
| ingest.tickers      | local                               |   6 |      0.0074 |      0.0091 |        0      |        0      |          0      |
| agents.analyst      | anthropic/claude-sonnet-5-5         |   6 |     14.2204 |     14.619  |        0.0246 |        0.0263 |          0.1489 |
| agents.scriptwriter | anthropic/claude-haiku-4-5-20251001 |   6 |     11.64   |     18.5433 |        0.0084 |        0.0146 |          0.0584 |
| media.podcast       | edge/edge-tts                       |   6 |     17.1362 |     22.1542 |        0      |        0      |          0      |
| media.transcript    | local                               |   6 |      0.0034 |      0.0044 |        0      |        0      |          0      |
| media.charts        | matplotlib                          |   6 |      1.538  |      2.0275 |        0      |        0      |          0      |
| storage.save        | local                               |   6 |      0.0063 |      0.0071 |        0      |        0      |          0      |
| ingest.pdf          | anthropic/claude-sonnet-5-5         |   1 |     18.3648 |     18.3648 |        0.0197 |        0.0197 |          0.0197 |
| ingest.chart        | anthropic/claude-sonnet-5-5         |   1 |     15.7482 |     15.7482 |        0.0147 |        0.0147 |          0.0147 |

## Juez

| escenario                 |   fidelidad |   claridad |   sin_consejo |   utilidad |   coste € |
|:--------------------------|------------:|-----------:|--------------:|-----------:|----------:|
| cartera_banca_es          |           3 |          4 |             5 |          4 |  0.01456  |
| cartera_tech_usa          |           4 |          4 |             3 |          4 |  0.013868 |
| cartera_mixta_defensiva   |           3 |          4 |             4 |          3 |  0.014329 |
| tickers_ibex_varios       |           3 |          4 |             4 |          3 |  0.013686 |
| tickers_usa_megacaps      |           3 |          4 |             4 |          3 |  0.014783 |
| tickers_con_pdf_y_grafico |           4 |          4 |             5 |          3 |  0.015095 |

## Carteras

| cartera                 |   recom. (an.+guion) |   cifras no trazables (an.+guion) | posiciones en análisis   | posiciones en guion   | ausentes del análisis   | titular                                                                                     |
|:------------------------|---------------------:|----------------------------------:|:-------------------------|:----------------------|:------------------------|:--------------------------------------------------------------------------------------------|
| cartera_banca_es        |                    0 |                                 0 | 3/3                      | 3/3                   | —                       | Santander lidera el rebote de la banca española, que impulsa al Ibex 35 un 1,08%            |
| cartera_tech_usa        |                    0 |                                 0 | 3/3                      | 3/3                   | —                       | NVIDIA y Microsoft lideran el avance de la sesión mientras Apple cede ligeramente un 0,24 % |
| cartera_mixta_defensiva |                    0 |                                 0 | 3/3                      | 3/3                   | —                       | Iberdrola lidera las subidas de tu cartera en un Ibex con impulso de la banca               |

Ids: cartera_banca_es=20261006-134527-44869c, cartera_tech_usa=20261006-134637-845111, cartera_mixta_defensiva=20261006-134731-ef9961, tickers_ibex_varios=20261006-134823-89a7d2, tickers_usa_megacaps=20261006-134913-9f8aba, tickers_con_pdf_y_grafico=20261006-135000-2ceb28