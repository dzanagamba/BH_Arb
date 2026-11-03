"""Hosted-AI adapter for match ambiguity. Proposals only — never approvals."""

import json
import logging
import os
from dataclasses import dataclass
from types import TracebackType

import httpx

from config.settings import VERIFY_SSL

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
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else os.getenv("AI_API_KEY", "")
        if base_url:
            self.base_url = base_url.rstrip("/")
        else:
            self.base_url = os.getenv(
                "AI_BASE_URL", "https://api.openai.com/v1"
            ).rstrip("/")
        self.model = model or os.getenv("AI_MODEL", "gpt-4o-mini")
        self.timeout = timeout
        self._client = client

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def with_shared_client(self) -> "MatchAI":
        """Return a copy that reuses one HTTP client for all of its calls.

        The default path builds an ``httpx.AsyncClient`` per call, so a batch of
        N calls pays N TLS handshakes and leaves ``aclose()`` nothing to close.
        The caller owns the returned adapter and must close it.
        """
        return MatchAI(
            api_key=self.api_key,
            base_url=self.base_url,
            model=self.model,
            timeout=self.timeout,
            client=httpx.AsyncClient(timeout=self.timeout, verify=VERIFY_SSL),
        )

    async def _chat(self, messages: list[dict], temperature: float = 0.0) -> str:
        if self._client is not None:
            return await self._chat_with_client(self._client, messages, temperature)
        async with httpx.AsyncClient(
            timeout=self.timeout, verify=VERIFY_SSL
        ) as client:
            return await self._chat_with_client(client, messages, temperature)

    async def _chat_with_client(
        self,
        client: httpx.AsyncClient,
        messages: list[dict],
        temperature: float,
    ) -> str:
        resp = await client.post(
            f"{self.base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
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

    async def aclose(self) -> None:
        """Close an injected client; default per-call clients close themselves."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> "MatchAI":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def suggest_pairs(self, pairs: list[dict]) -> list[PairProposal]:
        if not self.available or not pairs:
            return []
        try:
            messages = [
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": json.dumps(pairs, ensure_ascii=False)},
            ]
            raw = await self._chat(messages)
            data = json.loads(raw)
            if not isinstance(data, dict):
                return []
            proposals = data.get("proposals", [])
            if not isinstance(proposals, list):
                return []
            out: list[PairProposal] = []
            for p in proposals:
                if not isinstance(p, dict):
                    continue
                try:
                    confidence = float(p["confidence"])
                    if not 0.0 <= confidence <= 1.0:
                        continue
                    out.append(PairProposal(
                        match_a_book=str(p["a"]), match_b_book=str(p["b"]),
                        same_event=bool(p["same_event"]), confidence=confidence,
                        reason=str(p.get("reason", "")),
                        suggested_alias=p.get("alias"),
                        suggested_league_equivalence=p.get("league_equiv"),
                    ))
                except (KeyError, TypeError, ValueError):
                    continue
                if len(out) >= len(pairs):
                    break
            return out
        except Exception as e:
            logger.warning("AI suggest_pairs failed: %s", e)
            return []
