"""Customer identity and order-history agent."""

from __future__ import annotations

from .base import AgentResult
from ..repository import OlistRepository


class CustomerAgent:
    name = "customer_agent"

    def run(self, order_id: str, repository: OlistRepository, include_history: bool) -> AgentResult:
        order = repository.require_order(order_id)
        customer = repository.customers_by_id[order["customer_id"]]
        unique_id = customer["customer_unique_id"]
        related = []
        if include_history:
            related = [
                row["order_id"]
                for row in repository.orders_by_unique_customer[unique_id]
                if row["order_id"] != order_id
            ]
        return AgentResult(
            output={
                "customer_unique_id": unique_id,
                "related_order_ids": related[:5],
            },
            facts={
                "customer": customer,
                "related_order_count": len(related),
            },
        )
