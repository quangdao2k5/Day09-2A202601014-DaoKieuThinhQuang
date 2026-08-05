"""Fresh-run JSONL A2A trace logging."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import MODEL_NAME, MODEL_PARAMETER_BILLION


class TraceLogger:
    def __init__(self, path: Path, run_id: str) -> None:
        self.path = path
        self.run_id = run_id
        self.sequence = 0
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")

    def emit(
        self,
        event: str,
        *,
        case_id: str | None = None,
        agent: str | None = None,
        recipient: str | None = None,
        payload: dict[str, Any] | None = None,
        model_used: bool = False,
        duration_ms: float | None = None,
    ) -> None:
        self.sequence += 1
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "run_id": self.run_id,
            "sequence": self.sequence,
            "event": event,
            "case_id": case_id,
            "agent": agent,
            "recipient": recipient,
            "configured_model": MODEL_NAME,
            "model_parameter_billion": MODEL_PARAMETER_BILLION,
            "model_used": model_used,
            "duration_ms": None if duration_ms is None else round(duration_ms, 2),
            "payload": payload or {},
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
