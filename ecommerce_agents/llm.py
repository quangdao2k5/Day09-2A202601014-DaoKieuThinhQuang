"""Read-only small-model audit client.

The LLM may report concerns but cannot mutate deterministic case outputs.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from .config import MODEL_NAME, OPENROUTER_URL


class OpenRouterAuditor:
    def __init__(self) -> None:
        self.api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def audit(self, case_output: dict[str, Any]) -> dict[str, Any]:
        if not self.api_key:
            raise RuntimeError("OPENROUTER_API_KEY is missing; add it to .env")
        prompt = (
            "Audit this EC_POLICY_V2 case output for internal consistency only. "
            "The numeric facts were produced by deterministic tools and must not be changed. "
            "Return JSON with status='approved' unless you see a schema inconsistency, and a "
            "reason of at most 20 words.\nOUTPUT:\n"
            + json.dumps(case_output, ensure_ascii=False, separators=(",", ":"))
        )
        body = {
            "model": MODEL_NAME,
            "messages": [
                {
                    "role": "system",
                    "content": "You are a read-only verifier. Output one compact JSON object. /no_think",
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.0,
            "max_tokens": 100,
            "response_format": {"type": "json_object"},
            "reasoning": {"enabled": False},
        }
        request = urllib.request.Request(
            OPENROUTER_URL,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/",
                "X-Title": "Olist Dispute Multi-Agent Lab",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise RuntimeError(f"OpenRouter HTTP {exc.code}: {detail}") from exc
        content = payload["choices"][0]["message"]["content"]
        try:
            audit = json.loads(content)
        except json.JSONDecodeError:
            audit = {"status": "unparseable", "reason": content[:200]}
        return {
            "audit": audit,
            "request_id": payload.get("id"),
            "usage": payload.get("usage", {}),
            "model": payload.get("model", MODEL_NAME),
        }
