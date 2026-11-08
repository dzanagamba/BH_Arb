# Premier Kladionica delta sections — SR4-13

**Date:** 2026-11-08
**Status:** fixed and probed live in both modes.
**Fixture:** `tests/fixtures/wire/premier_kladionica_delta.json`
**Code:** `validate_premier_sync` in `scrapers/wire_schemas.py`

## What broke

SR5-2's baseline scans dropped `premier_kladionica` from both feeds with:

```text
premier_kladionica delta sync schema drift at 0: Value error,
odds row has 5 columns, expected at least 9
input_value=[0, '', 1794138522410, 4, 1308500813]
```

`validate_premier_sync(kind="delta")` validated **every non-empty delta
section** with the strict dogTipK odds adapter. The delta response is not one
table; section 0 is the execRes control row, which is 5 columns.

## The captured envelope

One live delta call (`dogadjajIDs` = 10 football ids,
`clientVer=1308505015`) returned five sections:

| index | table | rows | row width | example |
|---|---|---:|---:|---|
| 0 | execRes | 1 | 5 | `[0, "", 1794139866830, 4, 1308505019]` |
| 1 | dogVar | 279 | 14 | `[3841952, 2, 2338, 1, 0, 0, "", "", "", "", "X", null, null, 49]` |
| 2 | dogTipK odds | 1701 | 9 | `[3841952, 2, 2338, 1, 1, 1.0, 0, -1, 0]` |
| 3 | dogLiveScore | 26 | 43 | `[3841952, 1740870592110, 5, "ZAVRŠILO", ...]` |
| 4 | scalar section | 4 | — | `["0", "11", "12", ...]` |

The full sync is a different 15-slot array (12 slots non-empty in the same
call). A delta call with a single id and one with a bogus id both returned the
same five-section order, so the odds table is third in every observation — but
the module's protocol note says empty sections are omitted, so an index is not
a safe identifier. The fixture stores the five sections verbatim (one dogVar
row, two odds rows, one dogLiveScore row).

## The fix

A delta section is an odds table when at least one of its rows has the dogTipK
shape: columns 0/2/3/4 are ints, column 5 (price) is a number, column 7
(result) is a number. Every row of a recognised section is then validated by
the same strict adapter as before. The other sections are left unmodelled, as
they were for a full sync.

This keeps the strict check for real odds: a truncated row or a string price in
a recognised odds section still raises `schema_drift` and drops the book. The
one residual case is a section where **every** row lost the odds shape; it is
then indistinguishable from an auxiliary table, the parser reads no rows and
contributes no legs (fail closed), and SR4-4's raw-page fingerprint still
alarms.

## Live probe

```text
python scripts/probe_feeds.py --books premier_kladionica
  matches 700, duration 7.4 s
  1x2 698, btts 696, double_chance 694,
  over_under 0.5 465, 1.5 679, 2.5 694, 3.5 692, 4.5 667, 5.5 476
  (5,761 market rows)

python scripts/probe_feeds.py --books premier_kladionica --live
  matches 151, duration 5.2 s
  1x2 137, btts 112, double_chance 128,
  over_under 0.5 37, 1.5 83, 2.5 122, 3.5 114, 4.5 88, 5.5 47
  (868 market rows)
```

Both probes returned `"error": ""`; before the fix the same adapter raised
`schema_drift` and returned no matches. No fixture was invented: the delta
fixture is the trimmed live response.
