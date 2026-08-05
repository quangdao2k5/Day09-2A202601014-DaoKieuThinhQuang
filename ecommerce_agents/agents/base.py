"""Common agent result contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AgentResult:
    output: dict[str, Any]
    facts: dict[str, Any]
