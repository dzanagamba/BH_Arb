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
