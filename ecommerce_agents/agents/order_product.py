"""Order, item, seller, product and category agent."""

from __future__ import annotations

from .base import AgentResult
from ..repository import OlistRepository
from ..utils import stable_unique


class OrderProductAgent:
    name = "order_product_agent"

    def run(self, order_id: str, repository: OlistRepository, include_products: bool) -> AgentResult:
        order = repository.require_order(order_id)
        items = list(repository.items_by_order.get(order_id, []))
        seller_ids = stable_unique(row["seller_id"] for row in items)
        product_ids = stable_unique(row["product_id"] for row in items)
        categories = stable_unique(
            repository.products_by_id[product_id]["product_category_name"]
            for product_id in product_ids
            if repository.products_by_id[product_id]["product_category_name"]
        )

        affected = {
            "order_ids": [order_id],
            "item_ids": [f"{order_id}:{row['order_item_id']}" for row in items[:5]],
            "seller_ids": seller_ids[:3],
            "payment_ids": [],
        }
        product_context = {
            "product_ids": product_ids[:5] if include_products else [],
            "category_names": categories[:5] if include_products else [],
        }
        return AgentResult(
            output={
                "affected_entities": affected,
                "product_context": product_context,
            },
            facts={
                "order": order,
                "items": items,
                "seller_ids": seller_ids,
                "product_ids": product_ids,
                "categories": categories,
                "item_count": len(items),
                "seller_count": len(seller_ids),
                "category_count": len(categories),
            },
        )
