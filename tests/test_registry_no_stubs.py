"""Limpieza de *stubs* (D3, v0.3.9): el registry solo expone proveedores implementados.

Sin red ni claves: se comprueba el código fuente de cada clase registrada (ningún método lanza
``NotImplementedError``), que los nombres retirados ya no están ni en el registry ni en los
``Literal`` de ``config`` y que un ``.env`` antiguo con un proveedor retirado cae a ``mock`` con aviso.
"""

from __future__ import annotations

import ast
import importlib.util
import typing
from pathlib import Path

import pytest
from pydantic import ValidationError

from briefer import config
from briefer.config import RETIRED_PROVIDERS, Settings
from briefer.providers import mock, registry

_TABLES = {
    "llm": (registry.LLM_IMPLS, config.LLMProviderName),
    "vision": (registry.VISION_IMPLS, config.VisionProviderName),
    "stt": (registry.STT_IMPLS, config.STTProviderName),
    "tts": (registry.TTS_IMPLS, config.TTSProviderName),
    "image_gen": (registry.IMAGE_GEN_IMPLS, config.ImageGenProviderName),
    "image_classifier": (registry.IMAGE_CLASSIFIER_IMPLS, config.ImageClassifierName),
}
_ALL_RETIRED = {name for names in RETIRED_PROVIDERS.values() for name in names}


def _class_raises_not_implemented(module_path: str, class_name: str) -> list[str]:
    """Métodos de ``class_name`` (en el fuente de ``module_path``) que lanzan NotImplementedError."""
    spec = importlib.util.find_spec(module_path)
    assert spec is not None and spec.origin, f"{module_path} no existe"
    tree = ast.parse(Path(spec.origin).read_text(encoding="utf-8"))
    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for func in ast.walk(node):
                if not isinstance(func, ast.FunctionDef | ast.AsyncFunctionDef):
                    continue
                for raise_node in ast.walk(func):
                    exc = getattr(raise_node, "exc", None) if isinstance(raise_node, ast.Raise) else None
                    target = exc.func if isinstance(exc, ast.Call) else exc
                    if isinstance(target, ast.Name) and target.id == "NotImplementedError":
                        offenders.append(f"{class_name}.{func.name}")
            return offenders
    raise AssertionError(f"{class_name} no está en {module_path}")


@pytest.mark.parametrize("kind", sorted(_TABLES))
def test_registered_providers_are_implemented(kind: str) -> None:
    table, _ = _TABLES[kind]
    for name, (module_path, class_name, _secret) in table.items():
        assert not _class_raises_not_implemented(module_path, class_name), (kind, name)


@pytest.mark.parametrize("kind", sorted(_TABLES))
def test_config_literals_match_registry(kind: str) -> None:
    table, literal = _TABLES[kind]
    allowed = set(typing.get_args(literal)) - {"mock", "none"}
    assert allowed == set(table), kind
    assert not (allowed & _ALL_RETIRED)


@pytest.mark.parametrize(
    "module_path",
    [
        "briefer.providers.llm.openai_llm",
        "briefer.providers.vision.qwen_vl_local",
        "briefer.providers.stt.whisper_local",
        "briefer.providers.tts.elevenlabs_tts",
    ],
)
def test_stub_modules_are_gone(module_path: str) -> None:
    assert importlib.util.find_spec(module_path) is None


@pytest.mark.parametrize(
    ("field", "value"),
    [(field, name) for field, names in RETIRED_PROVIDERS.items() for name in sorted(names)],
)
def test_retired_provider_in_env_falls_back_to_mock(
    field: str, value: str, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level("WARNING", logger="briefer.config"):
        settings = Settings(_env_file=None, **{field: value.upper()})
    assert getattr(settings, field) == "mock"
    assert any("retirado" in r.getMessage() for r in caplog.records)


def test_unknown_provider_still_fails_validation() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, briefer_tts_provider="bark")


def test_mock_providers_from_registry_work() -> None:
    """Con ``force_mock`` cada familia devuelve un proveedor que responde sin red."""
    s = Settings(_env_file=None)
    assert registry.get_llm(s, force_mock=True).complete("s", [{"role": "user", "content": "x"}])
    assert isinstance(registry.get_vision(s, force_mock=True), mock.MockVision)
    assert isinstance(registry.get_stt(s, force_mock=True), mock.MockSTT)
    assert isinstance(registry.get_tts(s, force_mock=True), mock.MockTTS)
    assert isinstance(registry.get_image_gen(s, force_mock=True), mock.MockImageGen)
    assert isinstance(registry.get_image_classifier(s, force_mock=True), mock.MockImageClassifier)
