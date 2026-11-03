# Replay corpus — 2026-11-03

Frozen from the real 2026-09-25 captures in `tests/fixtures/e2e_certified/`,
which the certified end-to-end test also uses. The odds, labels, event ids and
market rows are real; only the event shell (teams, league, kickoff) is the one
fixture those three captures are read against.

`scan.json` stores kickoffs at `2030-01-01T18:00` so the file is stable. The
replay harness shifts every kickoff by the same amount to a future date and
sets `fetched_at` to the replay time, preserving every relative gap.

Do not rewrite this directory from a live scan. Add a new dated directory
instead, so a replay result always names the corpus that produced it.
