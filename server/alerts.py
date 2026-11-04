"""Operator alerts with dedupe, retry and a null transport (P1-5).

An unattended scanner needs to say when something changed: a new surebet above
the operator's threshold, a feed that went stale, a book that keeps failing, or
the process crossing a resource budget. Sending that from the scan path would
make bookmaker latency and a webhook outage part of the scan result, so this
module only decides ``what`` to say. A single background worker does the
network I/O, retries transient failures, and cannot raise into a scan.

The default is a null transport: a fresh checkout sends nothing. Webhook and
Telegram transports are built from environment values in
:func:`configured_alert_manager`; secrets are never logged or exposed by the
health endpoint.
"""

from __future__ import annotations

import hashlib
import json
import logging
import queue
import threading
import time
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from config.settings import (
    ALERT_DEDUPE_MINUTES,
    ALERT_MIN_PROFIT_PERCENT,
    ALERT_RETRY_ATTEMPTS,
    ALERT_RETRY_BASE_SECONDS,
    ALERT_TELEGRAM_BOT_TOKEN,
    ALERT_TELEGRAM_CHAT_ID,
    ALERT_WEBHOOK_URL,
)
from server.observability import current_rss_bytes, metrics

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Alert:
    """One operator-facing message.

    ``signature`` is the stable dedupe key. ``body`` never contains an API key,
    a webhook token or a full scan payload; it is built from the same labels the
    dashboard shows.
    """

    kind: str
    signature: str
    title: str
    body: str
    mode: str = ""


class AlertTransport(Protocol):
    name: str

    def send(self, alert: Alert) -> None: ...


class NullTransport:
    """The default transport: accepts an alert and does nothing."""

    name = "null"

    def send(self, alert: Alert) -> None:
        return None


class WebhookTransport:
    """POST one JSON object to an operator-provided webhook URL."""

    name = "webhook"

    def __init__(self, url: str, timeout: float = 10.0) -> None:
        self._url = url
        self._timeout = timeout

    def __repr__(self) -> str:
        return "WebhookTransport(<configured>)"

    def send(self, alert: Alert) -> None:
        payload = json.dumps(
            {
                "kind": alert.kind,
                "signature": alert.signature,
                "mode": alert.mode,
                "title": alert.title,
                "message": alert.body,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        request = urllib.request.Request(
            self._url,
            data=payload,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "User-Agent": "BH_Arb-alerts/1",
            },
        )
        # The URL is operator-supplied and may be an internal HTTP endpoint.
        # Bandit B310 is accepted and documented in docs/CI.md.
        with urllib.request.urlopen(request, timeout=self._timeout) as response:  # nosec B310
            response.read(1024)


class TelegramTransport:
    """Send one Telegram message through the Bot API."""

    name = "telegram"

    def __init__(self, bot_token: str, chat_id: str, timeout: float = 10.0) -> None:
        self._bot_token = bot_token
        self._chat_id = chat_id
        self._timeout = timeout

    def __repr__(self) -> str:
        return "TelegramTransport(<configured>)"

    def send(self, alert: Alert) -> None:
        # The token is part of the Bot API URL, so the URL (and the raw
        # exception text that may repeat it) is never logged.
        url = f"https://api.telegram.org/bot{self._bot_token}/sendMessage"
        payload = urllib.parse.urlencode(
            {
                "chat_id": self._chat_id,
                "text": f"{alert.title}\n{alert.body}",
                "disable_web_page_preview": "true",
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=payload,
            method="POST",
            headers={"User-Agent": "BH_Arb-alerts/1"},
        )
        # Fixed Telegram HTTPS endpoint; B310 is accepted in docs/CI.md.
        with urllib.request.urlopen(request, timeout=self._timeout) as response:  # nosec B310
            response.read(1024)


def _sha(parts: Iterable[object]) -> str:
    raw = json.dumps(list(parts), ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def surebet_signature(surebet: Mapping[str, Any]) -> str:
    """A stable key for match + market + legs + one-point profit bucket.

    The odds themselves are deliberately excluded: a price that moves a few
    ticks inside the same bucket is the same opportunity, and re-alerting on it
    would train the operator to ignore alerts.
    """
    profit = float(surebet.get("profit_percent") or 0.0)
    bucket = int(profit // 1.0)
    legs = []
    for leg in surebet.get("stakes") or []:
        if not isinstance(leg, Mapping):
            continue
        legs.append(
            [
                str(leg.get("bookmaker") or ""),
                str(leg.get("outcome_label") or ""),
                str(leg.get("line") or ""),
                str(leg.get("selection") or ""),
            ]
        )
    return _sha(
        [
            "surebet",
            str(surebet.get("home_team") or ""),
            str(surebet.get("away_team") or ""),
            str(surebet.get("league") or ""),
            str(surebet.get("kickoff") or ""),
            str(surebet.get("market_type") or ""),
            sorted(legs),
            bucket,
        ]
    )


def surebet_alert(
    surebet: Mapping[str, Any],
    *,
    mode: str,
    min_profit_percent: float,
) -> Alert | None:
    """Build an alert for one surebet, or ``None`` below the threshold."""
    profit = float(surebet.get("profit_percent") or 0.0)
    if profit < min_profit_percent:
        return None
    home = str(surebet.get("home_team") or "?")
    away = str(surebet.get("away_team") or "?")
    market = str(surebet.get("market_type") or "?")
    league = str(surebet.get("league") or "unknown league")
    legs = []
    for leg in surebet.get("stakes") or []:
        if not isinstance(leg, Mapping):
            continue
        legs.append(
            f"{leg.get('bookmaker', '?')}: {leg.get('outcome_label', '?')} "
            f"@ {float(leg.get('odds') or 0):.2f}"
        )
    body = f"{league} | {market} | {profit:.2f}% profit\n{home} - {away}"
    if legs:
        body += "\n" + "\n".join(legs)
    return Alert(
        kind="surebet",
        signature=surebet_signature(surebet),
        title=f"{profit:.2f}% surebet: {home} - {away}",
        body=body,
        mode=mode,
    )


def feed_alerts(mode: str, freshness: Mapping[str, Any]) -> list[Alert]:
    """One alert per book whose prices are stale in the served feed."""
    if not freshness.get("stale") or freshness.get("state") == "never_scanned":
        return []
    state = str(freshness.get("state") or "stale")
    alerts: list[Alert] = []
    books = freshness.get("stale_books") or []
    if not books:
        return [
            Alert(
                kind="feed_stale",
                signature=_sha(["feed", mode, state]),
                title=f"{mode} feed is stale",
                body=f"The saved scan is labelled {state}; do not treat it as current.",
                mode=mode,
            )
        ]
    per_book = freshness.get("per_book") or {}
    for book in books:
        entry = per_book.get(book) if isinstance(per_book, Mapping) else {}
        oldest = entry.get("oldest_age_sec") if isinstance(entry, Mapping) else None
        age = f" (oldest price {float(oldest):.0f}s)" if oldest is not None else ""
        alerts.append(
            Alert(
                kind="feed_stale",
                signature=_sha(["feed", mode, "book", book]),
                title=f"{mode} feed stale: {book}",
                body=f"{book} prices are older than the feed TTL{age}. It is not priced.",
                mode=mode,
            )
        )
    return alerts


def quarantine_alerts(mode: str, scorecard: Mapping[str, Any]) -> list[Alert]:
    """One alert per book the feed-integrity scorecard quarantined."""
    alerts: list[Alert] = []
    for book, entry in scorecard.items():
        if not isinstance(entry, Mapping) or entry.get("state") != "quarantined":
            continue
        reasons = sorted(str(reason) for reason in entry.get("reasons") or [])
        if not reasons:
            continue
        alerts.append(
            Alert(
                kind="book_quarantined",
                signature=_sha(["quarantine", mode, book, reasons]),
                title=f"{mode}: {book} quarantined",
                body=(
                    f"{entry.get('name') or book} is excluded from pricing "
                    f"({', '.join(reasons)}). Recovery needs clean scans."
                ),
                mode=mode,
            )
        )
    return alerts


def book_failure_alert(
    mode: str, book: str, failures: int, threshold: int
) -> Alert | None:
    """Build an alert once a book reaches the backoff failure threshold."""
    if failures < threshold:
        return None
    return Alert(
        kind="book_failing",
        signature=_sha(["book_failure", mode, book]),
        title=f"{mode}: {book} failed {failures} scans",
        body=(
            f"{book} reached the {threshold}-failure backoff threshold. "
            "Scheduled scans will skip it until it recovers."
        ),
        mode=mode,
    )


def resource_alerts(
    mode: str,
    *,
    cache_bytes: int,
    cache_budget_bytes: int,
    rss_mb: float | None,
    rss_budget_mb: int,
) -> list[Alert]:
    """Soft alerts for the two budgets the soak run watches."""
    alerts: list[Alert] = []
    if cache_bytes > cache_budget_bytes:
        alerts.append(
            Alert(
                kind="cache_budget",
                signature=_sha(["cache_budget", mode]),
                title=f"{mode} cache over budget",
                body=(
                    f"{cache_bytes / (1024 * 1024):.1f} MB persisted, "
                    f"budget {cache_budget_bytes / (1024 * 1024):.1f} MB."
                ),
                mode=mode,
            )
        )
    if rss_mb is not None and rss_mb > rss_budget_mb:
        alerts.append(
            Alert(
                kind="rss_budget",
                signature=_sha(["rss_budget", mode]),
                title=f"{mode} scan over memory budget",
                body=f"RSS {rss_mb:.0f} MB, budget {rss_budget_mb} MB.",
                mode=mode,
            )
        )
    return alerts


class AlertManager:
    """Dedupe alerts and deliver them from one background worker."""

    def __init__(
        self,
        transports: Sequence[AlertTransport] | None = None,
        *,
        min_profit_percent: float = ALERT_MIN_PROFIT_PERCENT,
        dedupe_minutes: int = ALERT_DEDUPE_MINUTES,
        retry_attempts: int = ALERT_RETRY_ATTEMPTS,
        retry_base_seconds: float = ALERT_RETRY_BASE_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        given = list(transports) if transports else []
        self._transports: list[AlertTransport] = given or [NullTransport()]
        self.enabled = any(not isinstance(item, NullTransport) for item in self._transports)
        self.min_profit_percent = min_profit_percent
        self.dedupe_minutes = dedupe_minutes
        self.retry_attempts = max(1, retry_attempts)
        self.retry_base_seconds = max(0.0, retry_base_seconds)
        self._clock = clock
        self._lock = threading.Lock()
        self._dedupe: dict[str, float] = {}
        self._counts = {"sent": 0, "failed": 0, "suppressed": 0}
        self._pending = 0
        self._idle = threading.Condition()
        self._queue: queue.Queue[Alert | None] = queue.Queue()
        self._worker: threading.Thread | None = None

    def __repr__(self) -> str:
        names = ",".join(item.name for item in self._transports)
        return f"AlertManager(transports={names}, enabled={self.enabled})"

    def _ensure_worker(self) -> None:
        if self._worker is not None:
            return
        with self._lock:
            if self._worker is not None:
                return
            self._worker = threading.Thread(
                target=self._run,
                name="bh-alert-worker",
                daemon=True,
            )
            self._worker.start()

    def _run(self) -> None:
        while True:
            alert = self._queue.get()
            try:
                if alert is None:
                    return
                self._deliver(alert)
            finally:
                self._queue.task_done()
                with self._idle:
                    self._pending -= 1
                    if self._pending <= 0:
                        self._pending = 0
                        self._idle.notify_all()

    def notify(self, alert: Alert) -> bool:
        """Queue an alert unless the same signature is inside the window.

        Returns whether it was queued. Never raises: a bad alert must not turn
        a completed scan into a failed one.
        """
        if not self.enabled:
            return False
        window = max(0, self.dedupe_minutes) * 60
        now = self._clock()
        with self._lock:
            last = self._dedupe.get(alert.signature)
            if last is not None and now - last < window:
                self._counts["suppressed"] += 1
                metrics.inc(
                    "bh_alerts_suppressed_total",
                    1,
                    kind=alert.kind,
                    reason="dedupe",
                )
                logger.info(
                    "alert suppressed kind=%s signature=%s",
                    alert.kind,
                    alert.signature,
                )
                return False
            self._dedupe[alert.signature] = now
            cutoff = now - window
            for signature, seen in list(self._dedupe.items()):
                if seen < cutoff:
                    self._dedupe.pop(signature, None)
        self._ensure_worker()
        with self._idle:
            self._pending += 1
        self._queue.put(alert)
        return True

    def notify_many(self, alerts: Iterable[Alert]) -> int:
        return sum(1 for alert in alerts if self.notify(alert))

    def _deliver(self, alert: Alert) -> None:
        for transport in self._transports:
            if isinstance(transport, NullTransport):
                continue
            for attempt in range(self.retry_attempts):
                try:
                    transport.send(alert)
                except Exception as exc:  # noqa: BLE001 - delivery is best effort
                    if attempt + 1 < self.retry_attempts:
                        time.sleep(self.retry_base_seconds * (2**attempt))
                        continue
                    with self._lock:
                        self._counts["failed"] += 1
                    metrics.inc(
                        "bh_alerts_failed_total",
                        1,
                        kind=alert.kind,
                        transport=transport.name,
                    )
                    # Exception text can contain a webhook token or a Telegram
                    # bot token in the URL. Log only the type.
                    logger.warning(
                        "alert delivery failed kind=%s transport=%s signature=%s error=%s",
                        alert.kind,
                        transport.name,
                        alert.signature,
                        type(exc).__name__,
                    )
                    break
                else:
                    with self._lock:
                        self._counts["sent"] += 1
                    metrics.inc(
                        "bh_alerts_sent_total",
                        1,
                        kind=alert.kind,
                        transport=transport.name,
                    )
                    break

    def wait_idle(self, timeout: float = 5.0) -> bool:
        """Wait for queued alerts; used by tests and a clean shutdown."""
        deadline = time.monotonic() + timeout
        with self._idle:
            while self._pending:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._idle.wait(remaining)
        return True

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            counts = dict(self._counts)
            pending = self._pending
        return {
            "enabled": self.enabled,
            "transports": [item.name for item in self._transports],
            "min_profit_percent": self.min_profit_percent,
            "dedupe_minutes": self.dedupe_minutes,
            "sent": counts["sent"],
            "failed": counts["failed"],
            "suppressed": counts["suppressed"],
            "pending": pending,
        }


def configured_alert_manager() -> AlertManager:
    """Build the manager from environment settings.

    An empty webhook/token pair means no transport, which is the default. The
    returned object never contains the URL or token in its repr or snapshot.
    """
    transports: list[AlertTransport] = []
    if ALERT_WEBHOOK_URL:
        transports.append(WebhookTransport(ALERT_WEBHOOK_URL))
    if ALERT_TELEGRAM_BOT_TOKEN and ALERT_TELEGRAM_CHAT_ID:
        transports.append(
            TelegramTransport(ALERT_TELEGRAM_BOT_TOKEN, ALERT_TELEGRAM_CHAT_ID)
        )
    return AlertManager(transports or None)


def current_rss_mb() -> float | None:
    """RSS in MB for the resource budget; ``None`` where /proc is unavailable."""
    value = current_rss_bytes()
    return None if value is None else round(value / (1024 * 1024), 1)


__all__ = [
    "Alert",
    "AlertManager",
    "AlertTransport",
    "NullTransport",
    "TelegramTransport",
    "WebhookTransport",
    "book_failure_alert",
    "configured_alert_manager",
    "current_rss_mb",
    "feed_alerts",
    "quarantine_alerts",
    "resource_alerts",
    "surebet_alert",
    "surebet_signature",
]
