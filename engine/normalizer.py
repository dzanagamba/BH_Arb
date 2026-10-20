"""
Team and League Name Normalizer

6-Stage Pipeline:
  1. Clean       — lowercase, strip, collapse whitespace, remove quotes
  2. Cyrillic    — Serbian Cyrillic → Latin transliteration
  3. Diacritics  — ž→z, č→c, š→s, ü→u, etc.
  4. Phonetic    — Bosnian phonetic overrides ("Čelzi" → "chelsea")
  5. Prefix strip — Remove FK, FC, NK, etc.
  6. Lookup      — Exact match in reverse map → canonical ID
     Fuzzy       — rapidfuzz fallback if no exact match (score ≥ 85)
"""

import json
import logging
import os
import re
import unicodedata

from rapidfuzz import fuzz, process

logger = logging.getLogger(__name__)

MAPPINGS_DIR = os.path.join(os.path.dirname(__file__), "..", "config")
TEAM_MAPPINGS_FILE = os.path.join(MAPPINGS_DIR, "team_mappings.json")
LEAGUE_MAPPINGS_FILE = os.path.join(MAPPINGS_DIR, "league_mappings.json")


# ---------------------------------------------------------------------------
# Transliteration tables
# ---------------------------------------------------------------------------

LATIN_DIACRITICS: dict[str, str] = {
    # Bosnian/Croatian/Serbian
    'č': 'c', 'ć': 'c', 'đ': 'dj', 'š': 's', 'ž': 'z',
    'Č': 'C', 'Ć': 'C', 'Đ': 'Dj', 'Š': 'S', 'Ž': 'Z',
    # German
    'ä': 'a', 'ö': 'o', 'ü': 'u', 'Ä': 'A', 'Ö': 'O', 'Ü': 'U', 'ß': 'ss',
    # Spanish/Portuguese
    'ñ': 'n', 'á': 'a', 'é': 'e', 'í': 'i', 'ó': 'o', 'ú': 'u',
    'Á': 'A', 'É': 'E', 'Í': 'I', 'Ó': 'O', 'Ú': 'U', 'Ñ': 'N',
    # French/Italian
    'à': 'a', 'è': 'e', 'ì': 'i', 'ò': 'o', 'ù': 'u',
    'â': 'a', 'ê': 'e', 'î': 'i', 'ô': 'o', 'û': 'u',
    'ë': 'e', 'ï': 'i',
    # Scandinavian
    'ø': 'o', 'å': 'a', 'æ': 'ae', 'Ø': 'O', 'Å': 'A', 'Æ': 'AE',
    # Turkish
    'ğ': 'g', 'ı': 'i', 'Ğ': 'G', 'İ': 'I',
}

CYRILLIC_TO_LATIN: dict[str, str] = {
    'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'ђ': 'dj',
    'е': 'e', 'ж': 'z', 'з': 'z', 'и': 'i', 'ј': 'j', 'к': 'k',
    'л': 'l', 'љ': 'lj', 'м': 'm', 'н': 'n', 'њ': 'nj', 'о': 'o',
    'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'ћ': 'c', 'у': 'u',
    'ф': 'f', 'х': 'h', 'ц': 'c', 'ч': 'c', 'џ': 'dz', 'ш': 's',
    # uppercase
    'А': 'A', 'Б': 'B', 'В': 'V', 'Г': 'G', 'Д': 'D', 'Ђ': 'Dj',
    'Е': 'E', 'Ж': 'Z', 'З': 'Z', 'И': 'I', 'Ј': 'J', 'К': 'K',
    'Л': 'L', 'Љ': 'Lj', 'М': 'M', 'Н': 'N', 'Њ': 'Nj', 'О': 'O',
    'П': 'P', 'Р': 'R', 'С': 'S', 'Т': 'T', 'Ћ': 'C', 'У': 'U',
    'Ф': 'F', 'Х': 'H', 'Ц': 'C', 'Ч': 'C', 'Џ': 'Dz', 'Ш': 'S',
}

PHONETIC_OVERRIDES: dict[str, str] = {
    "mancester junajted": "manchester united",
    "mancester siti": "manchester city",
    "celzi": "chelsea",
    "njukasl": "newcastle",
    "liverpul": "liverpool",
    "bajern minhen": "bayern munchen",
    "barselona": "barcelona",
    "atletiko madrid": "atletico madrid",
    "pari sen zermen": "paris saint germain",
    "juventus torino": "juventus",
    "lacio": "lazio",
    "dortmund": "borussia dortmund",
    "lajpcig": "rb leipzig",
    "arsenal london": "arsenal",
    "crvena zvezda": "red star belgrade",
    "zvezda": "red star belgrade",
}

# Club type designators — stripped from prefixes and suffixes
CLUB_DESIGNATORS: set[str] = {
    "fk", "fc", "nk", "hšk", "hsk", "sc", "sk", "bk", "if",
    "gnk", "rnk", "hnk", "ofk", "tsc", "rfk", "ask", "bsc",
    "afc", "ssc", "acf", "us", "as", "og", "cd", "cf", "ca",
    "rc", "rcd", "ud", "sd", "sp", "ss", "cs", "deportivo", "atletico",
    # Swedish / Austrian / German suffixes observed on WWIN/Sportplus/MDShop (vision 2026-08-20)
    "aif", "sv", "rb", "vfb", "tsg", "ssv", "ksv", "asv", "ev", "osk",
    "wac", "skn", "scr", "aks",
    "ac", "cfc", "bfc", "rfc", "vfl", "fsv", "ssg", "usc", "tss",
}

# Patterns for special categories (also used by base scraper)
AGE_GROUP_PATTERN = re.compile(
    r'\b(U-?\d{2}|Under[\s-]?\d{2}|Omladinci|Kadeti|Juniori|Pioniri)\b',
    re.IGNORECASE,
)
RESERVE_PATTERN = re.compile(
    r'\b(Rezerve|Reserves?|II\b|B\s*tim|2nd|Drugi?\s*tim)\b',
    re.IGNORECASE,
)
# 'W' alone is a women's marker only when NOT followed by a letter — avoids
# false positives on clubs like "W Connection" (Trinidad men's club).
WOMEN_PATTERN = re.compile(
    r'\b(Žene|Ženski|Women|Ladies)\b|(?:\bW\b)(?!\s*[A-Za-z])',
    re.IGNORECASE,
)
ESPORTS_PATTERN = re.compile(
    r'\b(SRL|Simulated Reality|Esoccer|Cyber|E-?sports?|Virtual)\b',
    re.IGNORECASE,
)


class TeamNormalizer:
    """
    Multi-stage team/league name normalizer for the Bosnian betting market.

    Handles:
    - Bosnian/Croatian/Serbian diacritics (č, ć, đ, š, ž)
    - Serbian Cyrillic → Latin transliteration
    - Bosnian phonetic transliterations of foreign names ("Čelzi" → "chelsea")
    - Club prefix stripping (FK, FC, NK, etc.)
    - Neutral venue markers (N)
    - Known mapping lookup + fuzzy fallback
    """

    def __init__(self):
        self.team_mappings: dict[str, list[str]] = {}
        self.team_reverse_map: dict[str, str] = {}   # cleaned_variation → canonical_id
        self.league_mappings: dict[str, list[str]] = {}
        self.league_reverse_map: dict[str, str] = {}  # cleaned_variation → canonical_id
        self.country_reverse_map: dict[str, str] = {}
        self._load_mappings()

    def _load_mappings(self) -> None:
        """Load all mapping JSON files and build reverse indices."""
        # Team mappings
        if os.path.exists(TEAM_MAPPINGS_FILE):
            with open(TEAM_MAPPINGS_FILE, encoding="utf-8") as f:
                self.team_mappings = json.load(f)
            count = 0
            for canonical_id, variations in self.team_mappings.items():
                if canonical_id.startswith("_"):
                    continue
                for name in variations:
                    cleaned = self._full_clean(name)
                    self.team_reverse_map[cleaned] = canonical_id
                    count += 1
            logger.info(f"Loaded {len(self.team_mappings)} team mappings ({count} variations)")
        else:
            logger.warning(f"team_mappings.json not found at {TEAM_MAPPINGS_FILE}")

        # League mappings
        if os.path.exists(LEAGUE_MAPPINGS_FILE):
            with open(LEAGUE_MAPPINGS_FILE, encoding="utf-8") as f:
                self.league_mappings = json.load(f)
            count = 0
            for canonical_id, variations in self.league_mappings.items():
                if canonical_id.startswith("_"):
                    continue
                for name in variations:
                    cleaned = self._league_clean(name)
                    self.league_reverse_map[cleaned] = canonical_id
                    count += 1
            logger.info(f"Loaded {len(self.league_mappings)} league mappings ({count} variations)")
        else:
            logger.warning(f"league_mappings.json not found at {LEAGUE_MAPPINGS_FILE}")

    # -------------------------------------------------------------------------
    # Cleaning stages
    # -------------------------------------------------------------------------

    def _clean(self, name: str) -> str:
        """Stage 1: lowercase, strip, collapse whitespace, remove quotes."""
        name = str(name).strip().lower()
        name = re.sub(r'\s+', ' ', name)
        name = re.sub(r'[""„"\'`]', '', name)
        return name

    def _cyrillic_to_latin(self, name: str) -> str:
        """Stage 2: Convert Cyrillic characters to Latin equivalents."""
        result = []
        for char in name:
            mapped = CYRILLIC_TO_LATIN.get(char)
            if mapped:
                result.append(mapped.lower())
            else:
                result.append(char)
        return ''.join(result)

    def _remove_diacritics(self, name: str) -> str:
        """Stage 3: Remove diacritics (ž→z, č→c, š→s, ü→u, etc.)."""
        for diacritic, replacement in LATIN_DIACRITICS.items():
            name = name.replace(diacritic.lower(), replacement.lower())
        # Final unicode normalization for anything missed
        nfkd = unicodedata.normalize('NFKD', name)
        return ''.join(c for c in nfkd if not unicodedata.combining(c))

    def _apply_phonetic_overrides(self, name: str) -> str:
        """Stage 4: Apply Bosnian phonetic transliteration overrides."""
        return PHONETIC_OVERRIDES.get(name, name)

    def _strip_club_designators(self, name: str) -> str:
        """Stage 5: Remove common club prefix/suffix designators (FK, FC, etc.)."""
        MULTI_PREFIXES = ["club deportivo", "club sportivo", "club atletico"]
        for prefix in MULTI_PREFIXES:
            if name.startswith(prefix + " "):
                name = name[len(prefix) + 1:].strip()
                break

        # Dotted abbreviations like "R.B. Salzburg" -> "rb salzburg" -> strip "rb"
        # and "Univ.Craiova" -> "univ craiova" (dot between words without space)
        # Remove dots between letters before splitting, keep dot in "1. liga" leagues
        # but for teams we can safely turn "r.b." -> "rb ".
        # This is team-specific; league names keep dots via separate path.
        # Here we normalize dotted team tokens: "r.b." -> "rb" and "univ.craiova" -> "univ craiova"
        name = re.sub(r"\b([a-z]\.)+", lambda m: m.group(0).replace(".", "") + " ", name)
        # General dot between word characters without space (e.g. "Univ.Craiova" -> "Univ Craiova")
        name = re.sub(r"(?<=[a-z])\.(?=[a-z])", " ", name, flags=re.IGNORECASE)
        # Trailing abbreviation dot (e.g. "Univ. Craiova" -> "Univ Craiova", "Lech P." -> "Lech P")
        name = re.sub(r"(?<=[a-z])\.(?=\s|$)", " ", name, flags=re.IGNORECASE)
        name = re.sub(r"\s+", " ", name).strip()

        words = name.split()
        if not words:
            return name

        # Strip leading designator (repeated, e.g. "fc salzburg")
        while len(words) > 1 and words[0] in CLUB_DESIGNATORS:
            words = words[1:]
        # Strip trailing designator (repeated, e.g. "kapfenberg sv", "mjallby aif")
        while len(words) > 1 and words[-1] in CLUB_DESIGNATORS:
            words = words[:-1]
        # Also strip dotted combos left as single token like "rb" after dot removal
        # and handle "lillestrom" vs "lillestrom" already clean

        return ' '.join(words) if words else name

    def _strip_neutral_venue(self, name: str) -> str:
        """Remove neutral venue indicators like (N), [N], (n)."""
        return re.sub(r'\s*[\(\[]n[\)\]]\s*', ' ', name, flags=re.IGNORECASE).strip()

    def _league_clean(self, name: str) -> str:
        """Clean a competition name: like a team name, minus club designators.

        Stripping "AFC"/"FC" is right for clubs and wrong for competitions:
        "AFC Champions League" became "champions league" and resolved to UEFA's.
        """
        name = self._remove_diacritics(self._cyrillic_to_latin(self._clean(name)))
        return self._strip_neutral_venue(name).strip()

    def _full_clean(self, name: str) -> str:
        """Run all cleaning stages to produce a normalized string."""
        name = self._clean(name)
        name = self._cyrillic_to_latin(name)
        name = self._remove_diacritics(name)
        name = self._apply_phonetic_overrides(name)
        name = self._strip_club_designators(name)
        name = self._strip_neutral_venue(name)
        return name.strip()

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    def normalize_team(self, name: str, league_scope: str = "") -> str:
        """
        Normalize a team name to a canonical ID.

        Returns canonical team ID if found in mappings,
        otherwise returns cleaned name as fallback.
        """
        if not name:
            return ""

        # Stage 1-5: full clean
        cleaned = self._full_clean(name)

        # Stage 6: exact lookup (post-strip)
        if cleaned in self.team_reverse_map:
            return self.team_reverse_map[cleaned]

        # Also try with prefix still attached (e.g. "fk sarajevo")
        cleaned_with_prefix = self._remove_diacritics(
            self._cyrillic_to_latin(self._clean(name))
        )
        if cleaned_with_prefix in self.team_reverse_map:
            return self.team_reverse_map[cleaned_with_prefix]

        # Stage 7: fuzzy fallback (score ≥ 85)
        if self.team_reverse_map:
            candidates = list(self.team_reverse_map.keys())
            result = process.extractOne(
                cleaned,
                candidates,
                scorer=fuzz.token_sort_ratio,
                score_cutoff=85,
            )
            if result:
                matched_name, score, _ = result
                canonical = self.team_reverse_map.get(matched_name, matched_name)
                logger.debug(
                    f"Fuzzy team match: '{name}' → '{canonical}' "
                    f"(via '{matched_name}', score={score})"
                )
                return canonical

        # Fallback: return cleaned name
        return cleaned

    # Ambiguous short names that must stay generic (vision 2026-08-20: "Premier Liga" maps to both BIH and ENG)
    GENERIC_LEAGUE_RAW = {
        "premier liga", "premijer liga", "premier league",
        "super liga", "superliga",
        "1. liga", "1.liga", "2. liga", "2.liga", "3. liga", "3.liga",
        "kup", "klubovi", "fudbal", "football", "soccer",
        # Added after live leak analysis 2026-08-20: short names ambiguous across countries
        "bundesliga", "prva liga",
    }

    def normalize_league(self, league_name: str) -> str:
        """Normalize a league name to its canonical ID."""
        if not league_name:
            return ""

        cleaned = self._league_clean(league_name)

        # Keep ambiguous/vague league strings generic — prevents false hard rejects
        # on short names like "Premier Liga" that appear for both BIH and ENG fixtures.
        # Qualified variants like "BIH Premijer Liga" or "Engleska 1" map via exact lookup below.
        if cleaned in self.GENERIC_LEAGUE_RAW:
            return cleaned

        # Exact lookup
        if cleaned in self.league_reverse_map:
            return self.league_reverse_map[cleaned]

        # No fuzzy fallback: a near-miss league name is a different competition
        # as often as not ("Liga Prvaka" scored 90 against Slovenia's "Prva
        # Liga", "Parva Liga" — Bulgaria — 95). An unmapped name stays
        # unmapped; the gate settles it on exact teams, and
        # scripts/derive_mappings.py maps it from shared fixtures.
        return cleaned

    def normalize_country(self, country_name: str) -> str:
        """Normalize a country name to its canonical ID."""
        if not country_name:
            return ""
        cleaned = self._full_clean(country_name)
        return self.country_reverse_map.get(cleaned, cleaned)

    def detect_special_category(self, text: str) -> list[str]:
        """Detect if text contains age-group/reserve/women's/esports markers."""
        tags = []
        if ESPORTS_PATTERN.search(text):
            tags.append("Esports")
        if AGE_GROUP_PATTERN.search(text):
            age_match = re.search(r'U-?(\d{2})', text, re.IGNORECASE)
            tags.append(f"U{age_match.group(1)}" if age_match else "Youth")
        if RESERVE_PATTERN.search(text):
            tags.append("Reserve")
        if WOMEN_PATTERN.search(text):
            tags.append("Women")
        return tags
