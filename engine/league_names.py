"""League-name taxonomy shared by the learner, matcher and resolver.

A generic name is too vague to be a hard league gate on its own ("Bundesliga"
exists in Germany and Austria, "1. liga" in a dozen countries). The name still
belongs in a team-set fingerprint: the teams that actually play under it are
what disambiguates it per fixture.
"""

from __future__ import annotations

GENERIC_LEAGUES = frozenset({
    "football", "fudbal", "soccer", "unknown_league", "", "2.liga", "2. liga", "3.liga", "3. liga",
    "kup", "klubovi", "1.liga", "1. liga", "superliga", "super liga",
    "prijateljske", "prijateljske utakmice", "prijateljske klubske",
    "world club friendly", "club friendly", "klubovi prijateljski",
    "elitne prijateljske", "friendlies",
    # Ambiguous short names without country — treat as generic to avoid false hard rejects
    # (e.g. "Premier Liga" appears for both BIH and ENG; country gate + teams decide)
    "premier liga", "premijer liga", "premier league",
    "bundesliga", "prva liga", "vtora liga",
})
