# Surebet Scanner — Muse 12 🎯

> **Working repo:** `surebetmuse12` (fresh fork of `dzanagamba/surebet-scanner` @ `7d2d5d8`). See `PLAN.md` for the full P0→P3 roadmap to fix “rare + wrong” surebets.

A web-based arbitrage betting detection tool for the Bosnian market.

## What it does

1. Scrapes football odds from 9 Bosnian bookmakers (Mozzartbet, MDShop, Admiralbet, MBet, SportPlus, EVLBet, Premier Kladionica and WWIN active; Betole disabled by default)
2. Normalizes team/league names (handling Bosnian diacritics, Cyrillic, phonetic transliterations)
3. Matches the same real-world events across bookmakers using multi-dimensional fingerprinting (with home/away swap detection)
4. Detects arbitrage (surebet) opportunities where odds guarantee a profit regardless of match outcome (enforcing strict 1-bet-per-bookmaker rule)
5. Supports two scan modes — **Future Matches** (prematch) and **Live Matches** (in-play) — with a dashboard toggle, per-mode caching, and per-mode history
6. Displays results in a premium dark-themed web dashboard

## Setup

### Prerequisites
- Python 3.11+
- pip

### Install

```bash
cd surebet

# Create virtual environment
python -m venv venv

# Activate (Windows)
venv\Scripts\activate

# Activate (Linux/Mac)
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Install Playwright browsers
playwright install chromium
```

### Run

```bash
python main.py
```

- **Dashboard**: http://localhost:8000
- **API Docs**: http://localhost:8000/docs
- **Health Check**: http://localhost:8000/api/health

## Configuration

Edit `config/settings.py` (or `.env`) to change:
- `HEADLESS` — `True` for background browser execution (default), or `False` to view browser windows (useful if CAPTCHA solving is required)
- `VERIFY_SSL` — `True` to enforce TLS certificate verification on direct httpx API calls (default `False`)
- `MIN_PROFIT_PERCENT` — Minimum profit % to show as a surebet (default: 0.5%)
- `KICKOFF_WINDOW_MINUTES` — Max kickoff time difference to group matches (default: 120)
- `DEFAULT_INVESTMENT` — Default total investment for stake calculation (default: 100 BAM)
- Bookmaker `enabled` status — Toggle individual bookmakers ON/OFF via config or the web UI

## Development

```bash
# Run the test suite
python -m pytest

# Lint / type check
python -m ruff check .
python -m mypy .
```

## Adding more leagues/teams

- Edit `config/league_mappings.json` to add new league name variations
- Edit `config/team_mappings.json` to add new team name variations

## Notes

- Mozzartbet and Admiralbet run hybrid Playwright sessions to bypass Cloudflare protection and fetch live API data
- Direct HTTP scrapers (MDShop, MBet, SportPlus, EVLBet, and Betole's prematch feed) fetch API data directly without browser overhead
- Betole is disabled (`"enabled": False`) by default to save system resources
- All odds are displayed as European decimal odds
- Stakes are calculated for the configured `DEFAULT_INVESTMENT` and can be adjusted live in the dashboard (with optional rounding to whole KM)
- Last scan results are cached to `cache/last_scan.json` and restored on startup
- Verified football market mappings and deliberately excluded offers are documented in `MARKET_MAPPING.md`
