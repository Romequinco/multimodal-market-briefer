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
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

from briefer.schemas import StepMetric

_LOGGER_NAME = "briefer"
_configured = False

#: Longitud máxima del mensaje de error que se guarda en ``StepMetric.error``.
_ERROR_DETAIL_CHARS = 160


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
                logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%H:%M:%S")
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
        detail = " ".join(str(exc).split())[:_ERROR_DETAIL_CHARS]
        handle.error = f"{type(exc).__name__}: {detail}" if detail else type(exc).__name__
        raise
    finally:
        latency = time.perf_counter() - start
        handle.metric = StepMetric(
            step=handle.step,
            provider=handle.provider,
            model=handle.model,
            latency_s=round(latency, 4),
            est_cost_eur=round(handle.est_cost_eur, 6),
            error=handle.error,
            detail=handle.detail,
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
    detail = " ".join(str(exc).split())[:_ERROR_DETAIL_CHARS]
    cause = f"{type(exc).__name__}: {detail}" if detail else type(exc).__name__
    return f"{FALLBACK_PREFIX}{substitute} tras {cause}"


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
