"""Structured logging, Prometheus metrics, and optional Phoenix (local) hooks."""
from __future__ import annotations

import os
import sys
import time
import uuid
from typing import Optional

import structlog
from flask import Flask, Response, g, request
from prometheus_client import Counter, Histogram
from prometheus_flask_exporter import PrometheusMetrics

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
    cache_logger_on_first_use=True,
)

log = structlog.get_logger(__name__)

resume_ranking_requests_total = Counter(
    "resume_ranking_requests_total",
    "Resume ranking API requests",
    ["algorithm", "status"],
)
resume_ranking_latency_seconds = Histogram(
    "resume_ranking_latency_seconds",
    "Wall time spent in ranking pipeline",
    ["algorithm"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0),
)
resume_ranking_score_distribution = Histogram(
    "resume_ranking_score_distribution",
    "Distribution of final match scores (0–1)",
    buckets=(0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0),
)
llm_expansion_calls_total = Counter(
    "llm_expansion_calls_total",
    "JD LLM expansion attempts",
    ["status"],
)

_metrics_exporter: Optional[PrometheusMetrics] = None
_phoenix_register_done: bool = False


def get_metrics_exporter() -> Optional[PrometheusMetrics]:
    return _metrics_exporter


def init_observability(app: Flask) -> PrometheusMetrics:
    """Register Prometheus /metrics, request timing hooks, and optional Phoenix."""
    global _metrics_exporter, _phoenix_register_done

    if _metrics_exporter is None:
        _metrics_exporter = PrometheusMetrics(app, path="/metrics")
    else:
        _metrics_exporter.init_app(app)

    @app.before_request
    def _obs_before_request():
        g._rank_start = time.perf_counter()
        rid = str(uuid.uuid4())
        g.request_id = rid
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=rid)

    @app.after_request
    def _obs_after_request(response: Response):
        rid = getattr(g, "request_id", None)
        if rid:
            response.headers["X-Request-ID"] = rid
        if hasattr(g, "_rank_start"):
            elapsed = time.perf_counter() - g._rank_start
            log.info(
                "request_complete",
                path=request.path,
                method=request.method,
                status=response.status_code,
                duration_s=round(elapsed, 4),
            )
        return response

    if os.getenv("PHOENIX_ENABLED", "").lower() in ("1", "true", "yes") and not _phoenix_register_done:
        _phoenix_register_done = True
        try:
            from phoenix.otel import register

            # batch=True uses BatchSpanProcessor (avoids SimpleSpanProcessor production warning).
            register(project_name="resume-ranking", batch=True, verbose=False)
            log.info(
                "phoenix_otel_registered",
                hint="Run `phoenix serve` or UI separately; OTLP export uses PHOENIX_* / collector env",
            )
        except Exception as exc:  # pragma: no cover
            log.warning("phoenix_register_failed", error=str(exc))

    return _metrics_exporter


def get_logger(name: str | None = None):
    return structlog.get_logger(name) if name else log
