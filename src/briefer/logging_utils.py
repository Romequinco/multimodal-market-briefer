"""Logging del proyecto y medición de pasos del pipeline (latencia + coste -> StepMetric).

Transversal. Uso típico en ``pipeline.py``::

    metrics: list[StepMetric] = []
    with track_step("agents.analyst", llm.provider_name, llm.model, metrics) as step:
        analysis = analyst.analyze(context, llm)
        step.est_cost_eur = costs.estimate_cost_eur(llm.provider_name, llm.model, **llm.last_usage)
    # al salir del bloque se añade un StepMetric a ``metrics`` (también si hay excepción)
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

from briefer.schemas import StepMetric

_LOGGER_NAME = "briefer"
_configured = False

#: Longitud máxima del mensaje de error que se guarda en ``StepMetric.error``.
_ERROR_DETAIL_CHARS = 160


# ── Redacción de secretos ──────────────────────────────────────────────────────────
#
# Ningún texto de error que acabe en ``StepMetric.error`` (y de ahí en ``briefing.json``, la tabla
# «Cómo se hizo», ``DeliveryResult.detail`` o la UI) ni en el log puede llevar una clave. Las
# excepciones de ``requests``/``httpx`` incluyen la URL (Telegram: ``/bot<TOKEN>/sendMessage``;
# Gemini/Google: ``?key=...``) y algunos SDK repiten la cabecera en el mensaje.

#: Patrones de credenciales conocidos -> sustituto. Se aplican después de los valores exactos.
_SECRET_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"sk-[A-Za-z0-9_\-]{8,}"), "sk-***"),                     # OpenAI / Anthropic
    (re.compile(r"AIza[0-9A-Za-z_\-]{10,}"), "AIza***"),                  # Google API key
    (re.compile(r"\bAQ\.[0-9A-Za-z_\-.]{10,}"), "AQ.***"),                # Google (formato nuevo)
    (re.compile(r"bot\d{5,}:[A-Za-z0-9_\-]{10,}"), "bot***"),             # token de bot de Telegram
    (re.compile(r"\b\d{6,}:[A-Za-z0-9_\-]{30,}"), "***"),                 # token de Telegram suelto
    (re.compile(r"(?i)\b(api[_-]?key|key|token|access_token|password|passwd|secret)=([^&\s'\"]+)"),
     r"\1=***"),                                                          # parámetros de URL
    (re.compile(r"(?i)(authorization|x-api-key|x-goog-api-key)(['\"]?\s*[:=]\s*['\"]?)(bearer\s+)?[^\s'\",}]+"),
     r"\1\2\3***"),                                                       # cabeceras repetidas
)
#: Longitud mínima de un valor de ``Settings`` para redactarlo literalmente (evita tapar «587»).
_MIN_SECRET_LEN = 6


def _settings_secrets() -> list[str]:
    """Valores no vacíos de los ``SecretStr`` de la configuración (claves, tokens, contraseñas)."""
    try:
        from briefer.config import get_settings

        s = get_settings()
    except Exception:  # config inválida: quedan los patrones genéricos
        return []
    values: list[str] = []
    for name in type(s).model_fields:
        getter = getattr(getattr(s, name, None), "get_secret_value", None)
        if getter is None:
            continue
        try:
            value = str(getter() or "")
        except Exception:
            continue
        if len(value) >= _MIN_SECRET_LEN:
            values.append(value)
    if s.smtp_user and len(s.smtp_user) >= _MIN_SECRET_LEN:  # smtplib puede citar el usuario
        values.append(s.smtp_user)
    return sorted(set(values), key=len, reverse=True)


def redact_secrets(text: object, extra: list[str] | None = None) -> str:
    """Devuelve ``text`` sin credenciales: valores exactos de ``Settings`` (y ``extra``) -> ``***``
    y patrones conocidos (``sk-…``, ``AIza…``, ``bot<id>:<token>``, ``key=…``, cabeceras).

    Nunca lanza. Se usa en ``track_step``, ``fallback_error``, ``PipelineStepError``, el log y la UI.
    """
    try:
        out = str(text)
    except Exception:
        return "<error no representable>"
    for value in [*(extra or []), *_settings_secrets()]:
        if value and len(value) >= _MIN_SECRET_LEN:
            out = out.replace(value, "***")
    for pattern, repl in _SECRET_PATTERNS:
        out = pattern.sub(repl, out)
    return out


def error_text(exc: BaseException, max_chars: int = 160) -> str:
    """``"Tipo: mensaje"`` de una excepción, redactado, en una línea y recortado a ``max_chars``.

    El recorte se hace **después** de redactar (un secreto partido por el corte no se escaparía).
    """
    detail = " ".join(redact_secrets(exc).split())[:max_chars]
    return f"{type(exc).__name__}: {detail}" if detail else type(exc).__name__


class _RedactingFormatter(logging.Formatter):
    """Formatter del log que redacta secretos del mensaje **y** del traceback (``log.exception``)."""

    def format(self, record: logging.LogRecord) -> str:
        return redact_secrets(super().format(record))


def get_logger(name: str | None = None) -> logging.Logger:
    """Logger del paquete (``briefer`` o ``briefer.<name>``), configurado una sola vez."""
    global _configured
    if not _configured:
        try:
            from briefer.config import get_settings

            level = get_settings().briefer_log_level.upper()
        except Exception:  # config inválida no debe impedir loguear
            level = "INFO"
        root = logging.getLogger(_LOGGER_NAME)
        if not root.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(
                _RedactingFormatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%H:%M:%S")
            )
            root.addHandler(handler)
        root.setLevel(getattr(logging, level, logging.INFO))
        _configured = True
    if not name:
        return logging.getLogger(_LOGGER_NAME)
    if name.startswith(_LOGGER_NAME):
        return logging.getLogger(name)
    return logging.getLogger(f"{_LOGGER_NAME}.{name}")


@dataclass
class StepHandle:
    """Objeto mutable que recibe el bloque ``with`` para ajustar proveedor, modelo y coste."""

    step: str
    provider: str
    model: str
    est_cost_eur: float = 0.0
    metric: StepMetric | None = field(default=None)
    error: str | None = None
    #: Notas de calidad que acaban en ``StepMetric.detail`` (reintentos, cifras eliminadas…).
    detail: str | None = None


@contextmanager
def track_step(
    step: str,
    provider: str = "-",
    model: str = "-",
    metrics: list[StepMetric] | None = None,
) -> Iterator[StepHandle]:
    """Mide la latencia de un paso y crea un ``StepMetric``.

    - Si se pasa ``metrics``, el ``StepMetric`` se añade a esa lista.
    - El ``StepMetric`` queda también en ``handle.metric`` tras salir del bloque.
    - Las excepciones se registran en log y se propagan (no se tragan). Si el paso falla,
      ``handle.error`` recibe ``"Tipo: mensaje"`` y el ``StepMetric`` lo lleva en su campo
      ``error`` (contrato v0.2; ver ``step_failed``/``step_error``).
    """
    log = get_logger("pipeline")
    handle = StepHandle(step=step, provider=provider, model=model)
    start = time.perf_counter()
    failed = False
    try:
        yield handle
    except BaseException as exc:
        failed = True
        handle.error = error_text(exc, _ERROR_DETAIL_CHARS)  # redactado: nunca claves ni tokens
        raise
    finally:
        latency = time.perf_counter() - start
        handle.metric = StepMetric(
            step=handle.step,
            provider=handle.provider,
            model=handle.model,
            latency_s=round(latency, 4),
            est_cost_eur=round(handle.est_cost_eur, 6),
            error=redact_secrets(handle.error) if handle.error else None,
            detail=redact_secrets(handle.detail) if handle.detail else None,
        )
        if metrics is not None:
            metrics.append(handle.metric)
        log.log(
            logging.WARNING if failed else logging.INFO,
            "%s [%s/%s] %.2fs %.4f€%s",
            step,
            handle.provider,
            handle.model,
            latency,
            handle.est_cost_eur,
            f" (FALLO: {handle.error})" if failed else "",
        )


#: Prefijo de ``StepMetric.error`` cuando el paso se completó con un sustituto del proveedor real.
FALLBACK_PREFIX = "Fallback a "


def fallback_error(substitute: str, exc: BaseException) -> str:
    """Texto de ``StepMetric.error`` para un paso caído a sustituto.

    Ejemplo: ``"Fallback a mock tras RateLimitError: 429 rate_limit_error"``.
    """
    return f"{FALLBACK_PREFIX}{substitute} tras {error_text(exc, _ERROR_DETAIL_CHARS)}"


def step_failed(metric: StepMetric) -> bool:
    """``True`` si el proveedor del paso lanzó una excepción (también si luego hubo fallback)."""
    return bool(metric.error)


def step_fell_back(metric: StepMetric) -> bool:
    """``True`` si el paso se completó con un sustituto (mock, ``data/samples``, sintéticos)
    porque el proveedor real falló. La UI debe avisar: «este paso usó mock»."""
    return bool(metric.error) and str(metric.error).startswith(FALLBACK_PREFIX)


def step_error(metric: StepMetric) -> str | None:
    """Texto ``"Tipo: mensaje"`` del error de un paso fallido, o ``None`` si no falló."""
    return metric.error or None
