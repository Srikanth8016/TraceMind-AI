"""
app/metrics.py — Lightweight in-memory operational metrics and request telemetry.

Milestone 15: Production Logging, Configuration & Observability.
Provides thread-safe request counters, error rates, and latency tracking
without requiring external heavy telemetry stacks or SaaS dependencies.
"""

from collections import defaultdict
from dataclasses import dataclass, field
import threading
import time
from typing import Any, Dict


@dataclass
class MetricsState:
    """Thread-safe telemetry accumulator."""
    lock: threading.Lock = field(default_factory=threading.Lock)
    started_at: float = field(default_factory=time.time)
    total_requests: int = 0
    total_errors_4xx: int = 0
    total_errors_5xx: int = 0
    total_duration_ms: float = 0.0
    status_counts: dict[int, int] = field(default_factory=lambda: defaultdict(int))
    endpoint_counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))

    def record(self, method: str, path: str, status_code: int, duration_ms: float) -> None:
        """Record a single HTTP transaction."""
        with self.lock:
            self.total_requests += 1
            self.total_duration_ms += duration_ms
            self.status_counts[status_code] += 1
            self.endpoint_counts[f"{method} {path}"] += 1

            if 400 <= status_code < 500:
                self.total_errors_4xx += 1
            elif status_code >= 500:
                self.total_errors_5xx += 1

    def snapshot(self) -> Dict[str, Any]:
        """Return a read-only dictionary snapshot of current metrics."""
        with self.lock:
            uptime_seconds = round(time.time() - self.started_at, 2)
            avg_latency_ms = (
                round(self.total_duration_ms / self.total_requests, 2)
                if self.total_requests > 0
                else 0.0
            )
            return {
                "uptime_seconds": uptime_seconds,
                "total_requests": self.total_requests,
                "total_errors_4xx": self.total_errors_4xx,
                "total_errors_5xx": self.total_errors_5xx,
                "avg_latency_ms": avg_latency_ms,
                "status_counts": dict(self.status_counts),
            }

    def reset(self) -> None:
        """Reset metrics counters (primarily used for test suite isolation)."""
        with self.lock:
            self.started_at = time.time()
            self.total_requests = 0
            self.total_errors_4xx = 0
            self.total_errors_5xx = 0
            self.total_duration_ms = 0.0
            self.status_counts.clear()
            self.endpoint_counts.clear()


# Global singleton metrics collector
metrics_collector = MetricsState()


def record_request_metric(method: str, path: str, status_code: int, duration_ms: float) -> None:
    """Record HTTP request metrics into global collector."""
    metrics_collector.record(method, path, status_code, duration_ms)


def get_metrics_snapshot() -> Dict[str, Any]:
    """Retrieve current operational telemetry snapshot."""
    return metrics_collector.snapshot()
