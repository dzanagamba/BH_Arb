### Task 6: Add the hosted-AI adapter (propose-only)

**Files:**
- Create: `engine/ai.py`
- Test: `tests/test_ai_adapter.py` (create)

**Interfaces:**
- Consumes: env vars `AI_API_KEY`, `AI_BASE_URL`, `AI_MODEL`; `httpx`.
- Produces:
  - `class PairProposal` (dataclass): `match_a_book`, `match_b_book`, `same_event: bool`, `confidence: float`, `reason: str`, `suggested_alias: str | None`, `suggested_league_equivalence: list[str] | None`.
  - `class MatchAI` with `__init__(self, api_key: str | None = None, base_url: str = "https://api.openai.com/v1", model: str = "gpt-4o-mini", timeout: float = 10.0)`, `available: bool` property, `async def suggest_pairs(self, pairs: list[dict]) -> list[PairProposal]`, `async def propose_alias(self, raw: str, candidates: list[str], league: str) -> tuple[str | None, float, str]`.
  - A `FakeAI(MatchAI)` override in tests.

- [ ] **Step 1: Write the failing test**

Create `tests/test_ai_adapter.py`:

```python
"""AI adapter contract: propose-only, no auto-approval, graceful when unavailable."""
import asyncio
import json

import pytest

from engine.ai import MatchAI, PairProposal


def run(coro):
    return asyncio.run(coro)


class FakeAI(MatchAI):
    def __init__(self, proposals):
        super().__init__(api_key="test", base_url="http://test", model="test")
        self._proposals = proposals

    async def _chat(self, messages, temperature=0.0):
        return json.dumps({"proposals": self._proposals})


def test_unavailable_without_api_key():
    ai = MatchAI(api_key="", base_url="http://test", model="test")
    assert ai.available is False


def test_suggest_pairs_parses_proposals():
    ai = FakeAI([{"a": "mdshop", "b": "mbet", "same_event": True, "confidence": 0.91,
                  "reason": "same clubs, different abbreviations", "alias": None, "league_equiv": None}])
    out = run(ai.suggest_pairs([{"a": "mdshop", "b": "mbet", "home": "A", "away": "B"}]))
    assert len(out) == 1
    assert isinstance(out[0], PairProposal)
    assert out[0].same_event is True
    assert out[0].confidence == pytest.approx(0.91)


def test_proposals_never_auto_approve():
    ai = FakeAI([{"a": "mdshop", "b": "mbet", "same_event": True, "confidence": 0.99,
                  "reason": "very sure", "alias": None, "league_equiv": None}])
    out = run(ai.suggest_pairs([{"a": "mdshop", "b": "mbet", "home": "A", "away": "B"}]))
    p = out[0]
    # The adapter returns a proposal only: no approval/status concept exists on it.
    assert not hasattr(p, "approved")
    assert not hasattr(p, "status")


def test_network_failure_degrades_gracefully():
    class FailingAI(MatchAI):
        async def _chat(self, messages, temperature=0.0):
            raise RuntimeError("network down")

    ai = FailingAI(api_key="test", base_url="http://test", model="test")
    assert run(ai.suggest_pairs([{"a": "x", "b": "y"}])) == []


def test_empty_input_short_circuits():
    ai = FakeAI([])
    assert run(ai.suggest_pairs([])) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_ai_adapter.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.ai'`.

- [ ] **Step 3: Implement `engine/ai.py`**

```python
"""Hosted-AI adapter for match ambiguity. Proposals only — never approvals."""

import json
import logging
import os
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

_SYSTEM = (
    "You compare betting fixture names from different bookmakers. "
    "Return JSON only: {\"proposals\":[{\"a\":bookmaker,\"b\":bookmaker,"
    "\"same_event\":bool,\"confidence\":0..1,\"reason\":str,\"alias\":str|null,"
    "\"league_equiv\":[str,str]|null}]}. "
    "Never claim certainty. confidence<0.99 unless names are identical."
)


@dataclass
class PairProposal:
    match_a_book: str
    match_b_book: str
    same_event: bool
    confidence: float
    reason: str
    suggested_alias: str | None = None
    suggested_league_equivalence: list[str] | None = None


class MatchAI:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout: float = 10.0,
    ) -> None:
        self.api_key = api_key if api_key is not None else os.getenv("AI_API_KEY", "")
        self.base_url = (base_url or os.getenv("AI_BASE_URL", "https://api.openai.com/v1")).rstrip("/")
        self.model = model or os.getenv("AI_MODEL", "gpt-4o-mini")
        self.timeout = timeout

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    async def _chat(self, messages: list[dict], temperature: float = 0.0) -> str:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                json={
                    "model": self.model,
                    "messages": messages,
                    "temperature": temperature,
                    "response_format": {"type": "json_object"},
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]

    async def suggest_pairs(self, pairs: list[dict]) -> list[PairProposal]:
        if not self.available or not pairs:
            return []
        messages = [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": json.dumps(pairs, ensure_ascii=False)},
        ]
        try:
            raw = await self._chat(messages)
            data = json.loads(raw)
        except Exception as e:
            logger.warning("AI suggest_pairs failed: %s", e)
            return []
        out: list[PairProposal] = []
        for p in data.get("proposals", []):
            try:
                out.append(PairProposal(
                    match_a_book=str(p["a"]), match_b_book=str(p["b"]),
                    same_event=bool(p["same_event"]), confidence=float(p["confidence"]),
                    reason=str(p.get("reason", "")),
                    suggested_alias=p.get("alias"),
                    suggested_league_equivalence=p.get("league_equiv"),
                ))
            except (KeyError, TypeError, ValueError):
                continue
        return out

    async def propose_alias(self, raw: str, candidates: list[str], league: str) -> tuple[str | None, float, str]:
        if not self.available:
            return None, 0.0, "ai_unavailable"
        prompt = {"raw_team": raw, "candidates": candidates, "league": league}
        messages = [
            {"role": "system", "content": "Return JSON: {\"alias\":str|null,\"candidate\":str|null,\"confidence\":0..1,\"reason\":str}."},
            {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
        ]
        try:
            raw_resp = await self._chat(messages)
            data = json.loads(raw_resp)
            return data.get("candidate"), float(data.get("confidence", 0.0)), str(data.get("reason", ""))
        except Exception as e:
            logger.warning("AI propose_alias failed: %s", e)
            return None, 0.0, f"ai_error: {e}"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_ai_adapter.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add engine/ai.py tests/test_ai_adapter.py
git commit -m "feat(mapping): add hosted-AI adapter for pair proposals (propose-only, graceful degradation)"
```

---

