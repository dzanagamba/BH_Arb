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
        if base_url:
            self.base_url = base_url.rstrip("/")
        else:
            self.base_url = os.getenv(
                "AI_BASE_URL", "https://api.openai.com/v1"
            ).rstrip("/")
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
