# Mozzartbet omits `value` on an unpriced pick (SR4-10)

**Measured:** 2026-11-08, operator host, one live `POST /betting/match/{id}`
response plus the `POST /betting/matches` list page.

## What the feed does

`MozzartOdd` required `game`, `subgame` and `value`, with `value` allowed to be
`null`. On 2026-11-08 the live offer sent **no `value` key at all** on an
unpriced pick, so the strict schema failed with
`offer schema drift at match.odds.14.value: Field required` and the whole book
dropped (0 matches).

One offer, 518 rows:

| rows | count |
|---|---|
| with a numeric `value` | 413 |
| without a `value` key | 105 |
| with `value: null` | 0 |

The 105 rows are otherwise identical to the priced rows: same key set minus
`value`, `specialOddValue: "-1"` on both, `priority`/`topOdd` false. There is no
second price field. A row without `value` is a suspended pick, not drift:

```json
{
  "id": 1001003009,
  "subgame": {"name": "2+p.p.", "description": "Zbir golova na poluvremenu će biti najmanje 2"},
  "game": {"id": 3, "name": "Ukupno golova", "specialOddValueType": "NONE"},
  "specialOddValue": "-1",
  "priority": false,
  "topOdd": false
}
```

Unpriced rows also appear in supported families (5 rows in game 3, one in 130),
not only in the excluded combinations.

## Fix

- `MozzartOdd.value` is now optional (`float | None = None`); `game` and
  `subgame` stay required and a string/boolean price is still schema drift.
- `validate_mozzart_page()` adds one book-level guard: if a list page carries
  odds rows and **none** of them has a numeric `value`, the price field was
  renamed or removed and the book is `schema_drift`. One suspended row, or one
  fully suspended offer, is accepted.
- The parser already skipped a row whose price is missing (`value` falsy →
  `0.0` → below the 1.01 floor), so no leg is ever emitted without a price; a
  market missing a leg still fails its `min_legs` check.

## Measured before → after

| probe | matches | markets |
|---|---|---|
| before (schema drift) | 0 | 0 |
| after (2026-11-08, same command) | 603 | 4,698 |

Families after: 1x2 603, double_chance 597, btts 590, over_under_1_5 579,
over_under_2_5 603, over_under_3_5 591, over_under_4_5 553, first_half_1x2 582.
`scripts/probe_feeds.py --books mozzartbet --timeout 300`, 28.8 s.
