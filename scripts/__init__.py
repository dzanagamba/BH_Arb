"""Developer scripts.

A package so that `scripts.verify_deeplinks` has exactly one module name for
importers and for mypy. It IS part of the running application —
`server/api.py` imports it for the `/api/verify-links` endpoint — while the other
modules here are standalone CLIs. The entry point still runs as
`python scripts/verify_deeplinks.py`.
"""
