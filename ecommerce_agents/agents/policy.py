"""EC_POLICY_V2 rule agent."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from .base import AgentResult
from ..utils import decimal_to_json


class PolicyAgent:
    name = "policy_agent"

    ROOT_CAUSES = {
        "late_delivery_seller": "SELLER_HANDOFF_AFTER_LIMIT",
        "late_delivery_logistics": "CARRIER_DELIVERED_AFTER_ESTIMATE",
        "canceled_order_paid": "ORDER_CANCELED_AFTER_PAYMENT",
        "unavailable_order_paid": "ORDER_UNAVAILABLE_AFTER_PAYMENT",
        "valid_split_payment": "MULTIPLE_PAYMENTS_RECONCILED",
        "unsupported_late_claim": "DELIVERY_WITHIN_ESTIMATE",
    }

    def run(
        self,
        order_facts: dict[str, Any],
        customer_facts: dict[str, Any],
        payment_facts: dict[str, Any],
        delivery_facts: dict[str, Any],
    ) -> AgentResult:
        order = order_facts["order"]
        status = order["order_status"]
        payment_total: Decimal = payment_facts["payment_total"]
        freight_total: Decimal | None = payment_facts["freight_total"]
        reconciled = payment_facts["reconciled"]
        payment_count = payment_facts["payment_count"]
        late_delivery = delivery_facts["late_delivery"]
        late_sellers = delivery_facts["late_seller_ids"]

        if status == "canceled" and payment_total > 0:
            primary = "canceled_order_paid"
            refund = payment_total
            primary_action = "issue_full_refund"
            parties = [{"party_type": "platform", "party_id": "OLIST_PLATFORM"}]
        elif status == "unavailable" and payment_total > 0:
            primary = "unavailable_order_paid"
            refund = payment_total
            primary_action = "issue_full_refund"
            parties = [{"party_type": "platform", "party_id": "OLIST_PLATFORM"}]
        elif late_delivery and late_sellers:
            primary = "late_delivery_seller"
            refund = freight_total or Decimal("0")
            primary_action = "refund_freight"
            parties = [
                {"party_type": "seller", "party_id": seller_id}
                for seller_id in late_sellers[:3]
            ]
        elif late_delivery:
            primary = "late_delivery_logistics"
            refund = freight_total or Decimal("0")
            primary_action = "refund_freight"
            parties = [
                {"party_type": "logistics_provider", "party_id": "LOGISTICS_PROVIDER"}
            ]
        elif payment_count >= 2 and reconciled is True:
            primary = "valid_split_payment"
            refund = Decimal("0")
            primary_action = "explain_valid_split_payment"
            parties = []
        elif delivery_facts["delivery_variance"] is not None and not late_delivery and reconciled is True:
            primary = "unsupported_late_claim"
            refund = Decimal("0")
            primary_action = "reject_late_refund"
            parties = []
        else:
            raise ValueError(
                f"Order {order['order_id']} does not match any EC_POLICY_V2 primary issue"
            )

        secondary: list[str] = []
        if order_facts["item_count"] >= 2:
            secondary.append("multi_item_order")
        if order_facts["seller_count"] >= 2:
            secondary.append("multi_seller_order")
        if payment_count >= 2:
            secondary.append("split_payment")
        if customer_facts["related_order_count"] >= 1:
            secondary.append("repeat_customer")
        if order_facts["category_count"] >= 2:
            secondary.append("multiple_categories")

        actions = [primary_action]
        if primary == "late_delivery_seller":
            actions.append("review_seller_handoff")
        elif primary == "late_delivery_logistics":
            actions.append("review_carrier_delay")
        if primary in {"canceled_order_paid", "unavailable_order_paid"}:
            actions.append("verify_refund_completion")
        if order_facts["seller_count"] >= 2:
            actions.append("coordinate_multi_seller_case")
        if payment_count >= 2 and primary != "valid_split_payment":
            actions.append("verify_payment_allocation")

        root_cause = self.ROOT_CAUSES[primary]
        return AgentResult(
            output={
                "case_assessment": {
                    "primary_issue": primary,
                    "secondary_issues": secondary,
                    "case_status": "action_required" if refund > 0 else "no_action",
                    "confidence": 1.0,
                },
                "root_cause_analysis": {
                    "ranked_causes": [{"cause_code": root_cause, "rank": 1}],
                    "responsible_parties": parties,
                },
                "financial_resolution": {
                    "currency": "BRL",
                    "recommended_refund_brl": decimal_to_json(refund),
                },
                "resolution_actions": actions[:5],
            },
            facts={
                "primary_issue": primary,
                "root_cause": root_cause,
                "responsible_parties": parties,
                "refund": refund,
            },
        )
