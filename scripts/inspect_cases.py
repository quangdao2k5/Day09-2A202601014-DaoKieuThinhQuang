"""Print a compact, secret-free distribution of generated case results."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    outputs = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted((root / "output").glob("EC_*.json"))
    ]
    print("cases", len(outputs))
    print("primary", dict(Counter(row["case_assessment"]["primary_issue"] for row in outputs)))
    print("status", dict(Counter(row["case_assessment"]["case_status"] for row in outputs)))
    print("refund_total_brl", round(sum(row["financial_resolution"]["recommended_refund_brl"] for row in outputs), 2))


if __name__ == "__main__":
    main()
