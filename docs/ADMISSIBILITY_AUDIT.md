# Dated sport/market admissibility audit (N3-2)

Admissibility is evidence-first. The rule was fixed before the expansion and is
not tunable:

> A sport is admissible only when at least three of the enabled books publish at
> least three comparable full-match families **under the same settlement**. A
> market family is enabled only after its own dated evidence.

N3-2 makes that one-off measurement repeatable. It does not change the rule, a
parser, the registry, `ENABLED_SPORTS` or `ENABLED_MARKETS`. A changed feed is a
prompt for a human re-measurement and a new evidence row, never an automatic
admission.

## Report

`engine/admissibility.py` builds a stable, offline report from the shipped dated
evidence:

| Source | What it proves |
|---|---|
| `docs/evidence/2026-11-04-sport-discovery.json` | Per-book family coverage for basketball, tennis and the blocked ice hockey probe. |
| `docs/evidence/2026-11-04-football-lines.json` | Measured cross-book coverage for the 0.5/4.5/5.5 goal lines. |
| `docs/evidence/2026-11-04-prematch-scan.json` | Dated football scan used as the evidence row for the remaining enabled football markets. |
| `config/bookmaker_markets.json` | Registry declarations per book for each enabled football market. |

Every enabled sport and market entry carries `evidence.path`,
`evidence.observed_at` and `evidence.available`. The report also records:

* per-book `families` counts and `settlements`;
* `qualifying_books` and the `admissible`/`admitted` status;
* `missing_families` (a canonical family absent from all measured books);
* per-market `declared_books` (prematch/live) and measured `price_sources`.

The report is a measurement record. The code still decides what is enabled.

## Baseline and change detection

The dated snapshot is
`docs/evidence/2026-11-08-admissibility-baseline.json`. `detect_changes` compares
a fresh report with it:

**Failures** (exit 1)

* an admitted sport or market is no longer admitted;
* a previously measured family disappears for a book, or a qualifying book
  drops below three comparable families;
* a sport family's or an enabled market's settlement changes;
* a measured price source for an admitted line disappears;
* the shipped baseline or the current report uses a different rule
  (`min_books != 3`, `min_families != 3`, `same_settlement != true`,
  `auto_admit != false`);
* an enabled sport or market has no available dated evidence row.

**Warnings** (exit 0, visible in the report)

* a new family, book, price source, sport or market appears without evidence.

A warning never changes an `admitted` flag. A new family remains unpriced until
a human updates the parser, the evidence and the registry, and the code change
is reviewed.

## Commands

```bash
# Offline report (default: print JSON)
python scripts/audit_admissibility.py

# CI / local gate: exit 1 on a disappeared admitted family or a changed rule
python scripts/audit_admissibility.py --check

# Write the report to a dated artifact
python scripts/audit_admissibility.py --out docs/evidence/2026-11-05-admissibility-report.json

# After a reviewed re-measurement, record a new baseline (never enables anything)
python scripts/audit_admissibility.py --write-baseline \
  --baseline docs/evidence/2026-11-XX-admissibility-baseline.json
```

`/api/health.admissibility_audit` exposes the same check as a bounded block:
status, failure/warning counts, per-sport admission flags and per-market
evidence paths. It never contains the full per-book report.

## Scheduled re-measurement

CI runs `--check` on every push and pull request, so a code or registry change
that loses an admitted family fails before it reaches a deployment. The live
network probe is deliberately **not** in CI: it calls bookmakers and would make
the suite non-hermetic.

For a weekly operator re-measurement:

```bash
# 1. Run the live probe and keep the dated output.
python scripts/measure_sports.py --out docs/evidence/$(date +%F)-sport-discovery.json

# 2. Review the diff against the new evidence file.
python scripts/audit_admissibility.py \
  --sport-evidence docs/evidence/$(date +%F)-sport-discovery.json

# 3. Only after review, record the new baseline.
python scripts/audit_admissibility.py \
  --sport-evidence docs/evidence/$(date +%F)-sport-discovery.json \
  --write-baseline --baseline docs/evidence/$(date +%F)-admissibility-baseline.json
```

A cron or systemd timer can run step 1 weekly and leave the report for review;
it must never run `--write-baseline` unattended. The same rule applies to a new
sport or market: the audit only shows the gap.

## Ice hockey remains blocked

The dated measurement gives sportplus and mbet three regular-time families, but
only two books reach the threshold. NSoft has no full-match handicap id and
MaxBet's only total includes overtime. Lowering the threshold to two books or
treating an incl-OT total as comparable would weaken the gate, so ice hockey
stays `not_enabled` in the report. A future measurement that reaches three books
would raise an `admissible` flag and a warning, **not** an admission.
