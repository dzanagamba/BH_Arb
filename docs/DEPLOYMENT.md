# Deployment

Two supported shapes: Docker Compose for a fresh Linux host, and a systemd
unit for a bare-metal install. Both run the scanner as a non-root user, keep
runtime state outside the image/checkout, and health-check `/api/health`.

The scanner never logs in, moves money or places a bet. It still holds an API
key and cached bookmaker data, so treat the host and the backup archive as
sensitive.

## Docker Compose

Prerequisites: Docker Engine with the Compose v2 plugin, and a clone of this
repository.

```bash
git clone https://github.com/dzanagamba/BH_Arb.git
cd BH_Arb
mkdir -p cache
docker compose up --build -d
docker compose ps
curl -fsS http://127.0.0.1:8000/api/health
```

The first build installs Chromium and its system libraries. Expect roughly
5–10 minutes and a 1–1.5 GB image; later builds reuse the dependency layer.

The dashboard is at `http://127.0.0.1:8000/`. The published port is bound to
loopback by default. Publishing it on `0.0.0.0` is only safe behind a firewall
and with `API_KEY` set.

### Persistence

`docker-compose.yml` bind-mounts:

| Host path | Container path | Why it must persist |
|---|---|---|
| `./cache` | `/app/cache` | Scan results, history, opportunity metrics, feed integrity, deep-link proofs and decisions, bookmaker/market toggles |
| `./config` | `/app/config` | Learned mapping ledger (`config/generated/mapping_evidence.json`), the human-approved `team_alias_allowlist.json`, and any edited declarations |

The container's user is the image's non-root `scanner` user, built with UID/GID
`1000` by default. If your host user is different, build with matching ids and
make the state directories writable by that uid:

```bash
mkdir -p cache config/generated
docker compose build \
  --build-arg BH_UID="$(id -u)" \
  --build-arg BH_GID="$(id -g)"
docker compose up -d
```

`docker compose exec scanner id -u` must print a non-zero id.

A restart keeps the files even though the process starts fresh:

```bash
docker compose restart scanner
docker compose exec scanner ls -l /app/cache
```

Note that `_load_cache` still applies its 30-minute TTL: an old scan file stays
on disk but is not replayed into the dashboard after that window.

### Configuration

Compose reads the repository `.env` for interpolation (it never enters the
image). The supported variables are the same as `.env.example`, notably
`API_KEY`, `AUTO_SCAN_PREMATCH_MINUTES`, `AUTO_SCAN_LIVE_MINUTES`,
`LOG_LEVEL`, `LOG_FORMAT`, `HEADLESS` and `PRICE_GUARD_ENABLED`.

### Health and metrics

```bash
curl -fsS http://127.0.0.1:8000/api/health
curl -fsS -H "X-API-Key: $API_KEY" http://127.0.0.1:8000/api/metrics
```

`/api/health` is exempt from the API key so container health checks work
unconditionally. `/api/metrics` is protected like every other `/api` route.

### Smoke test

`scripts/docker_smoke.py` builds the image (unless `--no-build`), starts a
container with a named cache volume, polls `/api/health`, verifies the process
is non-root, writes a marker into `/app/cache`, restarts the container and
checks the marker is still there:

```bash
python scripts/docker_smoke.py
python scripts/docker_smoke.py --no-build --image bh-arb:local
```

The optional `.github/workflows/docker.yml` workflow runs the build and this
smoke test on demand, and when the deployment files change. It is not part of
the fast unit-test job because the Chromium layer dominates the build time.

## Bare metal (systemd)

The example unit is `deploy/bh-arb.service` (installed as
`/etc/systemd/system/bh-arb.service`).

```bash
sudo useradd --system --create-home --shell /usr/sbin/nologin bh-arb
sudo git clone https://github.com/dzanagamba/BH_Arb.git /opt/bh-arb
sudo chown -R bh-arb:bh-arb /opt/bh-arb

sudo -u bh-arb python3.11 -m venv /opt/bh-arb/.venv
sudo -u bh-arb /opt/bh-arb/.venv/bin/pip install -r /opt/bh-arb/requirements.txt

# The browser install needs root for apt packages; put the browsers under the
# same path the unit exports, then hand ownership back to the service user.
sudo PLAYWRIGHT_BROWSERS_PATH=/opt/bh-arb/playwright-browsers \
  /opt/bh-arb/.venv/bin/playwright install --with-deps chromium
sudo chown -R bh-arb:bh-arb /opt/bh-arb/playwright-browsers

sudo -u bh-arb mkdir -p /opt/bh-arb/cache /opt/bh-arb/config/generated
sudo install -m 0644 /opt/bh-arb/deploy/bh-arb.service /etc/systemd/system/bh-arb.service
sudo systemctl daemon-reload
sudo systemctl enable --now bh-arb
systemctl status bh-arb --no-pager
curl -fsS http://127.0.0.1:8000/api/health
```

Put secrets and settings in `/etc/bh-arb.env` (same names as `.env.example`),
then `sudo systemctl restart bh-arb`. The unit ignores a missing file and keeps
its defaults.

The unit runs with `ProtectSystem=strict` and `ProtectHome=true`. Only
`cache/`, `config/generated/` and `config/team_alias_allowlist.json` are
writable; keep the Playwright browsers under `/opt/bh-arb/playwright-browsers`
as shown, or adjust `PLAYWRIGHT_BROWSERS_PATH` and the write paths together.

## Backup and restore

Back up these paths (stop the service first, or at least a scan, so a JSON file
is not being replaced mid-copy):

- `cache/` — scan caches, history, opportunity metrics, feed integrity,
  deep-link verification and decision stores, runtime toggles.
- `config/generated/mapping_evidence.json` — the learned mapping ledger. It is
  gitignored and rebuilt only by scans; losing it loses learned aliases.
- `config/team_alias_allowlist.json` — human-approved aliases.
- `config/bookmaker_deeplinks.json` — declarations, if the deployment edited
  them.
- `.env` / `/etc/bh-arb.env` — configuration and the API key. Store separately
  and encrypted; never commit it.

```bash
# Backup (Docker layout)
tar -czf bh-arb-backup-$(date +%F).tar.gz \
  cache config/generated/mapping_evidence.json \
  config/team_alias_allowlist.json config/bookmaker_deeplinks.json
```

```bash
# Restore into a stopped deployment
tar -xzf bh-arb-backup-2026-11-04.tar.gz -C /path/to/BH_Arb
sudo chown -R "$(id -u):$(id -g)" cache config
docker compose up -d
```

For systemd, untar under `/opt/bh-arb`, then
`sudo chown -R bh-arb:bh-arb /opt/bh-arb/cache /opt/bh-arb/config && sudo systemctl start bh-arb`.

The mapping ledger and allowlist are trust inputs: restoring an old copy can
re-introduce an alias a later run removed. Prefer restoring them together with
the cache from the same point in time.
