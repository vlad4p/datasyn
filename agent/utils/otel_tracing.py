"""OpenTelemetry bootstrap for brain process (optional, env-gated).

Enables:
- OTLP trace export (Langfuse OTEL endpoint or any OTLP collector)
- HTTPX context propagation (`traceparent`/`baggage`) for outbound requests
"""

from __future__ import annotations

import logging
import os

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

try:
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
except Exception:  # pragma: no cover - optional dependency at runtime
    HTTPXClientInstrumentor = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

_BOOTSTRAPPED = False


def otel_tracing_enabled() -> bool:
    """Treat OTEL as enabled when exporter is not disabled and endpoint exists."""
    if (os.environ.get("OTEL_TRACES_EXPORTER") or "").strip().lower() == "none":
        return False
    return bool((os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT") or "").strip())


def init_otel_tracing() -> None:
    """Initialize tracer provider + exporter once per process."""
    global _BOOTSTRAPPED
    if _BOOTSTRAPPED:
        return
    if not otel_tracing_enabled():
        return

    service_name = (os.environ.get("OTEL_SERVICE_NAME") or "datacyber-brain").strip()
    environment = (os.environ.get("DEPLOYMENT_ENV") or "production").strip()
    resource = Resource.create(
        {
            "service.name": service_name,
            "service.namespace": "datacyber",
            "deployment.environment": environment,
        }
    )

    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)

    # Propagate trace context in outbound HTTPX calls (LiteLLM, MCP servers, etc.).
    if HTTPXClientInstrumentor is not None:
        HTTPXClientInstrumentor().instrument()
    else:
        logger.warning(
            "OTEL HTTPX instrumentation package not installed; "
            "outbound automatic traceparent propagation via HTTPX is disabled."
        )

    _BOOTSTRAPPED = True
    logger.info("OTEL tracing initialized service.name=%s", service_name)

