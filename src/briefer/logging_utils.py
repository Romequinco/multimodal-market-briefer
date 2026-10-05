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
    - Las excepciones se registran en log y se propagan (no se tragan).
    """
    log = get_logger("pipeline")
    handle = StepHandle(step=step, provider=provider, model=model)
    start = time.perf_counter()
    failed = False
    try:
        yield handle
    except BaseException:
        failed = True
        raise
    finally:
        latency = time.perf_counter() - start
        handle.metric = StepMetric(
            step=handle.step,
            provider=handle.provider,
            model=handle.model,
            latency_s=round(latency, 4),
            est_cost_eur=round(handle.est_cost_eur, 6),
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
            " (FALLO)" if failed else "",
        )
