# Operator alerts

P1-5. The scanner can notify an operator when a new surebet clears a threshold,
a feed goes stale or a book is quarantined, a book reaches the scheduled-scan
backoff threshold, or a resource budget is crossed.

The default is **no transport**. A checkout that configures nothing sends
nothing, and `/api/health` still reports zero counters.

## Configure

Set either or both transports in `.env` (or the systemd `EnvironmentFile`):

```bash
# Generic webhook: one JSON POST per alert.
ALERT_WEBHOOK_URL=https://example.invalid/bh-arb

# Telegram: both values are required.
ALERT_TELEGRAM_BOT_TOKEN=...
ALERT_TELEGRAM_CHAT_ID=...
```

| Variable | Default | Meaning |
|---|---|---|
| `ALERT_WEBHOOK_URL` | empty | POST `{kind, signature, mode, title, message}` as JSON. |
| `ALERT_TELEGRAM_BOT_TOKEN` | empty | Telegram bot token. Never logged or exposed. |
| `ALERT_TELEGRAM_CHAT_ID` | empty | Destination chat id. |
| `ALERT_MIN_PROFIT_PERCENT` | `3.0` | Minimum `profit_percent` for a surebet alert. |
| `ALERT_DEDUPE_MINUTES` | `60` | At most one alert per signature in this window. |
| `ALERT_RETRY_ATTEMPTS` | `3` | Attempts per transport, from the alert worker. |
| `ALERT_RETRY_BASE_SECONDS` | `1.0` | Exponential backoff base. |

## Behaviour

- **Dedupe** is keyed by a hash of match, market, leg identities and the
  one-point profit bucket. A price move inside the same bucket is the same
  opportunity; crossing into the next bucket is a new alert. The window is
  in-memory and starts fresh on restart.
- **Delivery is asynchronous.** A single daemon worker sends the queued alert
  and retries with exponential backoff. A webhook timeout or a Telegram 500
  cannot block or fail the scan that produced the alert.
- **Failures are counted and logged by type only.** The raw exception can repeat
  a webhook URL or a Telegram bot token, so it is never logged.
- **Health and metrics expose counts, never secrets.** `/api/health` has
  `alerts.sent`, `alerts.failed`, `alerts.suppressed`, `alerts.pending` and
  transport names. Prometheus gets
  `bh_alerts_sent_total`, `bh_alerts_failed_total` and
  `bh_alerts_suppressed_total`, labelled by kind (and transport for sent/failed).
- **Alert bodies use dashboard labels.** They carry the match, market, profit
  and one line per leg, not the full scan payload or any API key.

## Check it

```bash
# Counters and transport names (no URLs or tokens)
curl -fsS http://127.0.0.1:8000/api/health | python -m json.tool | grep -A8 '"alerts"'

# Prometheus
curl -fsS -H "X-API-Key: $API_KEY" http://127.0.0.1:8000/api/metrics | grep bh_alerts
```

The offline tests use a fake transport: `python -m pytest tests/test_alerts.py`.

## Notes

- A webhook URL should be treated as a secret if it embeds a token. Put it in
  `.env` or the systemd environment file, not in the repository.
- Alerts are a notification path, not a health guarantee. Keep the existing
  `/api/health`, `/api/metrics` and dashboard banners as the source of truth.
