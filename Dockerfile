# Imagen del MVP (sin modelos locales pesados; para ellos usar requirements-local.txt + GPU).
# Uso: docker compose up --build   ->  http://localhost:8501
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app/src \
    TZ=Europe/Madrid \
    MPLBACKEND=Agg

# ffmpeg del sistema como respaldo del binario de imageio-ffmpeg (podcast y video);
# tzdata para que TZ funcione (fecha del briefing y horas de "Generado" en hora de Madrid).
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg tzdata \
    && rm -rf /var/lib/apt/lists/*

# Usuario sin privilegios (UID 1000: coincide con el usuario habitual de Linux en los volumenes).
RUN useradd --create-home --uid 1000 --shell /usr/sbin/nologin app

WORKDIR /app

# 1) Dependencias: capa que solo se reconstruye si cambia requirements.txt.
COPY requirements.txt ./
RUN pip install -r requirements.txt

# 2) Paquete briefer (editable: config.ROOT_DIR apunta a /app, no a site-packages).
COPY pyproject.toml README.md ./
COPY src/ src/
RUN pip install --no-deps -e .

# 3) App, scripts, datos de ejemplo y recursos (lo que mas cambia, al final).
COPY .streamlit/config.toml .streamlit/config.toml
COPY app/ app/
COPY scripts/ scripts/
COPY data/samples/ data/samples/
COPY docs/assets/ docs/assets/
COPY .env.example .env.example

RUN mkdir -p data/cache data/outputs \
    && chown -R app:app data

USER app

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8501/_stcore/health', timeout=4).status == 200 else 1)" || exit 1

# En el contenedor 0.0.0.0 es lo correcto: el aislamiento lo da el mapeo de puertos de Docker.
CMD ["streamlit", "run", "app/main.py", \
     "--server.port=8501", "--server.address=0.0.0.0", "--server.headless=true", \
     "--browser.gatherUsageStats=false"]
