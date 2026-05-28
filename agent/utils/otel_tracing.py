"""OpenTelemetry bootstrap for brain process (optional, env-gated).

Enables:
- OTLP trace export (Langfuse OTEL endpoint or any OTLP collector)
- HTTPX context propagation (`traceparent`/`baggage`) for outbound requests
"""

from __future__ import annotations

import logging
import os
import base64

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

    service_name = (os.environ.get("OTEL_SERVICE_NAME") or "datasyn-brain").strip()
    environment = (os.environ.get("DEPLOYMENT_ENV") or "production").strip()
    resource = Resource.create(
        {
            "service.name": service_name,
            "service.namespace": "datasyn",
            "deployment.environment": environment,
        }
    )

    provider = TracerProvider(resource=resource)
    exporter_kwargs = _resolve_otlp_exporter_kwargs()
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(**exporter_kwargs)))
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


def _resolve_otlp_exporter_kwargs() -> dict[str, dict[str, str]]:
    """Populate OTLP headers from Langfuse keys when unset or placeholder-valued."""
    headers = (os.environ.get("OTEL_EXPORTER_OTLP_HEADERS") or "").strip()
    if headers and "<BASE64_PUBLIC_COLON_SECRET>" not in headers:
        return {}

    pub = (os.environ.get("LANGFUSE_PUBLIC_KEY") or "").strip()
    sec = (os.environ.get("LANGFUSE_SECRET_KEY") or "").strip()
    if not (pub and sec):
        if headers:
            logger.warning(
                "OTEL_EXPORTER_OTLP_HEADERS still contains placeholder but Langfuse keys are missing; "
                "tracing export may fail with 401."
            )
        return {}

    token = base64.b64encode(f"{pub}:{sec}".encode("utf-8")).decode("ascii")
    return {"headers": {"Authorization": f"Basic {token}"}}

