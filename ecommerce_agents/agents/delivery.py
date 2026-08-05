"""Delivery variance and seller handoff agent."""

from __future__ import annotations

from .base import AgentResult
from ..utils import decimal_to_json, hours_between, stable_unique


class DeliveryAgent:
    name = "delivery_agent"

    def run(self, order: dict[str, str], items: list[dict[str, str]]) -> AgentResult:
        delivered = order["order_delivered_customer_date"] or None
        estimated = order["order_estimated_delivery_date"] or None
        carrier = order["order_delivered_carrier_date"] or None
        delivery_variance = hours_between(delivered, estimated)

        seller_ids = stable_unique(row["seller_id"] for row in items)
        analysis: list[dict[str, object]] = []
        late_sellers: list[str] = []
        for seller_id in seller_ids:
            limits = [row["shipping_limit_date"] for row in items if row["seller_id"] == seller_id]
            earliest_limit = min(limits) if limits else None
            handoff_variance = hours_between(carrier, earliest_limit)
            is_late = handoff_variance is not None and handoff_variance > 0
            if is_late:
                late_sellers.append(seller_id)
            analysis.append(
                {
                    "seller_id": seller_id,
                    "shipping_limit_at": earliest_limit,
                    "handoff_variance_hours": decimal_to_json(handoff_variance),
                    "late_handoff": is_late,
                }
            )

        return AgentResult(
            output={
                "delivered_at": delivered,
                "estimated_delivery_at": estimated,
                "carrier_handoff_at": carrier,
                "delivery_variance_hours": decimal_to_json(delivery_variance),
                "seller_handoff_analysis": analysis,
                "late_handoff_seller_ids": late_sellers[:3],
            },
            facts={
                "delivery_variance": delivery_variance,
                "late_delivery": delivery_variance is not None and delivery_variance > 0,
                "late_seller_ids": late_sellers,
            },
        )
