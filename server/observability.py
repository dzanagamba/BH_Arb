"""Structured logging and a dependency-free metrics registry (P1-2).

The scanner runs unattended, so the interesting events are the ones nobody is
watching: a scan that failed, a book that stopped answering, a feed that has not
refreshed. This module provides the two pieces needed to see those:

* a request/scan correlation id that is put on every log record emitted while a
  request or scan is running, and
* a tiny counters/gauges registry rendered in Prometheus text format.

Prometheus is a text protocol, not a library. Rendering it here keeps the
project free of a heavyweight optional dependency while still exposing the
standard scrape format.
"""

from __future__ import annotations

import contextvars
import json
import logging
import os
import re
import secrets
import sys
import threading
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from typing import Any

REQUEST_ID_HEADER = "X-Request-ID"
# A request id is echoed in logs and headers, so it must not be able to inject
# a newline or a forged field. Anything else is replaced with a fresh id.
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")

_request_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "bh_request_id", default="-"
)
_scan_id: contextvars.ContextVar[str] = contextvars.ContextVar("bh_scan_id", default="-")


def new_request_id() -> str:
    """A short, log-safe id. Not a security token; only a correlation handle."""
    return secrets.token_hex(8)


def valid_request_id(value: str | None) -> bool:
    return bool(value) and bool(_REQUEST_ID_PATTERN.match(value or ""))


def set_request_id(value: str) -> contextvars.Token[str]:
    return _request_id.set(value)


def reset_request_id(token: contextvars.Token[str]) -> None:
    _request_id.reset(token)


def current_request_id() -> str:
    return _request_id.get()


def set_scan_id(value: str) -> contextvars.Token[str]:
    return _scan_id.set(value)


def reset_scan_id(token: contextvars.Token[str]) -> None:
    _scan_id.reset(token)


def current_scan_id() -> str:
    return _scan_id.get()


_previous_record_factory = logging.getLogRecordFactory()
_record_factory_installed = False


def install_log_record_factory() -> None:
    """Stamp the active ids on every record as it is created.

    A handler filter only covers handlers we install; pytest's capture handler,
    uvicorn's handlers and any operator handler would otherwise see bare
    records. A record factory is the one seam every logger goes through. An
    explicit `extra={"request_id": ...}` still wins, because `Logger.makeRecord`
    applies extras after the factory returns.
    """
    global _previous_record_factory, _record_factory_installed
    if _record_factory_installed:
        return
    _previous_record_factory = logging.getLogRecordFactory()

    def factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
        record = _previous_record_factory(*args, **kwargs)
        if not getattr(record, "request_id", None):
            record.request_id = current_request_id()
        if not getattr(record, "scan_id", None):
            record.scan_id = current_scan_id()
        return record

    logging.setLogRecordFactory(factory)
    _record_factory_installed = True


install_log_record_factory()


class ContextLogFilter(logging.Filter):
    """Attach the active correlation ids to every record.

    A record may carry its own ``request_id``/``scan_id`` through ``extra``;
    that wins, so a log line emitted from a background task can name the scan it
    belongs to instead of inheriting the request that happened to start it.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if not getattr(record, "request_id", None):
            record.request_id = current_request_id()
        if not getattr(record, "scan_id", None):
            record.scan_id = current_scan_id()
        return True


# Only these structured fields are serialised. Everything else on a record
# stays out, so a caller cannot accidentally log a token, an API key or a full
# odds payload by passing it as an extra.
_ALLOWED_EXTRAS = (
    "mode",
    "duration_seconds",
    "books",
    "books_total",
    "groups",
    "surebets",
    "drops",
    "cache_bytes",
    "request_method",
    "request_path",
    "status_code",
)

_TEXT_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | req=%(request_id)s | %(message)s"


class JsonLogFormatter(logging.Formatter):
    """One JSON object per line, with the correlation ids and known fields."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "time": datetime.fromtimestamp(record.created, UTC)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }
        scan_id = getattr(record, "scan_id", "-")
        if scan_id and scan_id != "-":
            payload["scan_id"] = scan_id
        for key in _ALLOWED_EXTRAS:
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(level: str = "INFO", log_format: str = "text") -> None:
    """Install one stderr handler on the root logger.

    ``log_format=json`` switches to line-delimited JSON; anything else keeps the
    readable text format. Replacing the root handler is deliberate: a second
    handler would double every line.
    """
    handler = logging.StreamHandler()
    handler.addFilter(ContextLogFilter())
    if str(log_format).strip().lower() == "json":
        handler.setFormatter(JsonLogFormatter())
    else:
        handler.setFormatter(logging.Formatter(_TEXT_FORMAT, datefmt="%H:%M:%S"))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(getattr(logging, str(level).strip().upper(), logging.INFO))


# ─── Metrics ────────────────────────────────────────────────────────────────

LabelSet = tuple[tuple[str, str], ...]
GaugeProvider = Callable[[], Iterable[tuple[dict[str, object], float]]]


def _label_set(labels: dict[str, object]) -> LabelSet:
    return tuple(sorted((str(key), str(value)) for key, value in labels.items()))


def _escape_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _format_value(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else repr(float(value))


# Default latency buckets in seconds; a per-metric override is possible.
HISTOGRAM_BUCKETS: tuple[float, ...] = (
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
    30.0,
    60.0,
    120.0,
)


class MetricsRegistry:
    """Counters, gauges, histograms and dynamic gauge providers with one lock.

    Deliberately small: no multiprocess state, no registry of registries. A scan
    runs in one process, and the endpoint renders what that process has seen
    since start. Histograms use cumulative buckets and carry ``_sum``/``_count``.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, dict[LabelSet, float]] = {}
        self._gauges: dict[str, dict[LabelSet, float]] = {}
        self._histograms: dict[str, dict[LabelSet, dict[str, Any]]] = {}
        self._help: dict[str, str] = {}
        self._providers: dict[str, tuple[str, GaugeProvider]] = {}

    def inc(self, name: str, amount: float = 1.0, **labels: object) -> None:
        key = _label_set(labels)
        with self._lock:
            family = self._counters.setdefault(name, {})
            family[key] = family.get(key, 0.0) + float(amount)
            self._help.setdefault(name, f"BH_Arb counter {name}")

    def set_gauge(self, name: str, value: float, **labels: object) -> None:
        key = _label_set(labels)
        with self._lock:
            self._gauges.setdefault(name, {})[key] = float(value)
            self._help.setdefault(name, f"BH_Arb gauge {name}")

    def add_gauge(self, name: str, amount: float = 1.0, **labels: object) -> None:
        """Adjust a gauge by a delta, for counters of things currently open."""
        key = _label_set(labels)
        with self._lock:
            family = self._gauges.setdefault(name, {})
            family[key] = family.get(key, 0.0) + float(amount)
            self._help.setdefault(name, f"BH_Arb gauge {name}")

    def observe(
        self,
        name: str,
        value: float,
        *,
        buckets: tuple[float, ...] | None = None,
        **labels: object,
    ) -> None:
        """Record one observation in a cumulative histogram."""
        key = _label_set(labels)
        bounds = HISTOGRAM_BUCKETS if buckets is None else buckets
        with self._lock:
            family = self._histograms.setdefault(name, {})
            state = family.get(key)
            if state is None:
                state = {
                    "bounds": tuple(float(bound) for bound in bounds),
                    "counts": [0] * len(bounds),
                    "sum": 0.0,
                    "count": 0,
                }
                family[key] = state
            sample = float(value)
            for index, bound in enumerate(state["bounds"]):
                if sample <= bound:
                    state["counts"][index] += 1
            state["sum"] += sample
            state["count"] += 1
            self._help.setdefault(name, f"BH_Arb histogram {name}")

    def register_gauge_provider(
        self, name: str, help_text: str, provider: GaugeProvider
    ) -> None:
        """Register a gauge computed at scrape time (RSS, scan age, cache size)."""
        with self._lock:
            self._providers[name] = (help_text, provider)
            self._help[name] = help_text

    def reset_values(self) -> None:
        """Clear samples but keep providers, for a clean test or a fresh run."""
        with self._lock:
            self._counters.clear()
            self._gauges.clear()
            self._histograms.clear()

    def histogram_snapshot(self) -> dict[str, dict[LabelSet, dict[str, Any]]]:
        """A copy of the histogram state (tests and diagnostics)."""
        with self._lock:
            return {
                name: {
                    labels: {
                        "bounds": list(state["bounds"]),
                        "counts": list(state["counts"]),
                        "sum": state["sum"],
                        "count": state["count"],
                    }
                    for labels, state in family.items()
                }
                for name, family in self._histograms.items()
            }

    def snapshot(self) -> tuple[dict[str, dict[LabelSet, float]], dict[str, dict[LabelSet, float]]]:
        with self._lock:
            counters = {name: dict(values) for name, values in self._counters.items()}
            gauges = {name: dict(values) for name, values in self._gauges.items()}
            providers = list(self._providers.items())
            helps = dict(self._help)
        for name, (_help_text, provider) in providers:
            samples: dict[LabelSet, float] = {}
            try:
                for labels, value in provider():
                    samples[_label_set(labels)] = float(value)
            except Exception:  # a broken gauge must not take the endpoint down
                continue
            gauges[name] = samples
            helps.setdefault(name, name)
        self._help.update(helps)
        return counters, gauges

    @staticmethod
    def _format_labels(labels: LabelSet, extra: tuple[str, str] | None = None) -> str:
        pairs = list(labels)
        if extra is not None:
            pairs.append(extra)
        if not pairs:
            return ""
        return "{" + ",".join(
            f'{key}="{_escape_label(value)}"' for key, value in pairs
        ) + "}"

    def render(self) -> str:
        """Render the registry in Prometheus text exposition format."""
        counters, gauges = self.snapshot()
        with self._lock:
            histograms = {
                name: {
                    labels: {
                        "bounds": list(state["bounds"]),
                        "counts": list(state["counts"]),
                        "sum": state["sum"],
                        "count": state["count"],
                    }
                    for labels, state in family.items()
                }
                for name, family in self._histograms.items()
            }
        lines: list[str] = []
        for name in sorted(set(counters) | set(gauges) | set(histograms)):
            if name in histograms:
                lines.append(f"# HELP {name} {self._help.get(name, name)}")
                lines.append(f"# TYPE {name} histogram")
                for labels, state in sorted(histograms[name].items()):
                    for bound, count in zip(
                        state["bounds"], state["counts"], strict=True
                    ):
                        lines.append(
                            f"{name}_bucket"
                            f"{self._format_labels(labels, ('le', _format_value(bound)))}"
                            f" {count}"
                        )
                    lines.append(
                        f"{name}_bucket"
                        f"{self._format_labels(labels, ('le', '+Inf'))}"
                        f" {state['count']}"
                    )
                    lines.append(
                        f"{name}_sum{self._format_labels(labels)} "
                        f"{_format_value(state['sum'])}"
                    )
                    lines.append(
                        f"{name}_count{self._format_labels(labels)} "
                        f"{state['count']}"
                    )
                continue
            metric_type = "counter" if name in counters else "gauge"
            lines.append(f"# HELP {name} {self._help.get(name, name)}")
            lines.append(f"# TYPE {name} {metric_type}")
            values = counters.get(name) or gauges.get(name) or {}
            for labels, value in sorted(values.items()):
                lines.append(
                    f"{name}{self._format_labels(labels)} {_format_value(value)}"
                )
        return "\n".join(lines) + ("\n" if lines else "")


metrics = MetricsRegistry()


def _rss_bytes() -> float | None:
    """Resident set size, from /proc where available and getrusage otherwise."""
    try:
        with open("/proc/self/statm", encoding="ascii") as file:
            resident_pages = int(file.read().split()[1])
        return float(resident_pages * os.sysconf("SC_PAGE_SIZE"))
    except (OSError, ValueError, IndexError):
        pass
    try:
        import resource

        usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return float(usage if sys.platform == "darwin" else usage * 1024)
    except (ImportError, OSError, ValueError):
        return None


def current_rss_bytes() -> float | None:
    """Public RSS probe for health reporting and the resource-budget alert."""
    return _rss_bytes()


def _rss_samples() -> list[tuple[dict[str, object], float]]:
    value = _rss_bytes()
    return [] if value is None else [({}, value)]


metrics.register_gauge_provider(
    "bh_rss_bytes",
    "Resident set size of the scanner process in bytes.",
    _rss_samples,
)
