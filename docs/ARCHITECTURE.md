# Architecture

BH_Arb is a standalone project. The design keeps four boundaries explicit so
each can be tested without the others.

## 1. Ingestion

One adapter per bookmaker. An adapter returns normalized offers and never
decides whether two offers refer to the same event.

## 2. Identity resolution

Teams, leagues and markets are matched through deterministic rules plus a
persisted evidence ledger. Every accepted pairing must be explainable from the
evidence that produced it.

## 3. Pricing

Only verified event groups are priced. The engine returns the stake split, the
worst-case return and the profit margin for a requested total stake.

## 4. Presentation

A read-only dashboard over the latest scan. It must never be able to change the
trust state of a pairing.

## Non-goals

- No copied code, fixtures or configuration from other repositories.
- No human approval in the path to a displayed opportunity.
- No betting execution until the scanner and its evidence are stable.
