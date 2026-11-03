# BH_Arb

Independent arbitrage research project for the Bosnian betting market.

This repository is intentionally standalone. It does not reuse code, data or
configuration from any other project.

## Status

Early scaffold. The package exposes a CLI entry point and a smoke test; the
scanner, bookmaker adapters and pricing engine will be built here from scratch.

## Layout

```text
BH_Arb/
├── src/bh_arb/          # application package
│   ├── __init__.py
│   └── __main__.py      # `python -m bh_arb`
├── tests/               # test suite
├── docs/                # design notes
├── pyproject.toml
└── README.md
```

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
python -m bh_arb
pytest
```

## Scope

- Prematch arbitrage across bookmakers that publish machine-readable football
  offers.
- Explicit, testable identity resolution for teams, leagues and markets.
- No hidden manual approval step in the path to a shown opportunity.

## License

No license has been chosen yet. Treat the repository as private and
all-rights-reserved until a license is added.
