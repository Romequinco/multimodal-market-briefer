# 03 · Contratos entre módulos

Este documento permite que los tres carriles trabajen **en paralelo** desde el día 0: cada carril programa
contra estos contratos y usa `providers/mock.py` y los datos de `data/samples/` mientras lo de los demás no
existe.

**Versión de contratos: v0.3 (05-oct-2026, cierre de la Fase 1 · camino real).** Fuente de verdad en código:
`src/briefer/schemas.py` (`CONTRACTS_VERSION = "0.3"`) y `src/briefer/providers/base.py`. Si el código y este
documento discrepan, se corrige el que esté mal en el mismo cambio. Cambios respecto a v0.1 y v0.2: ver el
[registro de cambios](#registro-de-cambios-de-contrato) al final (todos **aditivos**: ningún campo ni firma
anterior cambia de tipo ni desaparece; solo se añaden campos con valor por defecto, parámetros opcionales
*keyword-only* y funciones nuevas).

> A partir del martes 6-oct a las 13:00 (Sync 1) **solo se admiten cambios aditivos** en `schemas.py` y
> `providers/base.py`, con un único responsable de hacer el merge (ver [05](05_roadmap_TODO.md#reglas-de-trabajo)).
> Este documento queda congelado salvo el registro de cambios y las firmas que cambien.

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
| `StepMetric` | `step: str`, `provider: str`, `model: str`, `latency_s: float`, `est_cost_eur: float = 0.0`, `error: str \| None = None`, `detail: str \| None = None` | Coste **estimado** vía `costs.py`; lo crea `logging_utils.track_step`. **v0.2:** `error` = `"Tipo: mensaje"` (recortado) si el paso falló, `None` si fue bien; `model` queda siempre limpio. **v0.3 (semántica):** si el proveedor real falló y el paso se completó con un **sustituto**, `error` empieza por `"Fallback a "` (p. ej. `"Fallback a mock tras RateLimitError: 429 …"`) y `provider`/`model` son los del sustituto (`mock`, `samples`, `synthetic`, `local`/`fallback_script`); se detecta con `logging_utils.step_fell_back`. **v0.3 (campo):** `detail` = notas de calidad para la traza (grounding de cifras, reintentos del Guionista, noticias filtradas…); `None` si no hay nada que contar |
| `DeliveryResult` | `channel: Channel`, `ok: bool`, `detail: str = ""` | Resultado de entregar por un canal |
| `Briefing` | `id: str = new_briefing_id()`, `created_at: datetime = datetime.now()`, `context: MarketContext`, `analysis: Analysis`, `script: PodcastScript`, `audio: AudioAsset \| None = None`, `transcript: Transcript \| None = None`, `charts: list[ChartAsset] = []`, `cover_path: Path \| None = None`, `video: VideoAsset \| None = None`, `metrics: list[StepMetric] = []`, `deliveries: list[DeliveryResult] = []` | Resultado de `pipeline.run_briefing`; se guarda como `briefing.json`. `run_briefing` siempre añade a `deliveries` la entrada `web` |
| `QAAnswer` | `question: str`, `answer_text: str`, `audio_path: Path \| None = None`, `sources: list[str] = []`, `metrics: list[StepMetric] = []` | Respuesta del Agente Q&A. **v0.2:** `metrics` lleva los pasos `qa.stt` / `agents.qa` / `qa.tts` de esa pregunta, para demostrar el objetivo de latencia (< 10 s) en la UI |

**Persistencia (`briefing.json`).** `storage.save_briefing` escribe las rutas de ficheros que están **dentro** de
la carpeta del briefing como **relativas** a ella y con `/` (`podcast.wav`, `charts/AAPL_price.png`), de modo
que la carpeta se puede mover a otra máquina o a Docker; `load_briefing` las resuelve de nuevo contra la carpeta
donde está el JSON. Las rutas de fuera de la carpeta se guardan tal cual. En memoria, los `Path` de `Briefing`
son siempre absolutos o relativos al directorio de trabajo; el formato relativo solo existe en disco.

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
- `cheap=True` pide el modelo barato: `anthropic` usa `BRIEFER_LLM_MODEL_CHEAP` (Haiku 4.5, sin `effort`);
  `gemini` usa el mismo `BRIEFER_GEMINI_MODEL` con el razonamiento desactivado o reducido; `openai` es un
  *stub* (ver abajo); el mock devuelve `model="mock-llm-cheap"`.
- Las implementaciones reales se importan de forma **perezosa** (`importlib`): no hace falta instalar `torch`,
  `anthropic`… si no se usan.
- Si falta la clave o la librería: con `BRIEFER_FALLBACK_TO_MOCK=true` (por defecto) devuelve el mock y deja un
  aviso en el log; con `false` lanza `ProviderConfigError`. Un nombre de proveedor desconocido lanza
  `ProviderConfigError` siempre.

Contrato de comportamiento:

- `complete(..., response_model=X)` devuelve una instancia válida de `X` o lanza excepción; nunca un dict suelto.
- `synthesize` puede cambiar la extensión de `out_path` según `audio_extension`: usar siempre la ruta devuelta.
- Los proveedores no escriben fuera de `out_path` ni de `data/cache/`.
- **Reintentos (corregido en v0.3):** hay dos niveles. (1) Cada proveedor real reintenta **solo errores
  transitorios** de red o del servicio, con su propio mecanismo: `AnthropicLLM` / `ClaudeVision` con el SDK
  (`max_retries=3`, backoff exponencial ante 408/409/429/5xx/529; timeout 120 s, 10 s de conexión);
  `GeminiLLM` con `HttpRetryOptions` (4 intentos ante 408/429/5xx); `EdgeTTS` con `retries=2` y espera lineal
  (`backoff_s`) ante websocket cerrado, `NoAudioReceived`, *timeouts* y 429/503. Los errores de uso (texto
  vacío, voz mal formada, 400) no se reintentan. (2) Con salida estructurada, `_structured.complete_structured`
  hace **un** reintento autocorrectivo si el JSON no valida. Por encima, el **pipeline** decide qué hacer
  cuando el proveedor ya ha agotado sus reintentos: `synthesize_podcast(retries=2)` por línea, reintentos de
  calidad de los agentes y caída a sustituto del paso núcleo (ver «Pasos núcleo y pasos opcionales»).
  Lo que un proveedor no consigue tras sus reintentos se propaga como excepción.

---

## Funciones públicas por módulo

> Firmas **reales del código** al cierre de la Fase 1 (05-oct-2026). Estado por función:
> **[impl]** implementada y probada (sin red, con mocks o *fixtures*; lo que usa red se probó además en real,
> ver [06](06_estado_actual.md)) · **[stub]** lanza `NotImplementedError` con un `TODO` que describe la
> implementación. Los carriles pueden añadir parámetros **opcionales** (con valor por defecto, preferiblemente
> *keyword-only*); cambiar tipos de entrada o salida sigue las reglas de cambio. Marcado **(v0.3)** lo añadido
> en la Fase 1.

**Inyección de dependencias:** las funciones de `ingest/`, `agents/` y `media/` **reciben el proveedor por
parámetro**; solo `pipeline` llama a `registry`.

### Orquestación (`pipeline.py`, `storage.py`, `costs.py`, `logging_utils.py`)

```python
# pipeline.py  [impl]
ProgressFn = Callable[[str], None]
DELIVERY_CHANNELS: tuple[str, ...] = ("email", "telegram")   # "web" va siempre incluido
PDF_EXTS = {".pdf"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
AUDIO_EXTS = {".wav", ".mp3", ".m4a", ".ogg", ".webm", ".flac"}
RunMode = Literal["real", "mock", "demo_voices"]               # (v0.3)
RUN_MODES: tuple[str, ...]                                     # (v0.3) ("real", "mock", "demo_voices")
PODCAST_TTS_WORKERS = 6                                        # (v0.3) hilos de edge-tts en el podcast
UPLOAD_WORKERS = 4                                             # (v0.3) subidas procesadas a la vez

class PipelineStepError(RuntimeError):          # fallo de un paso NÚCLEO; .step = nombre del paso,
    step: str                                   # la causa original en __cause__
class StepNotImplementedError(PipelineStepError, NotImplementedError): ...
    # paso núcleo aún sin implementar: la UI lo pinta como «Pendiente» (es también NotImplementedError)

@dataclass
class Providers:  # llm, llm_cheap, vision, stt, tts, image_gen | None, classifier | None
    ...

def resolve_mode(mode: str | None = None, use_mock: bool = False) -> str: ...   # (v0.3)
    # mode manda si se indica; si no, use_mock=True -> "mock", False -> "real"; modo desconocido -> ValueError
def demo_voice_tts(settings: Settings) -> TTSProvider: ...   # (v0.3) edge-tts real para "demo_voices"
def get_providers(settings: Settings, use_mock: bool = False) -> Providers: ...
def process_upload(path: Path, providers: Providers, metrics: list[StepMetric],
                   language: str = "es") -> DocumentInsight: ...
    # enruta por extensión: PDF / imagen / audio; extensión no soportada -> ValueError
    # (registrado como paso "ingest.upload"). Propaga errores: run_briefing decide omitir la subida.
def run_briefing(tickers: Sequence[str], portfolio: Portfolio | None = None,
                 uploads: Sequence[Path] | None = None, make_video: bool = False,
                 deliver: Sequence[str] | None = None, *, make_cover: bool = False,
                 use_mock: bool = False, mode: RunMode | None = None,       # mode (v0.3)
                 use_cache: bool = True,                                     # (v0.3)
                 settings: Settings | None = None,
                 progress: ProgressFn | None = None) -> Briefing: ...
    # Raises: ValueError (sin tickers ni cartera, canal de `deliver` desconocido o modo desconocido:
    #         se valida ANTES de gastar nada) · PipelineStepError / StepNotImplementedError
def answer_question(question: str | Path, briefing: Briefing | None = None, *, speak: bool = True,
                    history: list[dict] | None = None, use_mock: bool = False,
                    mode: RunMode | None = None,                             # (v0.3)
                    settings: Settings | None = None) -> QAAnswer: ...
    # Path = audio -> STT. El texto hablado pasa por media.speech.normalize_for_speech antes del TTS.
    # Raises: ValueError (pregunta vacía), PipelineStepError (qa.stt / agents.qa)
```

**Modos (v0.3).** `use_mock=True` equivale a `mode="mock"` (se mantiene por compatibilidad); si se pasa `mode`,
manda sobre `use_mock`.

| `mode` | Proveedores de IA | Noticias / precios | TTS | Red / claves |
| --- | --- | --- | --- | --- |
| `"real"` | los de `.env` | reales (`fetch_news`, `get_price_snapshots`) con caché diaria; `use_cache=False` la ignora y la refresca (botón «Refrescar datos», `demo.py --refresh`) | el de `.env` | sí / sí |
| `"mock"` | todos mock | `data/samples` + precios sintéticos | `MockTTS` (WAV mudo) | no / no |
| `"demo_voices"` | mock (LLM, visión, STT) | `data/samples` + precios sintéticos | **edge-tts real** (`demo_voice_tts`); si no responde, cae a `MockTTS` marcado como fallback | sí / no |

**Índices de contexto (v0.3).** `settings.context_tickers` (`BRIEFER_CONTEXT_TICKERS`, por defecto
`^IBEX,^GSPC`) se añaden a la petición de noticias y precios, pero **no** entran en `MarketContext.tickers`
(los tickers del usuario). Salen en el gráfico de variación del día (`make_charts(..., line_tickers=…)`), no con
gráfico de cotización propio.

```python
# storage.py  [impl]
BRIEFING_FILE = "briefing.json"
DEMO_BRIEFING_DIRNAME = "demo_briefing"                                             # (v0.3)
def briefing_dir(briefing_id: str, base_dir: Path | None = None) -> Path: ...  # valida el id (sin "../")
def save_briefing(briefing: Briefing, base_dir: Path | None = None) -> Path: ...     # ruta de briefing.json
def load_briefing(path_or_id: Path | str, base_dir: Path | None = None) -> Briefing: ...
def list_briefings(base_dir: Path | None = None, limit: int = 50) -> list[Path]: ...  # más reciente primero
    # rutas internas relativas y con "/" en disco (ver «Persistencia» arriba)
def demo_briefing_dir(samples_dir: Path | None = None) -> Path: ...                 # (v0.3) data/samples/demo_briefing
def load_demo_briefing(samples_dir: Path | None = None) -> Briefing | None: ...      # (v0.3)
    # None si no existe; JSON corrupto o fuera de contrato -> ValueError / ValidationError (falla alto)
def latest_briefing(base_dir: Path | None = None, max_tries: int = 5) -> Briefing | None: ...  # (v0.3)
    # el guardado más reciente que cargue (salta JSON corruptos)
def load_featured_briefing(base_dir: Path | None = None,
                           samples_dir: Path | None = None) -> tuple[Briefing, str] | None: ...  # (v0.3)
    # portada de la app: (último guardado, "guardado") o, si no hay, (pregenerado, "pregenerado")
def export_briefing(briefing: Briefing, dest_dir: Path) -> Path: ...                # (v0.3)
    # copia audio, SRT, gráficos, portada y vídeo a dest_dir con nombres estables y escribe el JSON
    # con rutas relativas (así se creó data/samples/demo_briefing/); quita ficheros inexistentes

# costs.py  [impl; tarifas Anthropic verificadas el 05-oct-2026, resto estimación a verificar]
USD_TO_EUR = 0.86
LLM_PRICES_USD_PER_MTOK: dict[str, tuple[float, float]]   # claude-sonnet-5-5 (2, 10) · claude-haiku-4-5 (1, 5)…
def estimate_tokens(text: str) -> int: ...
def estimate_image_tokens(width: int, height: int) -> int: ...
def llm_price_usd_per_mtok(model: str) -> tuple[float, float] | None: ...   # por prefijo de modelo
def estimate_llm_cost_eur(model: str, input_tokens: int = 0, output_tokens: int = 0) -> float: ...
def estimate_stt_cost_eur(model: str, duration_s: float) -> float: ...
def estimate_tts_cost_eur(provider: str, n_chars: int) -> float: ...
def estimate_image_cost_eur(provider: str, n_images: int = 1) -> float: ...
def estimate_cost_eur(provider: str, model: str, **usage: float) -> float: ...
    # usage: input_tokens/output_tokens · duration_s · n_chars · n_images; LOCAL_PROVIDERS -> 0.0
    # (incluye "samples", "synthetic", "local", "edge"…)
def summarize_metrics(metrics: Iterable[StepMetric]) -> dict[str, float]: ...
    # {"steps", "total_latency_s", "total_cost_eur"}

# logging_utils.py  [impl]
def get_logger(name: str | None = None) -> logging.Logger: ...
@dataclass
class StepHandle:  # step, provider, model, est_cost_eur, metric, error, detail (v0.3)
    ...
@contextmanager
def track_step(step: str, provider: str = "-", model: str = "-",
               metrics: list[StepMetric] | None = None) -> Iterator[StepHandle]: ...
    # mide la latencia y añade un StepMetric a `metrics`, también si el paso falla; en ese caso
    # rellena StepMetric.error ("Tipo: mensaje") y relanza la excepción. Dentro del bloque se
    # pueden fijar handle.provider / model / est_cost_eur / error / detail.
FALLBACK_PREFIX = "Fallback a "                                         # (v0.3)
def fallback_error(substitute: str, exc: BaseException) -> str: ...     # (v0.3)
    # "Fallback a <sustituto> tras <Tipo>: <mensaje>"
def step_failed(metric: StepMetric) -> bool: ...     # True si el proveedor falló (también si hubo fallback)
def step_fell_back(metric: StepMetric) -> bool: ...  # (v0.3) True si error empieza por "Fallback a "
def step_error(metric: StepMetric) -> str | None: ...    # texto del error, o None
```

#### Pasos núcleo y pasos opcionales

`run_briefing` clasifica cada paso (campo `StepMetric.step`). Un paso **opcional** que falla deja su
`StepMetric` con `error` relleno, se registra en el log y el briefing sigue sin esa pieza. Un paso **núcleo**
cuyo proveedor real falla (tras sus propios reintentos) se **repite con un sustituto** si
`BRIEFER_FALLBACK_TO_MOCK=true` y el modo es `"real"` (v0.3); si no hay sustituto (pasos locales, modo mock,
fallback desactivado) o el sustituto también falla, aborta con `PipelineStepError`.

| Tipo | Paso (`StepMetric.step`) | Sustituto si el proveedor real falla (v0.3) |
| --- | --- | --- |
| **Núcleo** | `ingest.news` | `data/samples` (`load_sample_news`; `provider="samples"`) |
| **Núcleo** | `ingest.prices` | precios sintéticos (`synthetic_snapshots`; `provider="synthetic"`) |
| **Núcleo** | `agents.analyst` | `MockLLM` |
| **Núcleo** | `agents.scriptwriter` | guion de respaldo determinista (`fallback_script`; `provider="local"`, `model="fallback_script"`) si el LLM no devuelve un guion válido; si aun así lanza, `MockLLM` barato |
| **Núcleo** | `media.podcast` | `MockTTS` |
| **Núcleo** | `ingest.tickers`, `media.transcript`, `media.charts` | ninguno (locales): `PipelineStepError` |
| **Opcional** | `ingest.pdf` / `ingest.chart` / `ingest.voice` / `ingest.upload` (uno por subida), `media.cover` (si `make_cover` y hay proveedor de imagen), `media.video` (si `make_video`), `delivery.<canal>` (uno por canal), `storage.save` | Se omite: subida sin insight, `cover_path=None`, `video=None`, `DeliveryResult(ok=False, detail="Error al enviar: …")`, briefing solo en memoria |

**Semántica del fallback (v0.3).** Se registra **un solo** `StepMetric` por paso: `provider`/`model` del
sustituto, `latency_s` = tiempo total (intento fallido + sustituto), `est_cost_eur` = suma de ambos,
`error = fallback_error(etiqueta, causa)` (empieza por `"Fallback a "`) y `detail` combinado. La UI (insignias,
avisos de `render_run_warnings` y nodo naranja en «Cómo se hizo») usa `step_fell_back` para avisar de que ese
paso usó datos o modelos simulados. `step_failed` sigue siendo `True` en ese caso (el proveedor falló).

Además: `make_charts` aísla cada gráfico (si uno falla, el resto sale); `synthesize_podcast` reintenta cada línea
(`retries`); el Analista pide **una** corrección si hay cifras no trazables (puerta de *grounding*, v0.3) y el
Guionista reescribe una vez si el guion no cumple.

`answer_question`: `qa.stt` (si la pregunta es un `Path`) y `agents.qa` (con el LLM barato) son núcleo;
`agents.qa` cae a `MockLLM` marcado igual que el Analista (v0.3). `qa.tts` (si `speak`) es opcional: si falla,
se devuelve el texto con `audio_path=None`. Los tres pasos van en `QAAnswer.metrics`.

#### Progreso, métricas, concurrencia y tickers

- **Progreso:** el callback `progress` recibe un texto por paso con el formato `"(n/N) mensaje"`
  (p. ej. `"(3/6) Escribiendo el guion del podcast…"` sin subidas ni extras); `N` = 5 pasos fijos + 1 por subida + portada + vídeo +
  1 por canal + guardado. El último mensaje es `"(N/N) Briefing listo."`. Un fallo del callback nunca rompe el
  briefing.
- **Concurrencia (v0.3):** noticias ∥ precios ∥ subidas (cada subida en su hilo, con sus propias instancias de
  LLM barato y visión para no mezclar `last_usage`); el podcast sintetiza `PODCAST_TTS_WORKERS` líneas a la vez.
  Las métricas de las subidas se añaden en el orden de subida.
- **Métricas:** `Briefing.metrics` incluye **todos** los pasos, también `storage.save` (se guarda, se añade la
  métrica del guardado y se reescribe el JSON; esa segunda escritura no se mide).
- **`StepMetric.detail` (v0.3)** lo rellenan: `ingest.tickers` (`"N de M noticias relevantes (k de índices de
  contexto)"`), `agents.analyst` (resultado de la puerta de *grounding*: `"grounding: todas las cifras
  trazables"`, `"… -> 1 reintento"`, `"eliminadas frases con …"`) y `agents.scriptwriter` (reintentos,
  respaldo, nº de intervenciones y duración estimada).
- **Coste por paso con dos modelos:** `ingest.pdf` e `ingest.chart` suman en `est_cost_eur` el coste del LLM
  barato **y** de visión de todas las llamadas del paso (envoltorios `_MeteredLLM` / `_MeteredVision`);
  `agents.analyst` y `agents.scriptwriter` incluyen los reintentos.
- **Tickers:** la lista de entrada (más los de la cartera) se normaliza con `ingest.tickers.normalize_ticker`
  (`"santander"` → `"SAN.MC"`, `"aapl"` → `"AAPL"`), sin duplicados, antes de filtrar noticias y pedir precios.
- **Modo mock / demo_voices:** noticias de `ingest.news.load_sample_news()` y precios de
  `ingest.prices.synthetic_snapshots()`; si ningún ticker elegido aparece en las noticias de ejemplo, se usan
  todas (son ficticias y lo indican). Lo mismo si `ingest.news` cayó a `data/samples` en modo real.

### Carril A · `ingest/`

```python
# cache.py  [impl, nuevo en v0.3] — caché diaria en disco ("best effort": nunca rompe la ingesta)
def cache_dir() -> Path: ...                                   # settings.cache_path (BRIEFER_CACHE_DIR), lo crea
def cache_key(*parts: object) -> str: ...                      # md5 corto (12 hex) de las partes
def cache_file(source: str, key: str, day: date | None = None) -> Path: ...  # <fuente>_<clave>_<YYYYMMDD>.json
def read_cache(source: str, key: str, day: date | None = None) -> Any | None: ...  # None si no hay o está dañado
def write_cache(source: str, key: str, data: Any, day: date | None = None) -> None: ...  # atómica; errores solo al log
def purge_old(keep_days: int = 1) -> int: ...                  # borra entradas de días anteriores

# news.py  [impl]
SAMPLE_NEWS_FILE = "noticias_ejemplo.json"
HTTP_TIMEOUT = 8.0; TOTAL_TIMEOUT = 25.0                      # (v0.3) por petición / espera total de fuentes
GOOGLE_NEWS_DAYS = 7
DEFAULT_MARKET_FEEDS: tuple[str, ...]                          # (v0.3) Expansión «Mercados» + Europa Press
WINDOWS_HOURS = (48, 72, 168); MIN_PER_TICKER = 3; SUMMARY_MAX_CHARS = 600
last_fetch_stats: dict[str, dict[str, Any]]                    # (v0.3) por fuente: items, latency_s, cached, error
class NewsFetchError(RuntimeError): ...                        # (v0.3) fallaron TODAS las fuentes esenciales
def clean_html(text: str | None, max_chars: int = SUMMARY_MAX_CHARS) -> str: ...      # (v0.3)
def news_id(url: str, title: str = "") -> str: ...                                   # (v0.3) "n-" + sha1
def parse_yfinance_item(raw: dict, ticker: str) -> NewsItem | None: ...              # (v0.3) formato antiguo y nuevo
def parse_feed(content: bytes | str, feed_url: str = "", max_items: int = 20,
               default_language: str = "es", default_source: str = "") -> list[NewsItem]: ...  # (v0.3)
def fetch_yfinance_news(ticker: str, max_items: int = 10) -> list[NewsItem]: ...
    # yfinance + respaldo en el RSS de titulares de Yahoo; nunca lanza (red -> [] + aviso).
    # Nota 05-oct: la API de noticias de yfinance devuelve 404; se desactiva hasta el día siguiente
def fetch_rss_news(feeds: list[str], max_items: int = 20) -> list[NewsItem]: ...     # feed caído -> se salta
def google_news_query(ticker: str) -> str: ...                 # (v0.3) '"Banco Santander" (acciones OR bolsa OR …)'
def google_news_url(query: str, days: int | None = GOOGLE_NEWS_DAYS) -> str: ...     # (v0.3) hl=es, gl=ES
def fetch_google_news(ticker: str, max_items: int = 15,
                      days: int = GOOGLE_NEWS_DAYS) -> list[NewsItem]: ...            # (v0.3) nunca lanza
def dedupe_news(items: list[NewsItem]) -> list[NewsItem]: ...                         # por URL y título
def fetch_news(tickers: list[str], max_items: int = 20, since: datetime | None = None,
               rss_feeds: list[str] | None = None, *,
               max_per_ticker: int | None = None, use_cache: bool = True) -> list[NewsItem]: ...  # (v0.3: kw)
    # Por ticker: yfinance + RSS Yahoo + Google News (es); + feeds de mercado. En paralelo, caché diaria
    # por fuente y ticker, etiquetado con extract_tickers, dedupe, ventana 48 h -> 72 h -> 7 días, cupo
    # por ticker y total. Raises NewsFetchError si fallan todas las fuentes esenciales (yfinance no cuenta)
def load_sample_news(path: Path | None = None) -> list[NewsItem]: ...                 # data/samples/

# tickers.py  [impl]
TICKER_UNIVERSE: dict[str, dict[str, list[str] | str]]   # tickers conocidos + nombre + alias (lo usa la UI)
MARKET_INDEX_TICKERS: tuple[str, ...] = ("^IBEX", "^GSPC")  # noticias "de mercado" para rellenar
def normalize_ticker(raw: str) -> str: ...
    # ticker exacto, raíz ("san"), nombre o alias sin tildes/mayúsculas -> ticker Yahoo;
    # desconocido -> en mayúsculas y sin espacios; vacío -> ValueError
def extract_tickers(text: str, universe: list[str] | None = None) -> list[str]: ...
def filter_by_tickers(news: list[NewsItem], tickers: list[str], min_items: int = 3) -> list[NewsItem]: ...
    # devuelve copias con NewsItem.tickers rellenado; si quedan < min_items, completa con noticias
    # de MARKET_INDEX_TICKERS; tickers vacío -> todas

# prices.py  [impl]
DOWNLOAD_TIMEOUT = 10
class PriceFetchError(RuntimeError): ...                       # (v0.3) ningún ticker con precio
def snapshot_from_closes(ticker: str, closes: Any, currency: str) -> PriceSnapshot: ...  # (v0.3)
def get_price_snapshots(tickers: list[str], period: str = "1mo", *,
                        use_cache: bool = True) -> list[PriceSnapshot]: ...           # (v0.3: use_cache)
    # caché del día por ticker+periodo; los que falten en UNA descarga en lote (yf.download), y si el
    # lote falla, uno a uno; divisa de fast_info o currency_for. Ticker sin datos -> se omite con aviso
    # (nunca sintético en real). Raises PriceFetchError si no hay precio de ninguno
def get_price_snapshot(ticker: str, period: str = "1mo", *, use_cache: bool = True) -> PriceSnapshot: ...
    # sin datos -> ValueError
def currency_for(ticker: str) -> str: ...                     # ".MC"/"^IBEX" -> EUR; resto USD
def synthetic_snapshots(tickers: list[str], days: int = 30, seed: int = 0,
                        end: date | None = None) -> list[PriceSnapshot]: ...          # modo mock / fallback
    # determinista por ticker; `end` = última sesión (por defecto hoy; fin de semana -> viernes)

# pdf_reader.py  [impl; usa los proveedores inyectados]
MAX_VISION_PAGES = 5         # páginas pobres en texto que se mandan a visión, como mucho
MAX_LLM_CHARS = 30_000       # texto máximo que se pasa al LLM que estructura
MAX_IMAGES_PER_PAGE = 2
def extract_page_texts(path: Path, max_pages: int = 30) -> list[str]: ...
def pages_needing_vision(page_texts: list[str], min_chars: int = 200) -> list[int]: ...
def page_images(path: Path, page_index: int) -> list[bytes]: ...
def read_pdf(path: Path, llm: LLMProvider, vision: VisionProvider | None = None,
             max_pages: int = 30) -> DocumentInsight: ...
    # Raises FileNotFoundError / ValueError (PDF ilegible, cifrado o vacío)

# chart_reader.py  [impl; usa los proveedores inyectados]
CHART_LABELS: list[str]      # etiquetas del clasificador zero-shot; la última = "no es un gráfico"
NOT_CHART_LABEL: str
NOT_CHART_THRESHOLD = 0.6
SUPPORTED_FORMATS = {"PNG", "JPEG", "WEBP", "GIF"}
CHART_PROMPT: str
def validate_image(image: bytes) -> str: ...   # formato ("PNG"…); vacía/corrupta/no soportada -> ValueError
def classify_image(image: bytes, classifier: ImageClassifier) -> tuple[str, float]: ...
def read_chart(image: bytes, source_name: str, vision: VisionProvider,
               llm: LLMProvider | None = None,
               classifier: ImageClassifier | None = None) -> DocumentInsight: ...

# portfolio.py  [impl]
WEIGHT_TOLERANCE = 0.02
def load_portfolio_csv(source: Path | BinaryIO | str, name: str = "Mi cartera") -> Portfolio: ...
def portfolio_tickers(portfolio: Portfolio) -> list[str]: ...

# voice.py  [impl; usa el STT inyectado — el STT real (Whisper API) sigue siendo stub]
def save_audio_upload(data: bytes, out_dir: Path, suffix: str = ".wav") -> Path: ...
def transcribe_question(audio_path: Path, stt: STTProvider, language: str = "es") -> str: ...
def voice_to_insight(audio_path: Path, stt: STTProvider, language: str = "es") -> DocumentInsight: ...
```

### Carril B · `agents/`

```python
# __init__.py  [impl]
PROMPTS_DIR: Path
def load_prompt(name: str) -> str: ...  # contenido de agents/prompts/<name>.md (sin comentarios HTML)

# analyst.py  [impl]
MAX_KEY_POINTS = 6
def build_user_message(context: MarketContext, max_chars: int = 40_000) -> str: ...
def allowed_sources(context: MarketContext) -> dict[str, str]: ...   # id/URL/nombre -> referencia canónica
def allowed_tickers(context: MarketContext) -> set[str]: ...
def postprocess_analysis(analysis: Analysis, context: MarketContext,
                         max_points: int = MAX_KEY_POINTS) -> Analysis: ...
    # no confía en el LLM: fija date y disclaimer, quita tickers y fuentes que no estén en el
    # contexto, elimina frases con recomendación (guardrails) y puntos vacíos; como mucho max_points
def grounding_reference(context: MarketContext) -> str: ...          # (v0.3) contexto completo + texto de documentos
def analysis_text(analysis: Analysis) -> str: ...                    # (v0.3) todo el texto libre del Analysis
def strip_untraceable(analysis: Analysis, figures: list[str]) -> Analysis: ...  # (v0.3) quita frases con esas cifras
def analyze(context: MarketContext, llm: LLMProvider, max_chars: int = 40_000, *,
            check_figures: bool = True,                              # (v0.3)
            trace: list[str] | None = None) -> Analysis: ...         # (v0.3)
    # puerta de grounding: cifras no trazables -> UNA corrección pedida al LLM con la lista; si
    # persisten, strip_untraceable. Notas en `trace` (el pipeline las guarda en StepMetric.detail).
    # El pipeline pasa check_figures=False con MockLLM.

# scriptwriter.py  [impl]
WORDS_PER_MINUTE = 150
LENGTH_TOLERANCE = 0.4        # desviación relativa de duración que dispara una reescritura
MAX_SAME_SPEAKER_RUN = 2      # (v0.3) intervenciones seguidas del mismo locutor toleradas
FALLBACK_NOTE: str            # (v0.3) nota en `trace` cuando se usa fallback_script
CLOSING_LINE_ES: str          # cierre hablado con disclaimer y aviso de voz sintética
def estimate_duration_s(lines: list[ScriptLine], wpm: int = WORDS_PER_MINUTE) -> float: ...
def build_user_message(analysis: Analysis) -> str: ...
def same_speaker_runs(lines: list[ScriptLine],
                      min_len: int = MAX_SAME_SPEAKER_RUN + 1) -> list[tuple[int, int]]: ...  # (v0.3)
    # tramos (inicio, longitud) con min_len o más intervenciones seguidas del mismo locutor
def merge_long_runs(lines: list[ScriptLine],
                    max_run: int = MAX_SAME_SPEAKER_RUN) -> list[ScriptLine]: ...  # (v0.3) reparación determinista
def fix_homoglyphs(text: str) -> str: ...     # (v0.3) cirílico con aspecto latino -> latino ("suба" -> "suba")
def script_problems(script: PodcastScript, target_minutes: float,
                    length_tolerance: float | None = LENGTH_TOLERANCE) -> list[str]: ...
def fallback_script(analysis: Analysis,
                    speaker_names: tuple[str, str] = ("Álvaro", "Elvira")) -> PodcastScript: ...
def write_script(analysis: Analysis, llm: LLMProvider, target_minutes: float = 4.0,
                 speaker_names: tuple[str, str] = ("Álvaro", "Elvira"), *,
                 max_retries: int = 1,
                 length_tolerance: float | None = LENGTH_TOLERANCE,
                 trace: list[str] | None = None) -> PodcastScript: ...   # trace (v0.3)
    # reescribe hasta max_retries veces si el guion tiene problemas (formato, alternancia,
    # cierre, duración) y se queda con el mejor; reparación determinista (homoglifos, recomendaciones,
    # tramos largos del mismo locutor); sin guion válido -> fallback_script + FALLBACK_NOTE en trace

# qa.py  [impl]
MAX_HISTORY_TURNS = 8
NO_BRIEFING_NOTE: str
def build_qa_context(briefing: Briefing | None, max_chars: int = 20_000) -> str: ...
def answer(question: str, briefing: Briefing | None, llm: LLMProvider,
           history: list[dict] | None = None) -> QAAnswer: ...
    # citas [id] -> sources (solo las que existen); guardarraíles MiFID; pregunta vacía -> ValueError

# guardrails.py  [impl] — compliance MiFID II y grounding, compartido por los agentes
ADVICE_REMINDER_ES: str
def contains_advice(text: str) -> bool: ...              # frase con recomendación (ignora negaciones)
def strip_advice(text: str) -> tuple[str, bool]: ...     # (texto sin esas frases, hubo_cambios)
def asks_for_advice(question: str) -> bool: ...          # la pregunta del usuario pide consejo personal
def extract_figures(text: str) -> list[str]: ...         # (v0.3) cifras relevantes (sin años, enteros < 10
                                                         #   salvo %, «IBEX 35», «S&P 500», Q3, fechas)
def untraceable_figures(text: str, reference: str) -> list[str]: ...  # (v0.3) cifras de text que no están
    # en reference (redondeo a los decimales escritos, formato es/en, signo ignorado; derivadas no cuentan)
def strip_figures(text: str, figures: list[str]) -> tuple[str, bool]: ...  # (v0.3) quita frases con esas cifras
```

Prompts de producción en `agents/prompts/{analyst,scriptwriter,qa}.md`, cargados en tiempo de ejecución con
`load_prompt` (editables sin tocar código). Los guardarraíles no sustituyen al prompt: son la segunda barrera
(determinista y verificable en tests).

### Carril C · `media/` y `delivery/`

```python
# charts.py  [impl]
def make_price_chart(snapshot: PriceSnapshot, out_dir: Path) -> ChartAsset: ...      # <TICKER>_price.png
def make_overview_chart(snapshots: list[PriceSnapshot], out_dir: Path) -> ChartAsset: ...  # overview_change.png
def portfolio_weights(portfolio: Portfolio,
                      prices: list[PriceSnapshot] | None = None) -> dict[str, float]: ...
def make_portfolio_chart(portfolio: Portfolio, out_dir: Path,
                         prices: list[PriceSnapshot] | None = None,
                         min_share: float = 0.03) -> ChartAsset: ...                   # portfolio_weights.png
    # posiciones < min_share (o más allá de 8 colores) -> «Otros»; sin pesos valorables -> ValueError
def make_charts(prices: list[PriceSnapshot], out_dir: Path,
                portfolio: Portfolio | None = None, *,
                line_tickers: Collection[str] | None = None) -> list[ChartAsset]: ...  # line_tickers (v0.3)
    # overview (si ≥ 2 valores, índices incluidos) + uno por ticker de line_tickers (si se indica) + cartera;
    # un gráfico fallido no tumba el resto. Pendiente: el overview rotula los índices como si fueran valores

# speech.py  [impl, nuevo en v0.3] — función pura y determinista (sin red)
ABBREVIATIONS: dict[str, str]
def number_to_words(n: int, *, apocope: bool = False) -> str: ...
def decimal_to_words(raw: str, *, apocope: bool = False) -> str: ...
def normalize_for_speech(text: str) -> str: ...
    # texto tal como lo diría un locutor: tickers -> nombre («SAN.MC» -> «Banco Santander»), fechas,
    # periodos («3T 2026», «Q3» -> «tercer trimestre…»), importes («1.200 M€»), porcentajes con signo,
    # decimales y siglas. Solo afecta a lo que se sintetiza: transcripción y SRT conservan el original

# podcast.py  [impl; ffmpeg vía imageio-ffmpeg, o stdlib para WAV]
OUTPUT_SAMPLE_RATE = 24_000
DEFAULT_MAX_WORKERS = 4                         # el pipeline usa PODCAST_TTS_WORKERS = 6
SYNTHETIC_VOICE_NOTICE: str                     # (v0.3)
AI_AUDIO_METADATA: dict[str, str]               # (v0.3) artist/album/genre/comment/copyright: voz sintética IA
def ffmpeg_exe() -> str: ...
def audio_duration_s(path: Path) -> float: ...
def concat_audio(paths: list[Path], out_path: Path, pause_s: float = 0.35, *,
                 metadata: dict[str, str] | None = None) -> Path: ...    # metadata (v0.3): ID3 vía ffmpeg
def synthesize_podcast(script: PodcastScript, tts: TTSProvider, out_dir: Path, voice_a: str,
                       voice_b: str, pause_s: float = 0.35, *,
                       max_workers: int = DEFAULT_MAX_WORKERS, retries: int = 2,
                       keep_parts: bool = False,
                       normalize: bool = True,                            # (v0.3) normalize_for_speech por línea
                       metadata: dict[str, str] | None = None) -> AudioAsset: ...  # (v0.3) por defecto AI_AUDIO_METADATA + título
    # TTS por línea en paralelo (orden conservado), reintentos por línea, out_dir/podcast<ext>;
    # out_dir/parts se borra salvo keep_parts=True; guion sin líneas -> ValueError

# transcript.py  [impl]
def default_speaker_names() -> dict[str, str]: ...
def format_srt_timestamp(seconds: float) -> str: ...
def segments_to_srt(segments: list[AudioSegment], speaker_names: dict[str, str] | None = None) -> str: ...
def build_transcript(script: PodcastScript, segments: list[AudioSegment], out_dir: Path,
                     speaker_names: dict[str, str] | None = None) -> Transcript: ...    # out_dir/podcast.srt

# cover.py  [stub, opcional → D2]
def build_cover_prompt(analysis: Analysis) -> str: ...
def overlay_title(image_path: Path, title: str, date_text: str) -> Path: ...
def make_cover(analysis: Analysis, image_gen: ImageGenProvider | None, out_dir: Path) -> Path | None: ...

# video.py  [stub, opcional → D2]
def make_video(audio: AudioAsset, images: list[Path], out_path: Path,
               transcript: Transcript | None = None, size: tuple[int, int] = (1080, 1920),
               fps: int = 24) -> VideoAsset: ...

# email_sender.py
SYNTHETIC_VOICE_NOTE: str
def build_email_html(briefing: Briefing, chart_cids: list[str] | None = None) -> str: ...   # [impl] pura
    # chart_cids: Content-ID de los PNG adjuntos (por defecto chart0, chart1… uno por briefing.charts)
def send_briefing_email(briefing: Briefing, to: list[str] | None = None,
                        settings: Settings | None = None) -> DeliveryResult: ...             # [stub] SMTP → D2

# telegram_sender.py
API_URL = "https://api.telegram.org/bot{token}/{method}"
def build_caption(briefing: Briefing, max_len: int = 1024) -> str: ...                      # [impl] pura
def send_briefing_telegram(briefing: Briefing, chat_id: str | None = None,
                           settings: Settings | None = None) -> DeliveryResult: ...         # [stub] red → D2
```

### Proveedores reales (estado al cierre de la Fase 1)

| Proveedor | Estado | Notas de contrato |
| --- | --- | --- |
| `AnthropicLLM.complete` | **[impl]** | Texto libre o **salida estructurada** con `output_config.format = {"type": "json_schema", "schema": …}` (esquema de `anthropic.transform_schema`) + validación Pydantic + 1 reintento autocorrectivo ([ADR-004](decisiones/ADR-004-salida-estructurada-json-schema.md)). Sonnet 5.5 con `effort="medium"`; Haiku 4.5 (`cheap=True`) sin `effort`. `last_usage` suma el reintento. Raises `anthropic.APIError`, `LLMResponseError` (rechazo, cortada, vacía), `StructuredOutputError` |
| `ClaudeVision.describe` (+ `detect_media_type`, `prepare_image`) | **[impl]** | Imagen en base64; `prepare_image` reescala si > 5 MB o > 2.000 px; `effort="low"` |
| `GeminiLLM.complete` | **[impl]** (alternativo) | `response_mime_type="application/json"` + `response_json_schema`; misma validación con 1 reintento. Probado con `smoke_real.py` (estructurado); briefing completo con Gemini: no medido |
| `EdgeTTS.synthesize` | **[impl]** | `edge-tts==7.2.8` (`TESTED_EDGE_TTS_VERSION`). Constructor `EdgeTTS(settings=None, *, rate=None, pitch=None, retries=2, backoff_s=1.0, connect_timeout=10, receive_timeout=60)` (`rate`/`pitch` por defecto de `BRIEFER_TTS_RATE`/`BRIEFER_TTS_PITCH`); `synthesize(text, voice, out_path, *, rate=None, pitch=None)` admite ajustar una llamada. Reintentos propios solo ante errores transitorios; escritura atómica (`.part` → MP3). Raises `ValueError` (texto/voz vacíos, `rate`/`pitch` mal formados), `RuntimeError` (sin audio tras reintentos) |
| `OpenAILLM.complete` | **[stub] documentado** | Recorte (docs/07, H10): lanza `NotImplementedError`; en el pipeline, el paso núcleo cae a mock marcado |
| `WhisperAPI.transcribe` | **[stub]** | Pendiente (D2). Sin él, el Q&A por voz y las notas de voz solo funcionan en mock |
| `QwenVLLocal`, `WhisperLocal`, `ElevenLabsTTS`, `SDXLTurbo`, `CLIPClassifier` | **[stub]** | *Won't* o D2; se retiran del registry antes de entregar si no se implementan |

**`providers/llm/_structured.py` (v0.3, interno de los LLM reales):**

```python
class StructuredOutputError(ValueError): ...
def dict_fields(response_model: type[BaseModel]) -> list[str]: ...        # campos dict[str, str] de primer nivel
def encode_dict_fields(schema: dict, fields: list[str]) -> dict: ...      # dict -> lista de pares {label, value}
def decode_dict_fields(data: object, fields: list[str]) -> object: ...    # pares -> dict (acepta también dicts)
def parse_json_model(text: str, response_model: type[BaseModel],
                     pair_fields: list[str] | None = None) -> BaseModel: ...   # admite vallas ```json
def complete_structured(call: CallFn, messages: list[dict], response_model: type[BaseModel],
                        usage_out: dict[str, int] | None = None, *, max_fix_attempts: int = 1,
                        pair_fields: list[str] | None = None) -> BaseModel: ...
```

**Por qué `pair_fields`:** el esquema estricto que exige `output_config.format` pone
`additionalProperties: false` en todos los objetos, así que un `dict[str, str]` libre
(`DocumentInsight.key_figures`) quedaría como `{}` y el modelo solo podría devolverlo vacío. `AnthropicLLM` pide
esos campos como lista de pares `{"label", "value"}` y `decode_dict_fields` los reconvierte antes de validar: el
contrato (`key_figures: dict[str, str]`) **no cambia**.

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
| **A** · Entradas, visión y Telegram | `ingest/*`, `providers/vision/*`, `providers/stt/*`, `providers/image/clip_classifier.py`, `delivery/telegram_sender.py` (desde v0.2) | Tickers, ficheros subidos (PDF, imagen, audio), CSV de cartera | `NewsItem[]`, `PriceSnapshot[]`, `DocumentInsight[]`, `Portfolio`, texto de la pregunta | `data/samples/*`, `MockVision`, `MockSTT` |
| **B** · Agentes, orquestación y calidad | `agents/*` (incl. `guardrails.py`), `agents/prompts/*`, `pipeline.py`, `costs.py`, `providers/llm/*`, `scripts/demo.py`; dueño del merge de `schemas.py` | `MarketContext` (de A), `Briefing` para el Q&A | `Analysis`, `PodcastScript`, `QAAnswer`, `Briefing` completo con `metrics` y `deliveries` | `MarketContext` construido desde `data/samples/`, `MockLLM`, funciones de A y C en versión mock |
| **C** · Media, UI y demo | `media/*`, `delivery/email_sender.py`, `providers/tts/*`, `providers/image/*` (texto→imagen), `app/*`, `data/samples/demo_briefing/` | `PodcastScript`, `Analysis`, `PriceSnapshot[]`, `Briefing` | `AudioAsset`, `Transcript`, `ChartAsset[]`, `VideoAsset`, `cover.png`, `DeliveryResult`, UI | `PodcastScript` y `Briefing` de ejemplo generados por `MockLLM`, `MockTTS` |
| Transversal | `schemas.py`, `providers/base.py`, `providers/registry.py`, `providers/mock.py`, `config.py`, `logging_utils.py`, `storage.py`, `tests/`, docs, Docker | — | Contratos, configuración, métricas, persistencia y modo mock | — |

### Puntos de integración (por orden)

1. **Modo mock** *(hecho en la Fase 0, verificado en integración)*: `load_sample_news` +
   `synthetic_snapshots` + `filter_by_tickers` (A) → `analyze` + `write_script` con `MockLLM` (B) →
   `synthesize_podcast` + `build_transcript` + `make_charts` (C) → `save_briefing`. Criterio: sin `skip` en
   `tests/test_pipeline_mock.py` y en verde.
2. **A → B real** *(hecho en la Fase 1)*: `MarketContext` construido con `fetch_news` + `get_price_snapshots`
   + insights de `process_upload` (PDF y gráfico con `ClaudeVision`) → `analyze()` con `AnthropicLLM`.
3. **B → C real** *(hecho en la Fase 1)*: `write_script()` (Haiku) → `synthesize_podcast()` con `EdgeTTS`.
4. **C → B** *(hecho)*: la UI llama a `pipeline.run_briefing()` / `pipeline.answer_question()` (con `mode` y
   `use_cache`) y a `storage` para el histórico y la portada (`load_featured_briefing`); no instancia
   proveedores.
5. **Fin a fin** *(hecho)*: `python scripts/demo.py --mock`, `--demo-voices` y `python scripts/demo.py` (con
   claves) producen un `briefing.json` válido en `data/outputs/<id>/`; el briefing real
   `20261005-110721-a127a9` se exportó con `storage.export_briefing` a `data/samples/demo_briefing/`.
6. **Pendiente (D2):** `qa.stt` real (`WhisperAPI.transcribe`), vídeo, portada, envíos.

---

## Registro de cambios de contrato

| Versión | Fecha | Cambio | Acordado por |
| --- | --- | --- | --- |
| v0.1 | 05-oct-2026 | Versión inicial, alineada con el código del esqueleto. Incluye `Briefing.deliveries` (añadido respecto a la spec inicial), `DISCLAIMER_ES`, `new_briefing_id`, `provider_name`/`model`/`last_usage` en proveedores y `registry` con `cheap`/`force_mock` | Equipo |
| v0.2 | 05-oct-2026 (noche) | **Aditivo.** Schemas: `StepMetric.error: str \| None = None` (sustituye la marca `"[ERROR …]"` dentro de `model`); `QAAnswer.metrics: list[StepMetric] = []`. Pipeline: `PipelineStepError`, `StepNotImplementedError`, `DELIVERY_CHANNELS`, `ValueError` por canal desconocido o sin tickers; clasificación núcleo/opcional; progreso `"(n/N) …"`; `storage.save` incluido en `Briefing.metrics` (bug de v0.1 corregido); tickers normalizados con `normalize_ticker`; coste de PDF/gráfico suma LLM + visión. Storage: rutas relativas portables en `briefing.json`. Parámetros opcionales nuevos: `synthetic_snapshots(..., end=None)`, `filter_by_tickers(..., min_items=3)`, `analyze(..., max_chars=40_000)`, `write_script(..., *, max_retries=1, length_tolerance=LENGTH_TOLERANCE)`, `synthesize_podcast(..., *, max_workers=4, retries=2, keep_parts=False)`, `make_portfolio_chart(..., prices=None, min_share=0.03)`, `build_email_html(..., chart_cids=None)`. Funciones/constantes nuevas: `prices.currency_for`, `chart_reader.validate_image` (+ `NOT_CHART_LABEL`, `NOT_CHART_THRESHOLD`, `SUPPORTED_FORMATS`), `tickers.MARKET_INDEX_TICKERS`, `pdf_reader.MAX_VISION_PAGES` / `MAX_LLM_CHARS` / `MAX_IMAGES_PER_PAGE`, `analyst.postprocess_analysis` / `allowed_sources` / `allowed_tickers`, `scriptwriter.script_problems` / `fallback_script` / `CLOSING_LINE_ES` / `LENGTH_TOLERANCE`, `charts.portfolio_weights`, `podcast.ffmpeg_exe`, módulo `agents/guardrails.py`. Ver [ADR-003](decisiones/ADR-003-tolerancia-fallos-y-contratos-v02.md) | Equipo (integración Fase 0) |
| v0.3 | 05-oct-2026 (cierre de la Fase 1) | **Aditivo.** Schemas: `StepMetric.detail: str \| None = None`; `CONTRACTS_VERSION = "0.3"`. **Semántica nueva de `StepMetric.error`:** prefijo `"Fallback a "` cuando un paso núcleo se completó con sustituto (`provider`/`model` = sustituto; latencia y coste suman ambos intentos); `logging_utils.FALLBACK_PREFIX`, `fallback_error`, `step_fell_back`, `StepHandle.detail`. Pipeline: caída a sustituto de los pasos núcleo (`ingest.news` → `data/samples`, `ingest.prices` → sintéticos, `agents.analyst` / `agents.qa` → `MockLLM`, `agents.scriptwriter` → `fallback_script` / `MockLLM`, `media.podcast` → `MockTTS`); `run_briefing(..., *, mode=None, use_cache=True)`, `answer_question(..., *, mode=None)`, `RunMode`, `RUN_MODES`, `resolve_mode`, `demo_voice_tts`, `PODCAST_TTS_WORKERS`, `UPLOAD_WORKERS`; subidas en paralelo con la ingesta; índices de contexto `settings.context_tickers` (`BRIEFER_CONTEXT_TICKERS`, fuera de `MarketContext.tickers`). Ingesta: módulo `ingest/cache.py`; `news.fetch_google_news`, `google_news_query`, `google_news_url`, `parse_feed`, `parse_yfinance_item`, `clean_html`, `news_id`, `last_fetch_stats`, `DEFAULT_MARKET_FEEDS`, `NewsFetchError`; `fetch_news(..., *, max_per_ticker=None, use_cache=True)`; `prices.PriceFetchError`, `snapshot_from_closes`, `get_price_snapshot(s)(..., *, use_cache=True)`. Agentes: `guardrails.extract_figures` / `untraceable_figures` / `strip_figures`; `analyst.grounding_reference` / `analysis_text` / `strip_untraceable`, `analyze(..., *, check_figures=True, trace=None)`; `scriptwriter.same_speaker_runs` / `merge_long_runs` / `fix_homoglyphs`, `MAX_SAME_SPEAKER_RUN`, `FALLBACK_NOTE`, `write_script(..., *, trace=None)`; `qa.NO_BRIEFING_NOTE`. Media: módulo `media/speech.py` (`normalize_for_speech`); `podcast.AI_AUDIO_METADATA`, `SYNTHETIC_VOICE_NOTICE`, `concat_audio(..., *, metadata=None)`, `synthesize_podcast(..., *, normalize=True, metadata=None)`; `make_charts(..., *, line_tickers=None)`. Storage: `DEMO_BRIEFING_DIRNAME`, `demo_briefing_dir`, `load_demo_briefing`, `latest_briefing`, `load_featured_briefing`, `export_briefing`. Proveedores: `AnthropicLLM`, `ClaudeVision`, `GeminiLLM`, `EdgeTTS` implementados (`EdgeTTS(settings, *, rate, pitch, retries, backoff_s, connect_timeout, receive_timeout)`, `synthesize(..., *, rate=None, pitch=None)`); `providers/llm/_structured.py` con `pair_fields`; `OpenAILLM` queda como *stub* documentado. **Corrección de texto:** los reintentos ante errores transitorios los hace cada proveedor; el pipeline decide el fallback. Ver [ADR-004](decisiones/ADR-004-salida-estructurada-json-schema.md) | Equipo (integración Fase 1) |
