"""Payment reconciliation agent."""

from __future__ import annotations

from decimal import Decimal

from .base import AgentResult
from ..repository import OlistRepository
from ..utils import decimal_to_json, money


class PaymentAgent:
    name = "payment_agent"

    def run(self, order_id: str, repository: OlistRepository, items: list[dict[str, str]]) -> AgentResult:
        rows = sorted(
            repository.payments_by_order.get(order_id, []),
            key=lambda row: int(row["payment_sequential"]),
        )
        payment_total = money(sum((Decimal(row["payment_value"]) for row in rows), Decimal("0")))
        payment_types = [row["payment_type"] for row in rows]

        if items:
            item_total = money(sum((Decimal(row["price"]) for row in items), Decimal("0")))
            freight_total = money(sum((Decimal(row["freight_value"]) for row in items), Decimal("0")))
            expected_total = money(item_total + freight_total)
            difference = money(payment_total - expected_total)
            reconciled: bool | None = abs(difference) <= Decimal("0.10")
        else:
            # Empty sums are zero, while reconciliation remains unknown because
            # there are no item rows to establish an expected order total.
            item_total = Decimal("0.00")
            freight_total = Decimal("0.00")
            expected_total = None
            difference = None
            reconciled = None

        output = {
            "currency": "BRL",
            "item_total_brl": decimal_to_json(item_total),
            "freight_total_brl": decimal_to_json(freight_total),
            "expected_total_brl": decimal_to_json(expected_total),
            "payment_total_brl": decimal_to_json(payment_total),
            "difference_brl": decimal_to_json(difference),
            "reconciled": reconciled,
            "payment_types": payment_types,
        }
        return AgentResult(
            output=output,
            facts={
                "rows": rows,
                "payment_count": len(rows),
                "payment_total": payment_total,
                "item_total": item_total,
                "freight_total": freight_total,
                "expected_total": expected_total,
                "difference": difference,
                "reconciled": reconciled,
            },
        )
