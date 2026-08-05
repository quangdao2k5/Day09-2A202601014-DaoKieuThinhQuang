"""Shared deterministic formatting helpers."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Iterable, TypeVar

T = TypeVar("T")
CENT = Decimal("0.01")


def parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")


def hours_between(later: str | None, earlier: str | None) -> Decimal | None:
    later_dt = parse_timestamp(later)
    earlier_dt = parse_timestamp(earlier)
    if later_dt is None or earlier_dt is None:
        return None
    seconds = Decimal(str((later_dt - earlier_dt).total_seconds()))
    return (seconds / Decimal("3600")).quantize(CENT, rounding=ROUND_HALF_UP)


def money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def decimal_to_json(value: Decimal | None) -> float | None:
    return None if value is None else float(value)


def stable_unique(values: Iterable[T]) -> list[T]:
    seen: set[T] = set()
    output: list[T] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            output.append(value)
    return output


def json_digest(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
