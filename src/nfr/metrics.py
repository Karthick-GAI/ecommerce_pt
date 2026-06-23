"""
Prometheus metrics integration for FastAPI services.

Exposes /metrics in Prometheus text format using prometheus_fastapi_instrumentator.
Falls back gracefully if the library is not installed (capstone-safe).

Usage:
    from nfr.metrics import instrument_app

    instrument_app(app, service_name="user_management")
    # Then visit http://localhost:8000/metrics
"""

import logging

logger = logging.getLogger(__name__)


def instrument_app(app, service_name: str = "service") -> None:
    """
    Attach Prometheus instrumentation to a FastAPI app.

    Recorded metrics (auto-generated):
      http_requests_total           — counter by method / path / status
      http_request_duration_seconds — histogram of response latency
      http_requests_in_progress     — gauge of in-flight requests

    A custom gauge `service_info` is also registered so dashboards can
    identify which service / version is producing the metrics.
    """
    try:
        from prometheus_fastapi_instrumentator import Instrumentator
        from prometheus_client import Gauge, Info

        Instrumentator(
            should_group_status_codes=False,
            should_ignore_untemplated=True,
            excluded_handlers=["/metrics", "/health", "/"],
        ).instrument(app).expose(app, endpoint="/metrics", tags=["Observability"])

        # Service identity gauge — appears in Prometheus as service_info{service="..."}
        Info("service_info", "E-Commerce service metadata").info({"service": service_name})

        logger.info("Prometheus /metrics endpoint registered", extra={"service": service_name})

    except ImportError:
        logger.warning(
            "prometheus_fastapi_instrumentator not installed — /metrics endpoint skipped. "
            "Install with: pip install prometheus-fastapi-instrumentator",
            extra={"service": service_name},
        )
        # Register a stub /metrics route so health-check scripts don't 404
        from fastapi.responses import PlainTextResponse

        @app.get("/metrics", tags=["Observability"], include_in_schema=False)
        def metrics_stub():
            return PlainTextResponse(
                "# prometheus_fastapi_instrumentator not installed\n"
                f'# install: pip install prometheus-fastapi-instrumentator\n'
                f'service_available{{service="{service_name}"}} 1\n'
            )
