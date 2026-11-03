# Bookmaker feed status — 2026-11-03

Produced by `python scripts/probe_feeds.py --books evlbet,betole --timeout 120`.
The probe runs the real scraper and reports matches, market types and errors.

| Book | Enabled | Matches | Markets published | Error |
|---|---|---:|---|---|
| Betole | yes | 1,239 | 1x2 (1,238), BTTS (1,231), first-half 1x2 (1,239), O/U 2.5 (1,239) | none |
| EVLBet | no | 0 | none | none |

EVLBet's zero is an evidence-backed absence, not a silent omission: its feed
returned no football events in this probe. It remains disabled and should be
re-probed before re-enabling. Betole's kickoff and Betradar-id fixes are what
made its 1,239 listings usable; it is enabled.

Run the probe again after a feed change or before adding a book. The 9-book
prematch scan remains the source for the other books' counts.
