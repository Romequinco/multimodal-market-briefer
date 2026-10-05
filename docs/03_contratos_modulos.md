# 03 · Contratos entre módulos

Este documento permite que los tres carriles trabajen **en paralelo** desde el día 0: cada carril programa
contra estos contratos y usa `providers/mock.py` y los datos de `data/samples/` mientras lo de los demás no
existe.

**Versión de contratos: v0.1 (05-oct-2026).** Fuente de verdad en código: `src/briefer/schemas.py` y
`src/briefer/providers/base.py`. Si el código y este documento discrepan, se corrige el que esté mal en el
mismo cambio.

## Reglas de cambio

1. `schemas.py` y `providers/base.py` son **transversales**: ningún carril los cambia en solitario.
2. Cambio **compatible** (campo nuevo con valor por defecto, función nueva): se avisa a los otros dos y se
   sube la versión menor (v0.1 → v0.2). No hace falta esperar respuesta.
3. Cambio **incompatible** (renombrar o quitar un campo, cambiar un tipo, cambiar una firma pública): se acuerda
   entre los tres **antes** de tocarlo, se sube la versión mayor y se actualizan mock y tests en el mismo cambio.
4. Toda modificación se refleja aquí y en el registro de cambios del final.
5. `tests/test_schemas.py` y `tests/test_pipeline_mock.py` deben pasar tras cualquier cambio de contrato.

---

## Schemas de datos

`src/briefer/schemas.py`, Pydantic v2. Todos heredan de una base común `_Model` con
`ConfigDict(validate_assignment=True, extra="forbid")`: se valida también al asignar un campo y **se
rechazan campos desconocidos**. Todos son serializables a JSON (`model_dump_json`). Las listas y dicts tienen
`default_factory` (por defecto vacíos).

Tipos auxiliares (alias `Literal`):

| Alias | Valores |
| --- | --- |
| `Sentiment` | `"positivo"`, `"negativo"`, `"neutral"` |
| `Speaker` | `"A"`, `"B"` |
| `SourceType` | `"pdf"`, `"chart"`, `"voice"`, `"text"` |
| `Channel` | `"web"`, `"email"`, `"telegram"` |

Otros símbolos públicos del módulo:

- `DISCLAIMER_ES: str`: aviso MiFID II («Contenido generado automáticamente con IA… No constituye
  asesoramiento financiero…»). Es el valor por defecto de `Analysis.disclaimer`, lo muestra la UI, lo imprime
  `scripts/demo.py` y debe aparecer en email, Telegram y al final del podcast.
- `new_briefing_id(now: datetime | None = None) -> str`: id legible y ordenable `YYYYMMDD-HHMMSS-xxxxxx`
  (6 caracteres hex de un `uuid4`). Es el `default_factory` de `Briefing.id` y el nombre de la carpeta del
  briefing en `data/outputs/`.

### Entradas y contexto

| Modelo | Campos | Notas |
| --- | --- | --- |
| `NewsItem` | `id: str`, `title: str`, `summary: str`, `source: str`, `url: str`, `published_at: datetime`, `tickers: list[str] = []`, `language: str = "es"` | `source` y `url` obligatorios: se citan siempre |
| `PriceSnapshot` | `ticker: str`, `last: float`, `change_pct: float`, `currency: str`, `history: list[tuple[date, float]] = []` | `change_pct` en %, no en tanto por uno |
| `Position` | `ticker: str`, `weight: float \| None = None`, `quantity: float \| None = None` | Basta con `weight` (0-1) o `quantity` (no se valida que haya al menos uno). Un validador pasa `ticker` a mayúsculas y quita espacios |
| `Portfolio` | `name: str`, `positions: list[Position] = []` | Dato personal (RGPD): no se persiste sin consentimiento |
| `DocumentInsight` | `source_type: SourceType`, `source_name: str`, `extracted_text: str`, `key_figures: dict[str, str] = {}`, `summary: str` | Salida común de PDF, gráfico, voz y texto libre |
| `MarketContext` | `date: date`, `tickers: list[str]`, `news: list[NewsItem] = []`, `prices: list[PriceSnapshot] = []`, `insights: list[DocumentInsight] = []`, `portfolio: Portfolio \| None = None` | Entrada única del Analista |

### Agentes

| Modelo | Campos | Notas |
| --- | --- | --- |
| `KeyPoint` | `title: str`, `explanation: str`, `tickers: list[str] = []`, `sentiment: Sentiment = "neutral"`, `sources: list[str] = []` | `sources` = ids/URLs de noticias o `source_name` de insights |
| `Analysis` | `date: date`, `headline: str`, `key_points: list[KeyPoint] = []`, `market_mood: str`, `disclaimer: str = DISCLAIMER_ES` | `disclaimer` nunca vacío |
| `ScriptLine` | `speaker: Speaker`, `text: str` | A = presentador/a que guía, B = analista; nombres en `BRIEFER_SPEAKER_A_NAME` / `BRIEFER_SPEAKER_B_NAME` |
| `PodcastScript` | `title: str`, `lines: list[ScriptLine] = []`, `est_duration_s: float = 0.0` | Objetivo 3-5 min (`BRIEFER_PODCAST_TARGET_MINUTES`); la última línea incluye el disclaimer hablado |

### Salidas

| Modelo | Campos | Notas |
| --- | --- | --- |
| `AudioSegment` | `speaker: Speaker`, `text: str`, `start_s: float`, `end_s: float` | Tramo por línea del guion; base para SRT y subtítulos del vídeo |
| `AudioAsset` | `path: Path`, `duration_s: float`, `segments: list[AudioSegment] = []` | Podcast final concatenado |
| `Transcript` | `text: str`, `srt_path: Path \| None = None` | `srt_path` es `None` si no hay tiempos de audio |
| `ChartAsset` | `path: Path`, `ticker: str \| None = None`, `kind: str` | `kind`: p. ej. `"price_line"`, `"overview_bar"`, `"portfolio_pie"` |
| `VideoAsset` | `path: Path`, `duration_s: float` | |
| `StepMetric` | `step: str`, `provider: str`, `model: str`, `latency_s: float`, `est_cost_eur: float = 0.0` | Coste **estimado** vía `costs.py`; lo crea `logging_utils.track_step` |
| `DeliveryResult` | `channel: Channel`, `ok: bool`, `detail: str = ""` | Resultado de entregar por un canal |
| `Briefing` | `id: str = new_briefing_id()`, `created_at: datetime = datetime.now()`, `context: MarketContext`, `analysis: Analysis`, `script: PodcastScript`, `audio: AudioAsset \| None = None`, `transcript: Transcript \| None = None`, `charts: list[ChartAsset] = []`, `cover_path: Path \| None = None`, `video: VideoAsset \| None = None`, `metrics: list[StepMetric] = []`, `deliveries: list[DeliveryResult] = []` | Resultado de `pipeline.run_briefing`; se guarda como `briefing.json`. `run_briefing` siempre añade a `deliveries` la entrada `web` |
| `QAAnswer` | `question: str`, `answer_text: str`, `audio_path: Path \| None = None`, `sources: list[str] = []` | Respuesta del Agente Q&A |

---

## Interfaces de proveedores

`src/briefer/providers/base.py`, clases abstractas (ABC). Todas heredan de `_Provider`, que define dos
atributos que cada implementación fija para `StepMetric` y `costs.py`:

- `provider_name: str`: nombre del proveedor (`"anthropic"`, `"edge"`, `"mock"`…). No siempre coincide con el
  valor de `.env`: `ClaudeVision.provider_name == "anthropic"` y `WhisperAPI.provider_name == "openai"`.
- `model: str`: modelo concreto (`"claude-sonnet-5-5"`, `"edge-tts"`, `"mock-llm"`…).

`LLMProvider` y `VisionProvider` tienen además `last_usage: dict[str, int]`
(`{"input_tokens": int, "output_tokens": int}`, inicializado en `__init__`), que cada llamada debe rellenar; el
pipeline lo pasa a `costs.estimate_cost_eur(...)`.

```python
class LLMProvider(_Provider):
    last_usage: dict[str, int]
    def complete(self, system: str, messages: list[dict],
                 response_model: type[BaseModel] | None = None) -> str | BaseModel: ...

class VisionProvider(_Provider):
    last_usage: dict[str, int]
    def describe(self, image: bytes, prompt: str) -> str: ...

class STTProvider(_Provider):
    def transcribe(self, audio_path: Path, language: str = "es") -> str: ...

class TTSProvider(_Provider):
    audio_extension: str = ".mp3"   # MockTTS usa ".wav"
    def synthesize(self, text: str, voice: str, out_path: Path) -> Path: ...  # devuelve la ruta REAL escrita

class ImageGenProvider(_Provider):
    def generate(self, prompt: str, out_path: Path) -> Path: ...

class ImageClassifier(_Provider):
    def classify(self, image: bytes, labels: list[str]) -> dict[str, float]: ...  # {etiqueta: prob}, suma ~1
```

Las implementaciones reales reciben `Settings` en el constructor (las de LLM, además, `cheap: bool = False`).
Los mocks de `providers/mock.py` (`MockLLM`, `MockVision`, `MockSTT`, `MockTTS`, `MockImageGen`,
`MockImageClassifier`) aceptan `settings` opcional y `model`; todos tienen `provider_name = "mock"`.

### Registro (`providers/registry.py`)

```python
def get_llm(settings: Settings | None = None, *, cheap: bool = False, force_mock: bool = False) -> LLMProvider: ...
def get_vision(settings: Settings | None = None, *, force_mock: bool = False) -> VisionProvider: ...
def get_stt(settings: Settings | None = None, *, force_mock: bool = False) -> STTProvider: ...
def get_tts(settings: Settings | None = None, *, force_mock: bool = False) -> TTSProvider: ...
def get_image_gen(settings: Settings | None = None, *, force_mock: bool = False) -> ImageGenProvider | None: ...
def get_image_classifier(settings: Settings | None = None, *, force_mock: bool = False) -> ImageClassifier | None: ...
def describe_providers(settings: Settings | None = None) -> dict[str, str]: ...  # resumen para la barra lateral de la UI

class ProviderConfigError(RuntimeError): ...  # proveedor desconocido, sin clave o sin dependencias
```

| Función | Variable de `.env` | Valores | Clave requerida |
| --- | --- | --- | --- |
| `get_llm` | `BRIEFER_LLM_PROVIDER` | `anthropic` · `gemini` · `openai` · `mock` | `ANTHROPIC_API_KEY` / `GEMINI_API_KEY` / `OPENAI_API_KEY` |
| `get_vision` | `BRIEFER_VISION_PROVIDER` | `claude` · `qwen_local` · `mock` | `ANTHROPIC_API_KEY` (solo `claude`) |
| `get_stt` | `BRIEFER_STT_PROVIDER` | `whisper_api` · `whisper_local` · `mock` | `OPENAI_API_KEY` (solo `whisper_api`) |
| `get_tts` | `BRIEFER_TTS_PROVIDER` | `edge` · `elevenlabs` · `mock` | `ELEVENLABS_API_KEY` (solo `elevenlabs`) |
| `get_image_gen` | `BRIEFER_IMAGE_GEN_PROVIDER` | `sdxl_turbo` · `none` · `mock` | — (`none` → devuelve `None`) |
| `get_image_classifier` | `BRIEFER_IMAGE_CLASSIFIER_PROVIDER` | `clip` · `none` · `mock` | — (`none` → devuelve `None`) |

Comportamiento:

- `mock` siempre está disponible. `force_mock=True` lo fuerza sin mirar `.env` (lo usa el pipeline cuando
  `use_mock=True`).
- `cheap=True` pide el modelo barato: `anthropic` usa `BRIEFER_LLM_MODEL_CHEAP`; `gemini` y `openai` aún
  ignoran el flag (TODO en su código); el mock devuelve `model="mock-llm-cheap"`.
- Las implementaciones reales se importan de forma **perezosa** (`importlib`): no hace falta instalar `torch`,
  `anthropic`… si no se usan.
- Si falta la clave o la librería: con `BRIEFER_FALLBACK_TO_MOCK=true` (por defecto) devuelve el mock y deja un
  aviso en el log; con `false` lanza `ProviderConfigError`. Un nombre de proveedor desconocido lanza
  `ProviderConfigError` siempre.

Contrato de comportamiento:

- `complete(..., response_model=X)` devuelve una instancia válida de `X` o lanza excepción; nunca un dict suelto.
- `synthesize` puede cambiar la extensión de `out_path` según `audio_extension`: usar siempre la ruta devuelta.
- Los proveedores no escriben fuera de `out_path` ni de `data/cache/`.
- Errores de red se propagan como excepción; los reintentos los decide el pipeline, no el proveedor.

---

## Funciones públicas por módulo

> Firmas **reales del código** (esqueleto del 05-oct-2026). Están implementados `pipeline.py`, `costs.py`,
> `config.py`, `logging_utils.py`, `agents.load_prompt` y `schemas.new_briefing_id`; el resto son *stubs* que
> lanzan `NotImplementedError` con un `TODO` que describe la implementación. Los carriles pueden añadir
> parámetros opcionales; cambiar tipos de entrada o salida sigue las reglas de cambio.

**Inyección de dependencias:** las funciones de `ingest/`, `agents/` y `media/` **reciben el proveedor por
parámetro**; solo `pipeline.get_providers` llama a `registry`.

### Orquestación (`pipeline.py`, `storage.py`, `costs.py`, `logging_utils.py`)

```python
# pipeline.py  (implementado)
ProgressFn = Callable[[str], None]

@dataclass
class Providers:  # llm, llm_cheap, vision, stt, tts, image_gen | None, classifier | None
    ...

def get_providers(settings: Settings, use_mock: bool = False) -> Providers: ...
def process_upload(path: Path, providers: Providers, metrics: list[StepMetric],
                   language: str = "es") -> DocumentInsight: ...  # enruta por extensión: PDF / imagen / audio
def run_briefing(tickers: Sequence[str], portfolio: Portfolio | None = None,
                 uploads: Sequence[Path] | None = None, make_video: bool = False,
                 deliver: Sequence[str] | None = None, *, make_cover: bool = False,
                 use_mock: bool = False, settings: Settings | None = None,
                 progress: ProgressFn | None = None) -> Briefing: ...
def answer_question(question: str | Path, briefing: Briefing | None = None, *, speak: bool = True,
                    history: list[dict] | None = None, use_mock: bool = False,
                    settings: Settings | None = None) -> QAAnswer: ...  # Path = audio → STT

# storage.py  (stubs)
def briefing_dir(briefing_id: str, base_dir: Path | None = None) -> Path: ...
def save_briefing(briefing: Briefing, base_dir: Path | None = None) -> Path: ...     # ruta de briefing.json
def load_briefing(path_or_id: Path | str, base_dir: Path | None = None) -> Briefing: ...
def list_briefings(base_dir: Path | None = None, limit: int = 50) -> list[Path]: ...  # rutas, más reciente primero

# costs.py  (implementado; tarifas aproximadas, TODO verificar)
def estimate_tokens(text: str) -> int: ...
def estimate_image_tokens(width: int, height: int) -> int: ...
def estimate_llm_cost_eur(model: str, input_tokens: int = 0, output_tokens: int = 0) -> float: ...
def estimate_stt_cost_eur(model: str, duration_s: float) -> float: ...
def estimate_tts_cost_eur(provider: str, n_chars: int) -> float: ...
def estimate_image_cost_eur(provider: str, n_images: int = 1) -> float: ...
def estimate_cost_eur(provider: str, model: str, **usage: float) -> float: ...
    # usage: input_tokens/output_tokens · duration_s · n_chars · n_images; proveedores locales → 0.0
def summarize_metrics(metrics: Iterable[StepMetric]) -> dict[str, float]: ...
    # {"steps", "total_latency_s", "total_cost_eur"}

# logging_utils.py  (implementado)
def get_logger(name: str | None = None) -> logging.Logger: ...
@contextmanager
def track_step(step: str, provider: str = "-", model: str = "-",
               metrics: list[StepMetric] | None = None) -> Iterator[StepHandle]: ...
    # mide la latencia y añade un StepMetric a `metrics`, también si el paso falla
```

Pasos que registra `run_briefing` (campo `StepMetric.step`): `ingest.news`, `ingest.tickers`,
`ingest.prices`, `ingest.pdf` / `ingest.chart` / `ingest.voice` (uno por subida), `agents.analyst`,
`agents.scriptwriter`, `media.podcast`, `media.transcript`, `media.charts`, `media.cover` (si `make_cover` y
hay proveedor de imagen), `media.video` (si `make_video`), `delivery.<canal>` (por canal de `deliver`) y
`storage.save` (este último solo va al log: se mide mientras se guarda, así que no queda en
`Briefing.metrics`). Con `use_mock=True` las noticias salen de `ingest.news.load_sample_news()` y los precios de
`ingest.prices.synthetic_snapshots()`. `answer_question` registra `qa.stt` (si la pregunta es un `Path`),
`agents.qa` (con el LLM barato) y `qa.tts` (si `speak`).

### Carril A · `ingest/`

```python
# news.py
def fetch_yfinance_news(ticker: str, max_items: int = 10) -> list[NewsItem]: ...
def fetch_rss_news(feeds: list[str], max_items: int = 20) -> list[NewsItem]: ...
def dedupe_news(items: list[NewsItem]) -> list[NewsItem]: ...
def fetch_news(tickers: list[str], max_items: int = 20, since: datetime | None = None,
               rss_feeds: list[str] | None = None) -> list[NewsItem]: ...
def load_sample_news(path: Path | None = None) -> list[NewsItem]: ...  # data/samples/noticias_ejemplo.json

# tickers.py
TICKER_UNIVERSE: dict[str, dict[str, list[str] | str]]  # tickers conocidos + alias (lo usa la UI)
def normalize_ticker(raw: str) -> str: ...
def extract_tickers(text: str, universe: list[str] | None = None) -> list[str]: ...
def filter_by_tickers(news: list[NewsItem], tickers: list[str]) -> list[NewsItem]: ...

# prices.py
def get_price_snapshot(ticker: str, period: str = "1mo") -> PriceSnapshot: ...
def get_price_snapshots(tickers: list[str], period: str = "1mo") -> list[PriceSnapshot]: ...
def synthetic_snapshots(tickers: list[str], days: int = 30, seed: int = 0) -> list[PriceSnapshot]: ...  # modo mock

# pdf_reader.py
def extract_page_texts(path: Path, max_pages: int = 30) -> list[str]: ...
def pages_needing_vision(page_texts: list[str], min_chars: int = 200) -> list[int]: ...
def page_images(path: Path, page_index: int) -> list[bytes]: ...
def read_pdf(path: Path, llm: LLMProvider, vision: VisionProvider | None = None,
             max_pages: int = 30) -> DocumentInsight: ...

# chart_reader.py
CHART_LABELS: list[str]   # etiquetas del clasificador zero-shot
CHART_PROMPT: str
def classify_image(image: bytes, classifier: ImageClassifier) -> tuple[str, float]: ...
def read_chart(image: bytes, source_name: str, vision: VisionProvider,
               llm: LLMProvider | None = None,
               classifier: ImageClassifier | None = None) -> DocumentInsight: ...

# portfolio.py
def load_portfolio_csv(source: Path | BinaryIO | str, name: str = "Mi cartera") -> Portfolio: ...
def portfolio_tickers(portfolio: Portfolio) -> list[str]: ...

# voice.py
def save_audio_upload(data: bytes, out_dir: Path, suffix: str = ".wav") -> Path: ...
def transcribe_question(audio_path: Path, stt: STTProvider, language: str = "es") -> str: ...
def voice_to_insight(audio_path: Path, stt: STTProvider, language: str = "es") -> DocumentInsight: ...
```

### Carril B · `agents/`

```python
# __init__.py  (implementado)
PROMPTS_DIR: Path
def load_prompt(name: str) -> str: ...  # contenido de agents/prompts/<name>.md

# analyst.py
def build_user_message(context: MarketContext, max_chars: int = 40_000) -> str: ...
def analyze(context: MarketContext, llm: LLMProvider) -> Analysis: ...

# scriptwriter.py
WORDS_PER_MINUTE = 150
def estimate_duration_s(lines: list[ScriptLine], wpm: int = WORDS_PER_MINUTE) -> float: ...
def write_script(analysis: Analysis, llm: LLMProvider, target_minutes: float = 4.0,
                 speaker_names: tuple[str, str] = ("Álvaro", "Elvira")) -> PodcastScript: ...

# qa.py
def build_qa_context(briefing: Briefing | None, max_chars: int = 20_000) -> str: ...
def answer(question: str, briefing: Briefing | None, llm: LLMProvider,
           history: list[dict] | None = None) -> QAAnswer: ...
```

Prompts en `agents/prompts/{analyst,scriptwriter,qa}.md`, cargados en tiempo de ejecución con `load_prompt`
(editables sin tocar código).

### Carril C · `media/` y `delivery/`

```python
# charts.py
def make_price_chart(snapshot: PriceSnapshot, out_dir: Path) -> ChartAsset: ...
def make_overview_chart(snapshots: list[PriceSnapshot], out_dir: Path) -> ChartAsset: ...
def make_portfolio_chart(portfolio: Portfolio, out_dir: Path) -> ChartAsset: ...
def make_charts(prices: list[PriceSnapshot], out_dir: Path,
                portfolio: Portfolio | None = None) -> list[ChartAsset]: ...

# podcast.py
def audio_duration_s(path: Path) -> float: ...
def concat_audio(paths: list[Path], out_path: Path, pause_s: float = 0.35) -> Path: ...
def synthesize_podcast(script: PodcastScript, tts: TTSProvider, out_dir: Path, voice_a: str,
                       voice_b: str, pause_s: float = 0.35) -> AudioAsset: ...

# transcript.py
def format_srt_timestamp(seconds: float) -> str: ...
def segments_to_srt(segments: list[AudioSegment], speaker_names: dict[str, str] | None = None) -> str: ...
def build_transcript(script: PodcastScript, segments: list[AudioSegment], out_dir: Path,
                     speaker_names: dict[str, str] | None = None) -> Transcript: ...

# cover.py
def build_cover_prompt(analysis: Analysis) -> str: ...
def overlay_title(image_path: Path, title: str, date_text: str) -> Path: ...
def make_cover(analysis: Analysis, image_gen: ImageGenProvider | None, out_dir: Path) -> Path | None: ...

# video.py
def make_video(audio: AudioAsset, images: list[Path], out_path: Path,
               transcript: Transcript | None = None, size: tuple[int, int] = (1080, 1920),
               fps: int = 24) -> VideoAsset: ...

# email_sender.py
def build_email_html(briefing: Briefing) -> str: ...
def send_briefing_email(briefing: Briefing, to: list[str] | None = None,
                        settings: Settings | None = None) -> DeliveryResult: ...

# telegram_sender.py
API_URL = "https://api.telegram.org/bot{token}/{method}"
def build_caption(briefing: Briefing, max_len: int = 1024) -> str: ...
def send_briefing_telegram(briefing: Briefing, chat_id: str | None = None,
                           settings: Settings | None = None) -> DeliveryResult: ...
```

---

## Qué consume y qué produce cada carril

```mermaid
flowchart LR
    subgraph A["Carril A · Entradas y procesado"]
        A1["NewsItem[]<br/>PriceSnapshot[]<br/>DocumentInsight[]<br/>Portfolio<br/>texto de la pregunta"]
    end
    subgraph B["Carril B · Agentes y orquestación"]
        B1["MarketContext → Analysis<br/>Analysis → PodcastScript<br/>pregunta + Briefing → respuesta<br/>run_briefing / answer_question"]
    end
    subgraph C["Carril C · Salidas, entrega y UI"]
        C1["AudioAsset · Transcript<br/>ChartAsset[] · VideoAsset<br/>DeliveryResult · páginas Streamlit"]
    end
    A -- "MarketContext" --> B
    B -- "PodcastScript, Analysis" --> C
    A -- "PriceSnapshot[] (gráficos)" --> C
    C -- "Briefing (UI) / audio de la pregunta" --> B
```

| Carril | Ficheros | Consume | Produce | Mientras no exista lo de otros, usa |
| --- | --- | --- | --- | --- |
| **A** · Entradas y procesado | `ingest/*`, `providers/vision/*`, `providers/stt/*`, `providers/image/clip_classifier.py` | Tickers, ficheros subidos (PDF, imagen, audio), CSV de cartera | `NewsItem[]`, `PriceSnapshot[]`, `DocumentInsight[]`, `Portfolio`, texto de la pregunta | `data/samples/*`, `MockVision`, `MockSTT` |
| **B** · Agentes y orquestación | `agents/*`, `agents/prompts/*`, `pipeline.py`, `costs.py`, `providers/llm/*`, `scripts/demo.py` | `MarketContext` (de A), `Briefing` para el Q&A | `Analysis`, `PodcastScript`, `QAAnswer`, `Briefing` completo con `metrics` y `deliveries` | `MarketContext` construido desde `data/samples/`, `MockLLM`, funciones de A y C en versión mock |
| **C** · Salidas, entrega y UI | `media/*`, `delivery/*`, `providers/tts/*`, `providers/image/sdxl_turbo.py`, `app/*` | `PodcastScript`, `Analysis`, `PriceSnapshot[]`, `Briefing` | `AudioAsset`, `Transcript`, `ChartAsset[]`, `VideoAsset`, `cover.png`, `DeliveryResult`, UI | `PodcastScript` y `Briefing` de ejemplo generados por `MockLLM`, `MockTTS` |
| Transversal | `schemas.py`, `providers/base.py`, `providers/registry.py`, `providers/mock.py`, `config.py`, `logging_utils.py`, `storage.py`, `tests/`, docs, Docker | — | Contratos, configuración, métricas, persistencia y modo mock | — |

### Puntos de integración (por orden)

1. **Modo mock:** `load_sample_news` + `synthetic_snapshots` + `filter_by_tickers` (A) → `analyze` +
   `write_script` con `MockLLM` (B) → `synthesize_podcast` + `build_transcript` + `make_charts` (C) →
   `save_briefing`. Hecho cuando se quita el `skip` de `tests/test_pipeline_mock.py` y pasa.
2. **A → B real:** `MarketContext` construido con `fetch_news` + `get_price_snapshots` + insights de
   `process_upload` → `analyze()`.
3. **B → C real:** `write_script()` → `synthesize_podcast()` con `EdgeTTS`.
4. **C → B:** la UI llama a `pipeline.run_briefing()` / `pipeline.answer_question()` y a `storage` para el
   histórico; no instancia proveedores.
5. **Fin a fin:** `python scripts/demo.py --mock` y `python scripts/demo.py` (con claves) producen un
   `briefing.json` válido en `data/outputs/<id>/`.

---

## Registro de cambios de contrato

| Versión | Fecha | Cambio | Acordado por |
| --- | --- | --- | --- |
| v0.1 | 05-oct-2026 | Versión inicial, alineada con el código del esqueleto. Incluye `Briefing.deliveries` (añadido respecto a la spec inicial), `DISCLAIMER_ES`, `new_briefing_id`, `provider_name`/`model`/`last_usage` en proveedores y `registry` con `cheap`/`force_mock` | Equipo |
