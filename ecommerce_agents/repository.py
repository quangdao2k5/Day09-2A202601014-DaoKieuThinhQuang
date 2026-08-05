"""Read-only Olist CSV repository with stable source ordering."""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path
from typing import Any


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


class OlistRepository:
    """Load only the tables required by EC_POLICY_V2.

    Reviews and geolocation are intentionally excluded: neither contributes to
    the required output schema or any policy condition.
    """

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        orders = _read_csv(data_dir / "olist_orders_dataset.csv")
        customers = _read_csv(data_dir / "olist_customers_dataset.csv")
        items = _read_csv(data_dir / "olist_order_items_dataset.csv")
        payments = _read_csv(data_dir / "olist_order_payments_dataset.csv")
        products = _read_csv(data_dir / "olist_products_dataset.csv")
        sellers = _read_csv(data_dir / "olist_sellers_dataset.csv")

        self.orders_in_source_order = orders
        self.orders_by_id = {row["order_id"]: row for row in orders}
        self.customers_by_id = {row["customer_id"]: row for row in customers}
        self.products_by_id = {row["product_id"]: row for row in products}
        self.sellers_by_id = {row["seller_id"]: row for row in sellers}

        self.items_by_order: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in items:
            self.items_by_order[row["order_id"]].append(row)

        self.payments_by_order: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in payments:
            self.payments_by_order[row["order_id"]].append(row)

        self.orders_by_unique_customer: dict[str, list[dict[str, str]]] = defaultdict(list)
        for order in orders:
            customer = self.customers_by_id[order["customer_id"]]
            self.orders_by_unique_customer[customer["customer_unique_id"]].append(order)

    def require_order(self, order_id: str) -> dict[str, str]:
        try:
            return self.orders_by_id[order_id]
        except KeyError as exc:
            raise ValueError(f"Order not found: {order_id}") from exc

    def summary(self) -> dict[str, Any]:
        return {
            "orders": len(self.orders_by_id),
            "customers": len(self.customers_by_id),
            "products": len(self.products_by_id),
            "sellers": len(self.sellers_by_id),
        }
