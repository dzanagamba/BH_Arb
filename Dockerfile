# syntax=docker/dockerfile:1
#
# Reproducible BH_Arb image (P1-3).
#
# Chromium is the size driver: `playwright install --with-deps chromium` adds
# roughly 400 MB of browser plus system libraries and is the slowest step on a
# cold build. It is installed into a shared path before the non-root user is
# switched on, so the runtime never needs root.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    HOST=0.0.0.0 \
    PORT=8000

# Match the host user that owns the bind-mounted cache/config directories.
# Override with `docker compose build --build-arg BH_UID=$(id -u) ...` when the
# host user is not 1000.
ARG BH_UID=1000
ARG BH_GID=1000

RUN groupadd --gid "${BH_GID}" scanner \
    && useradd --uid "${BH_UID}" --gid "${BH_GID}" \
        --create-home --shell /usr/sbin/nologin scanner

WORKDIR /app

# Dependencies first, so an application edit does not redownload them.
# The lock carries the full resolved runtime set, transitives included, so the
# image gets exactly the packages CI tested.
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock

# Chromium is the size driver (~400 MB of browser plus system libraries) and
# the slowest cold-build step, roughly 5–10 minutes on a clean runner. Keeping
# it in its own layer lets an app-only change restore it from the CI GHA layer
# cache; a requirements change still rebuilds it because the layer above moved.
RUN playwright install --with-deps chromium \
    && chmod -R o+rX /ms-playwright

# Application code, owned by the runtime user. config/ is writable because the
# allowlist and the learned mapping ledger are updated during operation.
COPY --chown=${BH_UID}:${BH_GID} . .
RUN mkdir -p /app/cache && chown "${BH_UID}:${BH_GID}" /app/cache

USER scanner
EXPOSE 8000

# The dashboard and every API route are served by this process. /api/health is
# exempt from API_KEY, so the probe works with or without a key configured.
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3)"

CMD ["python", "main.py"]
