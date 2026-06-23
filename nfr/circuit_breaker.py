"""
Simple in-process circuit breaker for inter-service HTTP calls.

States:
  CLOSED   → requests pass through normally
  OPEN     → requests fail immediately (fast-fail) — no call to the downstream service
  HALF_OPEN → one probe request allowed; success → CLOSED, failure → OPEN

Usage:
    from nfr.circuit_breaker import CircuitBreaker
    import httpx

    inventory_cb = CircuitBreaker(name="inventory_service", failure_threshold=5, recovery_timeout=30)

    @inventory_cb
    def fetch_stock(product_id: str):
        resp = httpx.get(f"http://localhost:8005/inventory/{product_id}", timeout=2)
        resp.raise_for_status()
        return resp.json()

    try:
        stock = fetch_stock("prod-123")
    except CircuitOpenError:
        stock = {"quantity": None, "source": "circuit_open"}  # graceful degradation
"""

import logging
import threading
import time
from enum import Enum
from functools import wraps
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    CLOSED    = "closed"
    OPEN      = "open"
    HALF_OPEN = "half_open"


class CircuitOpenError(Exception):
    """Raised when a call is attempted on an OPEN circuit."""

    def __init__(self, name: str):
        super().__init__(f"Circuit '{name}' is OPEN — downstream service unavailable")
        self.circuit_name = name


class CircuitBreaker:
    """
    Thread-safe circuit breaker.

    Args:
        name:               Identifier used in logs and error messages.
        failure_threshold:  Number of consecutive failures before opening the circuit.
        recovery_timeout:   Seconds to wait in OPEN state before trying a probe (HALF_OPEN).
        expected_exception: Exception type(s) that count as failures.
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: int = 30,
        expected_exception: type = Exception,
    ):
        self.name               = name
        self.failure_threshold  = failure_threshold
        self.recovery_timeout   = recovery_timeout
        self.expected_exception = expected_exception

        self._state          = CircuitState.CLOSED
        self._failure_count  = 0
        self._last_failure   = 0.0
        self._lock           = threading.Lock()

    # ── Public API ────────────────────────────────────────────────────────────

    @property
    def state(self) -> CircuitState:
        return self._state

    def call(self, func: Callable, *args, **kwargs):
        """Execute func through the circuit breaker."""
        with self._lock:
            state = self._resolve_state()

        if state == CircuitState.OPEN:
            logger.warning("Circuit OPEN — fast-failing", extra={"circuit": self.name})
            raise CircuitOpenError(self.name)

        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except self.expected_exception as exc:
            self._on_failure()
            raise exc

    def __call__(self, func: Callable):
        """Use as a decorator: @circuit_breaker"""
        @wraps(func)
        def wrapper(*args, **kwargs):
            return self.call(func, *args, **kwargs)
        return wrapper

    def status(self) -> dict:
        return {
            "name":            self.name,
            "state":           self._state.value,
            "failure_count":   self._failure_count,
            "threshold":       self.failure_threshold,
            "recovery_timeout": self.recovery_timeout,
        }

    # ── Internal ──────────────────────────────────────────────────────────────

    def _resolve_state(self) -> CircuitState:
        if self._state == CircuitState.OPEN:
            elapsed = time.monotonic() - self._last_failure
            if elapsed >= self.recovery_timeout:
                self._state = CircuitState.HALF_OPEN
                logger.info("Circuit → HALF_OPEN (probing)", extra={"circuit": self.name})
        return self._state

    def _on_success(self):
        with self._lock:
            if self._state in (CircuitState.HALF_OPEN, CircuitState.OPEN):
                logger.info("Circuit → CLOSED (recovered)", extra={"circuit": self.name})
            self._state         = CircuitState.CLOSED
            self._failure_count = 0

    def _on_failure(self):
        with self._lock:
            self._failure_count += 1
            self._last_failure   = time.monotonic()
            if self._failure_count >= self.failure_threshold or self._state == CircuitState.HALF_OPEN:
                self._state = CircuitState.OPEN
                logger.error(
                    "Circuit → OPEN after %d failures",
                    self._failure_count,
                    extra={"circuit": self.name},
                )


# ── Registry — one breaker per named downstream service ──────────────────────

_registry: dict[str, CircuitBreaker] = {}
_registry_lock = threading.Lock()


def get_breaker(
    name: str,
    failure_threshold: int = 5,
    recovery_timeout: int = 30,
) -> CircuitBreaker:
    """Return (or create) a named circuit breaker from the global registry."""
    with _registry_lock:
        if name not in _registry:
            _registry[name] = CircuitBreaker(
                name=name,
                failure_threshold=failure_threshold,
                recovery_timeout=recovery_timeout,
            )
        return _registry[name]


def all_statuses() -> list[dict]:
    """Snapshot of every registered breaker — useful for /health endpoints."""
    with _registry_lock:
        return [cb.status() for cb in _registry.values()]
