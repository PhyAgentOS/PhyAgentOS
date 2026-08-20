"""Stateless model-backed semantic verification."""

from __future__ import annotations

import asyncio
import json
from typing import Any


class VerificationEngine:
    def __init__(self, *, provider: Any, model: str, timeout_s: float = 180.0) -> None:
        self.provider = provider
        self.model = model
        self.timeout_s = float(timeout_s)

    async def complete(self, *, system_prompt: str, content: list[dict[str, Any]]) -> dict:
        response = await asyncio.wait_for(
            self.provider.chat_with_retry(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": content},
                ],
                model=self.model,
                tools=None,
                temperature=0.0,
            ),
            timeout=self.timeout_s,
        )
        if response.finish_reason == "error" or not response.content:
            raise RuntimeError(response.content or "verifier model returned no content")
        value = json.loads(response.content)
        if not isinstance(value, dict):
            raise ValueError("verifier response must be a JSON object")
        return value
