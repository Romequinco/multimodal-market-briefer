"""Tests sin red de los proveedores LLM/visión reales (carril B) con el SDK sustituido.

Se simula el cliente de ``anthropic`` y de ``google-genai`` con respuestas realistas
(bloques ``thinking`` + ``text`` con JSON de salida estructurada, ``usage``, ``stop_reason``).
"""

from __future__ import annotations

import io
import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from briefer import costs
from briefer.config import ROOT_DIR, Settings
from briefer.providers.llm import _anthropic_common as common
from briefer.providers.llm._structured import StructuredOutputError, parse_json_model
from briefer.schemas import Analysis, KeyPoint, PodcastScript

SAMPLES_DIR = ROOT_DIR / "data" / "samples"


# ── Dobles del SDK de Anthropic ─────────────────────────────────────────────────────


def _resp(text: str, *, stop: str = "end_turn", inp: int = 1000, out: int = 300, thinking: bool = True):
    content = []
    if thinking:
        content.append(SimpleNamespace(type="thinking", thinking="", signature="sig"))
    content.append(SimpleNamespace(type="text", text=text))
    return SimpleNamespace(
        id="msg_test",
        content=content,
        stop_reason=stop,
        stop_details=None,
        usage=SimpleNamespace(
            input_tokens=inp, output_tokens=out, cache_read_input_tokens=0, cache_creation_input_tokens=0
        ),
    )


class FakeMessages:
    def __init__(self, responses: list) -> None:
        self.responses = list(responses)
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        resp = self.responses[min(len(self.calls) - 1, len(self.responses) - 1)]
        if isinstance(resp, Exception):
            raise resp
        return resp


class FakeAnthropicClient:
    def __init__(self, responses: list) -> None:
        self.messages = FakeMessages(responses)


@pytest.fixture
def anthropic_settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        briefer_llm_provider="anthropic",
        briefer_vision_provider="claude",
        anthropic_api_key="sk-test-no-real",
        briefer_output_dir=tmp_path / "outputs",
    )


def _analysis_json(**overrides) -> str:
    data = {
        "date": "2026-10-05",
        "headline": "El Santander sube un 1,2 %",
        "key_points": [
            {
                "title": "Banca al alza",
                "explanation": "El banco sube un 1,2 % tras sus resultados.",
                "tickers": ["SAN.MC"],
                "sentiment": "positivo",
                "sources": ["ejemplo-001"],
            }
        ],
        "market_mood": "Tono positivo.",
    }
    data.update(overrides)
    return json.dumps(data, ensure_ascii=False)


def _llm(settings: Settings, responses: list, cheap: bool = False):
    from briefer.providers.llm.anthropic_llm import AnthropicLLM

    llm = AnthropicLLM(settings, cheap=cheap)
    llm._client = FakeAnthropicClient(responses)
    return llm


# ── AnthropicLLM ────────────────────────────────────────────────────────────────────


def test_anthropic_structured_output_uses_json_schema_and_effort(anthropic_settings: Settings) -> None:
    llm = _llm(anthropic_settings, [_resp(_analysis_json())])
    result = llm.complete("sistema", [{"role": "user", "content": "contexto"}], response_model=Analysis)
    assert isinstance(result, Analysis) and result.key_points[0].tickers == ["SAN.MC"]
    call = llm._client.messages.calls[0]
    assert call["model"] == "claude-sonnet-5-5" and call["system"] == "sistema"
    fmt = call["output_config"]["format"]
    assert fmt["type"] == "json_schema" and fmt["schema"]["additionalProperties"] is False
    assert call["output_config"]["effort"] == "medium"
    assert "tool_choice" not in call and "thinking" not in call
    assert llm.last_usage == {"input_tokens": 1000, "output_tokens": 300}


def test_anthropic_cheap_uses_haiku_without_effort(anthropic_settings: Settings) -> None:
    script = {"title": "Ep", "lines": [{"speaker": "A", "text": "Hola"}, {"speaker": "B", "text": "Buenas"}]}
    llm = _llm(anthropic_settings, [_resp(json.dumps(script), thinking=False)], cheap=True)
    result = llm.complete("s", [{"role": "user", "content": "x"}], response_model=PodcastScript)
    assert isinstance(result, PodcastScript) and len(result.lines) == 2
    call = llm._client.messages.calls[0]
    assert call["model"] == "claude-haiku-4-5-20251001"
    assert "effort" not in call["output_config"]  # Haiku 4.5 no admite effort


def test_anthropic_retries_once_with_validation_error(anthropic_settings: Settings) -> None:
    bad = _analysis_json(key_points=[{"title": "x", "explanation": "y", "sentiment": "eufórico"}])
    llm = _llm(anthropic_settings, [_resp(bad, inp=100, out=50), _resp(_analysis_json(), inp=200, out=80)])
    result = llm.complete("s", [{"role": "user", "content": "x"}], response_model=Analysis)
    assert isinstance(result, Analysis)
    calls = llm._client.messages.calls
    assert len(calls) == 2
    retry_msgs = calls[1]["messages"]
    assert [m["role"] for m in retry_msgs] == ["user", "assistant", "user"]
    assert retry_msgs[1]["content"] == bad and "sentiment" in retry_msgs[2]["content"]
    assert llm.last_usage == {"input_tokens": 300, "output_tokens": 130}  # suma de ambos intentos


def test_anthropic_gives_up_after_one_retry(anthropic_settings: Settings) -> None:
    llm = _llm(anthropic_settings, [_resp("no es json"), _resp("{\"tampoco\": 1}")])
    with pytest.raises(StructuredOutputError):
        llm.complete("s", [{"role": "user", "content": "x"}], response_model=Analysis)
    assert len(llm._client.messages.calls) == 2
    assert llm.last_usage["input_tokens"] == 2000  # el gasto de los dos intentos cuenta


def test_anthropic_free_text_and_message_format(anthropic_settings: Settings) -> None:
    llm = _llm(anthropic_settings, [_resp("Respuesta en texto")])
    history = [
        {"role": "user", "content": "hola"},
        {"role": "assistant", "content": "¿qué tal?"},
        {"role": "user", "content": "pregunta"},
    ]
    assert llm.complete("s", history) == "Respuesta en texto"
    call = llm._client.messages.calls[0]
    assert call["messages"] == history and "format" not in call.get("output_config", {})


@pytest.mark.parametrize(
    ("stop", "text", "match"),
    [("max_tokens", "{\"a\":", "max_tokens"), ("refusal", "", "refusal"), ("end_turn", "", "sin texto")],
)
def test_anthropic_unusable_responses_raise(anthropic_settings: Settings, stop: str, text: str, match: str) -> None:
    llm = _llm(anthropic_settings, [_resp(text, stop=stop)])
    with pytest.raises(common.LLMResponseError, match=match):
        llm.complete("s", [{"role": "user", "content": "x"}])


def test_anthropic_client_has_timeouts_and_retries(
    anthropic_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    import anthropic

    captured: dict = {}

    class FakeAnthropic:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(anthropic, "Anthropic", FakeAnthropic)
    common.make_client(anthropic_settings)
    assert captured["max_retries"] == common.MAX_RETRIES >= 2
    assert captured["timeout"].read == common.REQUEST_TIMEOUT_S
    assert captured["api_key"] == "sk-test-no-real"


def test_api_errors_propagate_after_sdk_retries(anthropic_settings: Settings) -> None:
    llm = _llm(anthropic_settings, [ConnectionError("red caída")])
    with pytest.raises(ConnectionError):
        llm.complete("s", [{"role": "user", "content": "x"}], response_model=Analysis)


def test_to_api_messages_marks_cache_control() -> None:
    out = common.to_api_messages([
        {"role": "user", "content": "contexto", "cache": True},
        {"role": "assistant", "content": "ok"},
        {"role": "user", "content": "pregunta"},
    ])
    assert out[0] == {"role": "user", "content": [
        {"type": "text", "text": "contexto", "cache_control": {"type": "ephemeral"}}
    ]}
    assert out[2] == {"role": "user", "content": "pregunta"} and "cache" not in out[1]


def test_to_api_messages_validates_history() -> None:
    assert common.to_api_messages([{"role": "system", "content": "x"}, {"role": "user", "content": "y"}]) == [
        {"role": "user", "content": "y"}
    ]
    with pytest.raises(ValueError):
        common.to_api_messages([{"role": "assistant", "content": "x"}])


def test_parse_json_model_accepts_code_fences() -> None:
    model = parse_json_model("```json\n" + _analysis_json() + "\n```", Analysis)
    assert isinstance(model, Analysis) and model.date == date(2026, 10, 5)


def test_registry_builds_anthropic_with_cheap(anthropic_settings: Settings) -> None:
    from briefer.providers import registry

    main = registry.get_llm(anthropic_settings)
    cheap = registry.get_llm(anthropic_settings, cheap=True)
    assert (main.provider_name, main.model) == ("anthropic", "claude-sonnet-5-5")
    assert cheap.model == "claude-haiku-4-5-20251001"


# ── ClaudeVision ────────────────────────────────────────────────────────────────────


def test_detect_media_type() -> None:
    from briefer.providers.vision.claude_vision import detect_media_type

    assert detect_media_type((SAMPLES_DIR / "grafico_ejemplo.png").read_bytes()) == "image/png"
    assert detect_media_type(b"\xff\xd8\xff\xe0rest") == "image/jpeg"
    assert detect_media_type(b"RIFF\x00\x00\x00\x00WEBPVP8 ") == "image/webp"
    assert detect_media_type(b"GIF89a....") == "image/gif"
    with pytest.raises(ValueError):
        detect_media_type(b"%PDF-1.7")
    with pytest.raises(ValueError):
        detect_media_type(b"")


def test_claude_vision_describe(anthropic_settings: Settings) -> None:
    from briefer.providers.vision.claude_vision import ClaudeVision

    vision = ClaudeVision(anthropic_settings)
    vision._client = FakeAnthropicClient([_resp("Gráfico de velas con tendencia bajista.", inp=1600, out=120)])
    png = (SAMPLES_DIR / "grafico_ejemplo.png").read_bytes()
    text = vision.describe(png, "Describe el gráfico")
    assert "velas" in text
    call = vision._client.messages.calls[0]
    image_block, text_block = call["messages"][0]["content"]
    assert image_block["source"]["media_type"] == "image/png" and image_block["source"]["data"]
    assert text_block == {"type": "text", "text": "Describe el gráfico"}
    assert call["output_config"] == {"effort": "low"}
    assert vision.last_usage == {"input_tokens": 1600, "output_tokens": 120}


def test_prepare_image_downscales_big_images() -> None:
    from PIL import Image

    from briefer.providers.vision.claude_vision import MAX_SIDE_PX, prepare_image

    buf = io.BytesIO()
    Image.new("RGB", (MAX_SIDE_PX * 2, 300), "white").save(buf, format="JPEG")
    data, media_type = prepare_image(buf.getvalue())
    with Image.open(io.BytesIO(data)) as img:
        assert max(img.size) <= MAX_SIDE_PX
    assert media_type in {"image/png", "image/jpeg"}
    small = (SAMPLES_DIR / "grafico_ejemplo.png").read_bytes()
    assert prepare_image(small) == (small, "image/png")  # sin cambios si ya cabe


# ── GeminiLLM ───────────────────────────────────────────────────────────────────────


class FakeGeminiModels:
    def __init__(self, texts: list[str]) -> None:
        self.texts = list(texts)
        self.calls: list[dict] = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        text = self.texts[min(len(self.calls) - 1, len(self.texts) - 1)]
        return SimpleNamespace(
            text=text,
            prompt_feedback=None,
            usage_metadata=SimpleNamespace(prompt_token_count=500, candidates_token_count=100, thoughts_token_count=40),
        )


def _gemini(texts: list[str], cheap: bool = False):
    from briefer.providers.llm.gemini_llm import GeminiLLM

    settings = Settings(_env_file=None, briefer_llm_provider="gemini", gemini_api_key="g-test")
    llm = GeminiLLM(settings, cheap=cheap)
    llm._client = SimpleNamespace(models=FakeGeminiModels(texts))
    return llm


def test_gemini_structured_output_and_usage() -> None:
    llm = _gemini([_analysis_json()])
    history = [
        {"role": "user", "content": "a"},
        {"role": "assistant", "content": "b"},
        {"role": "user", "content": "c"},
    ]
    result = llm.complete("sistema", history, response_model=Analysis)
    assert isinstance(result, Analysis)
    call = llm._client.models.calls[0]
    assert call["model"] == "gemini-2.5-flash"
    assert [c["role"] for c in call["contents"]] == ["user", "model", "user"]
    config = call["config"]
    assert config.system_instruction == "sistema"
    assert config.response_mime_type == "application/json"
    assert config.response_json_schema["title"] == "Analysis"
    assert llm.last_usage == {"input_tokens": 500, "output_tokens": 140}  # salida + razonamiento


def test_gemini_retry_and_text_mode() -> None:
    llm = _gemini(["{roto", _analysis_json()])
    assert isinstance(llm.complete("s", [{"role": "user", "content": "x"}], response_model=Analysis), Analysis)
    assert len(llm._client.models.calls) == 2
    assert llm.last_usage["input_tokens"] == 1000

    cheap = _gemini(["Hola"], cheap=True)
    assert cheap.complete("s", [{"role": "user", "content": "x"}]) == "Hola"
    assert cheap._client.models.calls[0]["config"].thinking_config.thinking_budget == 0


def test_gemini_dict_fields_travel_as_pairs() -> None:
    """Como en Anthropic: ``key_figures`` (dict libre) viaja como lista de pares y se reconvierte."""
    import json as _json

    from briefer.schemas import DocumentInsight

    payload = {
        "source_type": "pdf", "source_name": "r.pdf", "extracted_text": "t", "summary": "s",
        "key_figures": [{"label": "Ingresos", "value": "100 M€"}, {"label": "Margen", "value": "12 %"}],
    }
    llm = _gemini([_json.dumps(payload)])
    result = llm.complete("s", [{"role": "user", "content": "x"}], response_model=DocumentInsight)
    assert result.key_figures == {"Ingresos": "100 M€", "Margen": "12 %"}
    schema = llm._client.models.calls[0]["config"].response_json_schema
    assert schema["properties"]["key_figures"]["type"] == "array"


def test_gemini_empty_response_raises() -> None:
    llm = _gemini([""])
    with pytest.raises(common.LLMResponseError):
        llm.complete("s", [{"role": "user", "content": "x"}])


# ── Costes ──────────────────────────────────────────────────────────────────────────


def test_costs_for_real_model_ids() -> None:
    assert costs.llm_price_usd_per_mtok("claude-sonnet-5-5") == (2.0, 10.0)
    assert costs.llm_price_usd_per_mtok("claude-haiku-4-5-20251001") == (1.0, 5.0)  # por prefijo
    assert costs.llm_price_usd_per_mtok("modelo-desconocido") is None
    usage = {"input_tokens": 1_000_000, "output_tokens": 100_000}
    assert costs.estimate_cost_eur("anthropic", "claude-sonnet-5-5", **usage) == pytest.approx(3.0 * costs.USD_TO_EUR)
    assert costs.estimate_cost_eur("mock", "mock-llm", **usage) == 0.0
    assert costs.estimate_cost_eur("samples", "-", n_chars=10) == 0.0
    # el guionista en Haiku cuesta la mitad que en Sonnet con el mismo uso
    haiku = costs.estimate_cost_eur("anthropic", "claude-haiku-4-5-20251001", **usage)
    sonnet = costs.estimate_cost_eur("anthropic", "claude-sonnet-5-5", **usage)
    assert haiku == pytest.approx(sonnet / 2)


def test_keypoint_schema_is_api_compatible() -> None:
    import anthropic

    schema = anthropic.transform_schema(Analysis)
    kp = schema["$defs"]["KeyPoint"]
    assert kp["additionalProperties"] is False and set(KeyPoint.model_fields) == set(kp["properties"])
