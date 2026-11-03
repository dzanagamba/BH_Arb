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


class RawResponseAI(MatchAI):
    def __init__(self, response):
        super().__init__(api_key="test", base_url="http://test", model="test")
        self.response = response

    async def _chat(self, messages, temperature=0.0):
        return self.response


class FakeResponse:
    def __init__(self, content):
        self.content = content

    def raise_for_status(self):
        pass

    def json(self):
        return {"choices": [{"message": {"content": self.content}}]}


class RecordingClient:
    def __init__(self, content="{}", **kwargs):
        self.content = content
        self.kwargs = kwargs
        self.closed = False
        self.post_calls = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        await self.aclose()

    async def post(self, url, headers, json):
        self.post_calls += 1
        return FakeResponse(self.content)

    async def aclose(self):
        self.closed = True


@pytest.mark.parametrize("content", ["null", "[]", "42", '"not an object"'])
def test_suggest_pairs_rejects_non_object_json(content):
    ai = RawResponseAI(content)
    assert run(ai.suggest_pairs([{"a": "x", "b": "y"}])) == []


def test_suggest_pairs_degrades_for_non_serializable_input():
    ai = FakeAI([])
    assert run(ai.suggest_pairs([{"a": {"x", "y"}, "b": "z"}])) == []


def test_unavailable_suggest_pairs_never_calls_chat():
    class ChatSpyAI(MatchAI):
        def __init__(self):
            super().__init__(api_key="", base_url="http://test", model="test")
            self.chat_calls = 0

        async def _chat(self, messages, temperature=0.0):
            self.chat_calls += 1
            return "{}"

    ai = ChatSpyAI()
    assert run(ai.suggest_pairs([{"a": "x", "b": "y"}])) == []
    assert ai.chat_calls == 0


@pytest.mark.parametrize("confidence", [-0.1, 1.1])
def test_suggest_pairs_rejects_out_of_range_confidence(confidence):
    ai = FakeAI([{"a": "x", "b": "y", "same_event": True,
                  "confidence": confidence, "reason": "out of range"}])
    assert run(ai.suggest_pairs([{"a": "x", "b": "y"}])) == []


def test_suggest_pairs_caps_proposals_to_submitted_pair_count():
    ai = FakeAI([
        {"a": "x", "b": "y", "same_event": True, "confidence": 0.8, "reason": "one"},
        {"a": "x", "b": "z", "same_event": True, "confidence": 0.7, "reason": "two"},
        {"a": "x", "b": "w", "same_event": True, "confidence": 0.6, "reason": "three"},
    ])
    out = run(ai.suggest_pairs([{"a": "x", "b": "y"}]))
    assert len(out) == 1


def test_default_chat_passes_ssl_verification_setting(monkeypatch):
    import engine.ai as ai_module
    from config.settings import VERIFY_SSL

    created = []

    class Client(RecordingClient):
        def __init__(self, **kwargs):
            super().__init__("{}", **kwargs)
            created.append(self)

    monkeypatch.setattr(ai_module.httpx, "AsyncClient", Client)
    ai = MatchAI(api_key="test", base_url="http://test", model="test")
    assert run(ai._chat([{"role": "user", "content": "x"}])) == "{}"
    assert created[0].kwargs.get("verify") is VERIFY_SSL


def test_injected_client_has_lifecycle_seam():
    client = RecordingClient(content='{"proposals": []}')

    async def exercise():
        ai = MatchAI(api_key="test", base_url="http://test", model="test", client=client)
        async with ai:
            await ai.suggest_pairs([{"a": "x", "b": "y"}])

    run(exercise())
    assert client.post_calls == 1
    assert client.closed is True


def test_shared_client_serves_every_call_and_aclose_closes_it(monkeypatch):
    """A batch of N calls must cost one TLS handshake, not N."""
    import engine.ai as ai_module
    from config.settings import VERIFY_SSL

    created = []

    class Client(RecordingClient):
        def __init__(self, **kwargs):
            super().__init__('{"proposals": []}', **kwargs)
            created.append(self)

    monkeypatch.setattr(ai_module.httpx, "AsyncClient", Client)

    async def exercise():
        shared = MatchAI(
            api_key="test", base_url="http://test", model="test"
        ).with_shared_client()
        await shared.suggest_pairs([{"a": "x", "b": "y"}])
        await shared.suggest_pairs([{"a": "x", "b": "z"}])
        await shared.aclose()

    run(exercise())
    assert len(created) == 1
    assert created[0].post_calls == 2
    assert created[0].closed is True
    assert created[0].kwargs.get("verify") is VERIFY_SSL
    assert created[0].kwargs.get("timeout") == 10.0


def test_shared_client_keeps_the_configured_endpoint(monkeypatch):
    import engine.ai as ai_module

    monkeypatch.setattr(ai_module.httpx, "AsyncClient", RecordingClient)
    shared = MatchAI(
        api_key="test", base_url="https://example.test/v1/", model="m1", timeout=3.0
    ).with_shared_client()

    assert shared.api_key == "test"
    assert shared.base_url == "https://example.test/v1"
    assert shared.model == "m1"
    assert shared.timeout == 3.0
    assert shared.available is True
    run(shared.aclose())
