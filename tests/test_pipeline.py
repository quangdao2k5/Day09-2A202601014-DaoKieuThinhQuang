from __future__ import annotations

import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from ecommerce_agents.config import MODEL_PARAMETER_BILLION
from ecommerce_agents.coordinator import Coordinator
from ecommerce_agents.repository import OlistRepository
from ecommerce_agents.utils import hours_between


ROOT = Path(__file__).resolve().parents[1]


class RepositoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repository = OlistRepository(ROOT / "data")

    def test_core_join_counts(self) -> None:
        self.assertEqual(len(self.repository.orders_by_id), 99_441)
        self.assertEqual(len(self.repository.customers_by_id), 99_441)
        self.assertEqual(len(self.repository.products_by_id), 32_951)
        self.assertEqual(len(self.repository.sellers_by_id), 3_095)

    def test_model_is_within_assignment_limit(self) -> None:
        self.assertLessEqual(MODEL_PARAMETER_BILLION, 10.0)

    def test_hour_rounding(self) -> None:
        self.assertEqual(
            str(hours_between("2018-03-31 15:23:33", "2018-03-28 00:00:00")),
            "87.39",
        )


class EndToEndTests(unittest.TestCase):
    def test_all_50_cases_generate_and_verify(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temp = Path(temporary)
            coordinator = Coordinator(
                ROOT,
                output_dir=temp / "output",
                logging_dir=temp / "logging",
                llm_audit=False,
            )
            outputs = coordinator.run(expected_count=50)
            self.assertEqual(len(outputs), 50)
            self.assertEqual(
                Counter(row["case_assessment"]["primary_issue"] for row in outputs),
                {
                    "canceled_order_paid": 8,
                    "unavailable_order_paid": 6,
                    "late_delivery_seller": 10,
                    "late_delivery_logistics": 10,
                    "valid_split_payment": 8,
                    "unsupported_late_claim": 8,
                },
            )
            self.assertEqual(
                round(
                    sum(
                        row["financial_resolution"]["recommended_refund_brl"]
                        for row in outputs
                    ),
                    2,
                ),
                3437.76,
            )
            self.assertEqual(
                sorted(path.name for path in (temp / "output").glob("*.json")),
                [f"EC_{index:03d}.json" for index in range(1, 51)],
            )
            trace_rows = (temp / "logging" / "trace.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertGreater(len(trace_rows), 500)
            metadata = json.loads((temp / "logging" / "metadata.json").read_text())
            self.assertEqual(metadata["artifacts"]["case_count"], 50)


if __name__ == "__main__":
    unittest.main()
