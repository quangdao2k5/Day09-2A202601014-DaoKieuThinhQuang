"""Independent output verifier agent built directly from raw CSV rows."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from ..repository import OlistRepository
from ..utils import decimal_to_json, hours_between, money, stable_unique


class VerifierAgent:
    name = "verifier_agent"

    ROOT_CAUSES = {
        "late_delivery_seller": "SELLER_HANDOFF_AFTER_LIMIT",
        "late_delivery_logistics": "CARRIER_DELIVERED_AFTER_ESTIMATE",
        "canceled_order_paid": "ORDER_CANCELED_AFTER_PAYMENT",
        "unavailable_order_paid": "ORDER_UNAVAILABLE_AFTER_PAYMENT",
        "valid_split_payment": "MULTIPLE_PAYMENTS_RECONCILED",
        "unsupported_late_claim": "DELIVERY_WITHIN_ESTIMATE",
    }
    LIMITS = {
        "affected_entities.order_ids": 5,
        "affected_entities.item_ids": 5,
        "affected_entities.seller_ids": 3,
        "affected_entities.payment_ids": 5,
        "customer_context.related_order_ids": 5,
        "product_context.product_ids": 5,
        "product_context.category_names": 5,
        "delivery_analysis.late_handoff_seller_ids": 3,
        "root_cause_analysis.ranked_causes": 3,
        "root_cause_analysis.responsible_parties": 3,
        "evidence_ids": 20,
        "resolution_actions": 5,
    }

    def verify(
        self,
        case_input: dict[str, Any],
        output: dict[str, Any],
        repository: OlistRepository,
    ) -> list[str]:
        errors: list[str] = []
        expected = self._expected_output(case_input, output, repository)
        self._compare_sections(expected, output, errors)
        self._verify_limits(output, errors)
        try:
            json.dumps(output, ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError) as exc:
            errors.append(f"not strict JSON serializable: {exc}")
        return errors

    def _expected_output(
        self,
        case: dict[str, Any],
        actual: dict[str, Any],
        repository: OlistRepository,
    ) -> dict[str, Any]:
        case_id = case["case_id"]
        order_id = case["customer_request"]["claimed_order_id"]
        order = repository.require_order(order_id)
        items = list(repository.items_by_order.get(order_id, []))
        payments = list(repository.payments_by_order.get(order_id, []))
        scope = case["investigation_scope"]

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
            "payment_ids": [
                f"{order_id}:{row['payment_sequential']}" for row in payments[:5]
            ],
        }
        product_context = {
            "product_ids": product_ids[:5] if scope["include_product_context"] else [],
            "category_names": categories[:5] if scope["include_product_context"] else [],
        }

        customer = repository.customers_by_id[order["customer_id"]]
        unique_id = customer["customer_unique_id"]
        related = []
        if scope["include_customer_history"]:
            related = [
                row["order_id"]
                for row in repository.orders_by_unique_customer[unique_id]
                if row["order_id"] != order_id
            ]
        customer_context = {
            "customer_unique_id": unique_id,
            "related_order_ids": related[:5],
        }

        payment_total = money(
            sum((Decimal(row["payment_value"]) for row in payments), Decimal("0"))
        )
        if items:
            item_total = money(
                sum((Decimal(row["price"]) for row in items), Decimal("0"))
            )
            freight_total = money(
                sum((Decimal(row["freight_value"]) for row in items), Decimal("0"))
            )
            expected_total = money(item_total + freight_total)
            difference = money(payment_total - expected_total)
            reconciled: bool | None = abs(difference) <= Decimal("0.10")
        else:
            item_total = Decimal("0.00")
            freight_total = Decimal("0.00")
            expected_total = difference = None
            reconciled = None
        payment_output = {
            "currency": "BRL",
            "item_total_brl": decimal_to_json(item_total),
            "freight_total_brl": decimal_to_json(freight_total),
            "expected_total_brl": decimal_to_json(expected_total),
            "payment_total_brl": decimal_to_json(payment_total),
            "difference_brl": decimal_to_json(difference),
            "reconciled": reconciled,
            "payment_types": stable_unique(row["payment_type"] for row in payments),
        }

        delivered = order["order_delivered_customer_date"] or None
        estimated = order["order_estimated_delivery_date"] or None
        carrier = order["order_delivered_carrier_date"] or None
        delivery_variance = hours_between(delivered, estimated)
        handoff_analysis: list[dict[str, Any]] = []
        late_sellers: list[str] = []
        analyzable_seller_ids = seller_ids if carrier is not None else []
        for seller_id in analyzable_seller_ids:
            earliest_limit = min(
                row["shipping_limit_date"]
                for row in items
                if row["seller_id"] == seller_id
            )
            variance = hours_between(carrier, earliest_limit)
            is_late = variance is not None and variance > 0
            if is_late:
                late_sellers.append(seller_id)
            handoff_analysis.append(
                {
                    "seller_id": seller_id,
                    "shipping_limit_at": earliest_limit,
                    "handoff_variance_hours": decimal_to_json(variance),
                    "late_handoff": is_late,
                }
            )
        delivery_output = {
            "delivered_at": delivered,
            "estimated_delivery_at": estimated,
            "carrier_handoff_at": carrier,
            "delivery_variance_hours": decimal_to_json(delivery_variance),
            "seller_handoff_analysis": handoff_analysis,
            "late_handoff_seller_ids": late_sellers[:3],
        }

        late_delivery = delivery_variance is not None and delivery_variance > 0
        primary, refund, primary_action, parties = self._resolve_primary(
            order["order_status"],
            payment_total,
            freight_total,
            len(payments),
            reconciled,
            delivery_variance,
            late_delivery,
            late_sellers,
        )
        affected["seller_ids"] = [
            party["party_id"]
            for party in parties
            if party["party_type"] == "seller"
        ][:3]
        secondary: list[str] = []
        if len(items) >= 2:
            secondary.append("multi_item_order")
        if len(seller_ids) >= 2:
            secondary.append("multi_seller_order")
        if len(payments) >= 2:
            secondary.append("split_payment")
        if related:
            secondary.append("repeat_customer")
        if len(categories) >= 2:
            secondary.append("multiple_categories")

        actions = [primary_action]
        if primary == "late_delivery_seller":
            actions.append("review_seller_handoff")
        elif primary == "late_delivery_logistics":
            actions.append("review_carrier_delay")
        if primary in {"canceled_order_paid", "unavailable_order_paid"}:
            actions.append("verify_refund_completion")
        if len(seller_ids) >= 2:
            actions.append("coordinate_multi_seller_case")
        if len(payments) >= 2 and primary != "valid_split_payment":
            actions.append("verify_payment_allocation")

        root_cause = self.ROOT_CAUSES[primary]
        evidence = [f"order:{order_id}"]
        evidence.extend(f"item:{value}" for value in affected["item_ids"])
        evidence.extend(f"payment:{value}" for value in affected["payment_ids"])
        evidence.extend(
            f"seller:{party['party_id']}"
            for party in parties
            if party["party_type"] == "seller"
        )
        evidence.append(f"policy:{root_cause}")

        confidence = actual.get("case_assessment", {}).get("confidence")
        return {
            "case_id": case_id,
            "case_assessment": {
                "primary_issue": primary,
                "secondary_issues": secondary,
                "case_status": "action_required" if refund > 0 else "no_action",
                "confidence": confidence,
            },
            "affected_entities": affected,
            "customer_context": customer_context,
            "product_context": product_context,
            "delivery_analysis": delivery_output,
            "payment_reconciliation": payment_output,
            "root_cause_analysis": {
                "ranked_causes": [{"cause_code": root_cause, "rank": 1}],
                "responsible_parties": parties,
            },
            "evidence_ids": evidence[:20],
            "financial_resolution": {
                "currency": "BRL",
                "recommended_refund_brl": decimal_to_json(refund),
            },
            "resolution_actions": actions[:5],
        }

    @staticmethod
    def _resolve_primary(
        status: str,
        payment_total: Decimal,
        freight_total: Decimal | None,
        payment_count: int,
        reconciled: bool | None,
        delivery_variance: Decimal | None,
        late_delivery: bool,
        late_sellers: list[str],
    ) -> tuple[str, Decimal, str, list[dict[str, str]]]:
        if status == "canceled" and payment_total > 0:
            return (
                "canceled_order_paid",
                payment_total,
                "issue_full_refund",
                [{"party_type": "platform", "party_id": "OLIST_PLATFORM"}],
            )
        if status == "unavailable" and payment_total > 0:
            return (
                "unavailable_order_paid",
                payment_total,
                "issue_full_refund",
                [{"party_type": "platform", "party_id": "OLIST_PLATFORM"}],
            )
        if late_delivery and late_sellers:
            return (
                "late_delivery_seller",
                freight_total or Decimal("0"),
                "refund_freight",
                [
                    {"party_type": "seller", "party_id": seller_id}
                    for seller_id in late_sellers[:3]
                ],
            )
        if late_delivery:
            return (
                "late_delivery_logistics",
                freight_total or Decimal("0"),
                "refund_freight",
                [
                    {
                        "party_type": "logistics_provider",
                        "party_id": "LOGISTICS_PROVIDER",
                    }
                ],
            )
        if payment_count >= 2 and reconciled is True:
            return "valid_split_payment", Decimal("0"), "explain_valid_split_payment", []
        if delivery_variance is not None and delivery_variance <= 0 and reconciled is True:
            return "unsupported_late_claim", Decimal("0"), "reject_late_refund", []
        raise ValueError("case does not match EC_POLICY_V2")

    @staticmethod
    def _compare_sections(
        expected: dict[str, Any], actual: dict[str, Any], errors: list[str]
    ) -> None:
        required = set(expected)
        if set(actual) != required:
            errors.append(f"top-level keys mismatch: {sorted(set(actual) ^ required)}")
        confidence = actual.get("case_assessment", {}).get("confidence")
        if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
            errors.append("confidence must be numeric")
        elif not 0 <= confidence <= 1:
            errors.append("confidence outside [0, 1]")
        for key, expected_value in expected.items():
            if actual.get(key) != expected_value:
                errors.append(f"{key} does not match independently recomputed value")

    def _verify_limits(self, output: dict[str, Any], errors: list[str]) -> None:
        for path, limit in self.LIMITS.items():
            value: Any = output
            for part in path.split("."):
                value = value.get(part, []) if isinstance(value, dict) else []
            if not isinstance(value, list):
                errors.append(f"{path} must be an array")
            elif len(value) > limit:
                errors.append(f"{path} exceeds limit {limit}")
