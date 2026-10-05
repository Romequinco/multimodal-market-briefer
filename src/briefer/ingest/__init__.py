"""Entradas y procesado (carril A): todo lo que llega al sistema se normaliza a schemas.

- ``news``        -> ``list[NewsItem]`` (Google News + Bing News + yfinance/Yahoo + prensa RSS, o ejemplos
                     offline), priorizadas por relevancia y con extracto breve (≤ 200 caracteres)
- ``article_meta``-> URL final del medio y ``og:description`` (solo metadatos, respeta robots.txt)
- ``tickers``     -> filtro de noticias por tickers/cartera
- ``prices``      -> ``list[PriceSnapshot]``
- ``portfolio``   -> ``Portfolio`` desde CSV
- ``pdf_reader``  -> ``DocumentInsight`` (texto con pypdf + visión en páginas con gráficos)
- ``chart_reader``-> ``DocumentInsight`` (captura de gráfico con visión, CLIP opcional)
- ``voice``       -> texto / ``DocumentInsight`` (STT)
- ``cache``       -> caché diaria en disco (``BRIEFER_CACHE_DIR``) para noticias, metadatos y precios
"""
