"""
Shared Non-Functional Requirements (NFR) utilities for the e-commerce platform.

Import from here in any service:
    from nfr.structured_logging import setup_logging, RequestLoggingMiddleware
    from nfr.circuit_breaker import CircuitBreaker
    from nfr.metrics import instrument_app
"""
