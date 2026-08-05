"""Coordinator and explicit agent-to-agent handoff orchestration."""

from __future__ import annotations

import json
import platform
import time
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from . import __version__
from .agents import (
    CustomerAgent,
    DeliveryAgent,
    OrderProductAgent,
    PaymentAgent,
    PolicyAgent,
    VerifierAgent,
)
from .agents.base import AgentResult
from .config import (
    MODEL_NAME,
    MODEL_PARAMETER_BILLION,
    MODEL_PROVIDER,
    POLICY_VERSION,
    load_local_env,
    validate_model_limit,
)
from .llm import OpenRouterAuditor
from .repository import OlistRepository
from .tracing import TraceLogger
from .utils import json_digest


class Coordinator:
    name = "coordinator_agent"

    def __init__(
        self,
        root: Path,
        *,
        output_dir: Path | None = None,
        logging_dir: Path | None = None,
        llm_audit: bool = False,
    ) -> None:
        self.root = root.resolve()
        self.input_dir = self.root / "input"
        self.output_dir = output_dir or self.root / "output"
        self.logging_dir = logging_dir or self.root / "logging"
        self.llm_audit = llm_audit
        validate_model_limit()
        load_local_env(self.root)

        self.repository = OlistRepository(self.root / "data")
        self.customer_agent = CustomerAgent()
        self.order_agent = OrderProductAgent()
        self.payment_agent = PaymentAgent()
        self.delivery_agent = DeliveryAgent()
        self.policy_agent = PolicyAgent()
        self.verifier_agent = VerifierAgent()
        self.auditor = OpenRouterAuditor()
        if llm_audit and not self.auditor.configured:
            raise RuntimeError("LLM audit requested but OPENROUTER_API_KEY is not configured in .env")

    def run(self, expected_count: int = 50) -> list[dict[str, Any]]:
        cases = self._load_cases(expected_count)
        run_id = uuid.uuid4().hex
        trace = TraceLogger(self.logging_dir / "trace.jsonl", run_id)
        started = time.perf_counter()
        trace.emit(
            "run_started",
            agent=self.name,
            payload={
                "case_count": len(cases),
                "policy_version": POLICY_VERSION,
                "repository": self.repository.summary(),
                "llm_audit": self.llm_audit,
            },
        )
        self.output_dir.mkdir(parents=True, exist_ok=True)
        outputs: list[dict[str, Any]] = []
        audit_successes = 0
        for case in cases:
            try:
                output, audited = self._run_case(case, trace)
                outputs.append(output)
                audit_successes += int(audited)
            except Exception as exc:
                trace.emit(
                    "case_failed",
                    case_id=case.get("case_id"),
                    agent=self.name,
                    payload={"error_type": type(exc).__name__, "error": str(exc)[:500]},
                )
                raise

        duration_ms = (time.perf_counter() - started) * 1000
        trace.emit(
            "run_completed",
            agent=self.name,
            payload={
                "case_count": len(outputs),
                "output_digest": json_digest(outputs),
                "llm_audit_successes": audit_successes,
            },
            duration_ms=duration_ms,
        )
        self._write_metadata(run_id, outputs, duration_ms, audit_successes)
        return outputs

    def _run_case(self, case: dict[str, Any], trace: TraceLogger) -> tuple[dict[str, Any], bool]:
        case_id = case["case_id"]
        request = case["customer_request"]
        scope = case["investigation_scope"]
        order_id = request["claimed_order_id"]
        trace.emit(
            "case_started",
            case_id=case_id,
            agent=self.name,
            payload={"order_id": order_id, "policy_version": case["policy_version"]},
        )

        order_result = self._invoke(
            self.order_agent.name,
            case_id,
            trace,
            lambda: self.order_agent.run(
                order_id, self.repository, scope["include_product_context"]
            ),
        )
        customer_result = self._invoke(
            self.customer_agent.name,
            case_id,
            trace,
            lambda: self.customer_agent.run(
                order_id, self.repository, scope["include_customer_history"]
            ),
        )
        payment_result = self._invoke(
            self.payment_agent.name,
            case_id,
            trace,
            lambda: self.payment_agent.run(
                order_id, self.repository, order_result.facts["items"]
            ),
        )
        delivery_result = self._invoke(
            self.delivery_agent.name,
            case_id,
            trace,
            lambda: self.delivery_agent.run(
                order_result.facts["order"], order_result.facts["items"]
            ),
        )

        trace.emit(
            "a2a_handoff",
            case_id=case_id,
            agent=self.name,
            recipient=self.policy_agent.name,
            payload={
                "sources": [
                    self.order_agent.name,
                    self.customer_agent.name,
                    self.payment_agent.name,
                    self.delivery_agent.name,
                ],
                "facts_digest": json_digest(
                    {
                        "order": order_result.output,
                        "customer": customer_result.output,
                        "payment": payment_result.output,
                        "delivery": delivery_result.output,
                    }
                ),
            },
        )
        policy_result = self._invoke(
            self.policy_agent.name,
            case_id,
            trace,
            lambda: self.policy_agent.run(
                order_result.facts,
                customer_result.facts,
                payment_result.facts,
                delivery_result.facts,
            ),
        )

        affected = order_result.output["affected_entities"]
        payment_rows = payment_result.facts["rows"]
        affected["payment_ids"] = [
            f"{order_id}:{row['payment_sequential']}" for row in payment_rows[:5]
        ]
        affected["seller_ids"] = [
            party["party_id"]
            for party in policy_result.facts["responsible_parties"]
            if party["party_type"] == "seller"
        ][:3]
        output = {
            "case_id": case_id,
            "case_assessment": policy_result.output["case_assessment"],
            "affected_entities": affected,
            "customer_context": customer_result.output,
            "product_context": order_result.output["product_context"],
            "delivery_analysis": delivery_result.output,
            "payment_reconciliation": payment_result.output,
            "root_cause_analysis": policy_result.output["root_cause_analysis"],
            "evidence_ids": self._build_evidence(
                order_id, affected, policy_result.facts
            ),
            "financial_resolution": policy_result.output["financial_resolution"],
            "resolution_actions": policy_result.output["resolution_actions"],
        }
        trace.emit(
            "a2a_handoff",
            case_id=case_id,
            agent=self.policy_agent.name,
            recipient=self.verifier_agent.name,
            payload={"output_digest": json_digest(output)},
        )
        verify_started = time.perf_counter()
        errors = self.verifier_agent.verify(case, output, self.repository)
        verify_ms = (time.perf_counter() - verify_started) * 1000
        if errors:
            trace.emit(
                "verification_failed",
                case_id=case_id,
                agent=self.verifier_agent.name,
                recipient=self.name,
                payload={"errors": errors},
                duration_ms=verify_ms,
            )
            raise ValueError(f"Verifier rejected {case_id}: {'; '.join(errors)}")
        trace.emit(
            "verification_passed",
            case_id=case_id,
            agent=self.verifier_agent.name,
            recipient=self.name,
            payload={"error_count": 0, "output_digest": json_digest(output)},
            duration_ms=verify_ms,
        )

        audited = False
        if self.llm_audit:
            audit_started = time.perf_counter()
            audit = self.auditor.audit(output)
            audited = True
            trace.emit(
                "llm_read_only_audit",
                case_id=case_id,
                agent=self.verifier_agent.name,
                recipient=self.name,
                payload={
                    "status": audit["audit"].get("status"),
                    "reason": str(audit["audit"].get("reason", ""))[:200],
                    "request_id": audit.get("request_id"),
                    "usage": audit.get("usage", {}),
                },
                model_used=True,
                duration_ms=(time.perf_counter() - audit_started) * 1000,
            )

        output_path = self.output_dir / f"{case_id}.json"
        output_path.write_text(
            json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        trace.emit(
            "case_completed",
            case_id=case_id,
            agent=self.name,
            payload={
                "output_file": f"output/{case_id}.json",
                "primary_issue": output["case_assessment"]["primary_issue"],
                "output_digest": json_digest(output),
            },
        )
        return output, audited

    def _invoke(
        self,
        agent_name: str,
        case_id: str,
        trace: TraceLogger,
        operation: Callable[[], AgentResult],
    ) -> AgentResult:
        trace.emit(
            "agent_delegated",
            case_id=case_id,
            agent=self.name,
            recipient=agent_name,
        )
        started = time.perf_counter()
        result = operation()
        trace.emit(
            "a2a_handoff",
            case_id=case_id,
            agent=agent_name,
            recipient=self.name,
            payload={"output_digest": json_digest(result.output)},
            duration_ms=(time.perf_counter() - started) * 1000,
        )
        return result

    @staticmethod
    def _build_evidence(
        order_id: str,
        affected: dict[str, list[str]],
        policy_facts: dict[str, Any],
    ) -> list[str]:
        evidence = [f"order:{order_id}"]
        evidence.extend(f"item:{item_id}" for item_id in affected["item_ids"])
        evidence.extend(f"payment:{payment_id}" for payment_id in affected["payment_ids"])
        for party in policy_facts["responsible_parties"]:
            if party["party_type"] == "seller":
                evidence.append(f"seller:{party['party_id']}")
        evidence.append(f"policy:{policy_facts['root_cause']}")
        return evidence[:20]

    def _load_cases(self, expected_count: int) -> list[dict[str, Any]]:
        expected_names = [f"EC_{index:03d}.json" for index in range(1, expected_count + 1)]
        actual_names = sorted(path.name for path in self.input_dir.glob("*.json"))
        if actual_names != expected_names:
            raise ValueError("input/ must contain exactly EC_001.json through EC_050.json")
        cases: list[dict[str, Any]] = []
        for name in expected_names:
            case = json.loads((self.input_dir / name).read_text(encoding="utf-8"))
            if case.get("case_id") != Path(name).stem:
                raise ValueError(f"case_id mismatch in {name}")
            if case.get("policy_version") != POLICY_VERSION:
                raise ValueError(f"Unsupported policy_version in {name}")
            self.repository.require_order(case["customer_request"]["claimed_order_id"])
            cases.append(case)
        return cases

    def _write_metadata(
        self,
        run_id: str,
        outputs: list[dict[str, Any]],
        duration_ms: float,
        audit_successes: int,
    ) -> None:
        counts = Counter(row["case_assessment"]["primary_issue"] for row in outputs)
        metadata = {
            "run_id": run_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "policy_version": POLICY_VERSION,
            "model": {
                "provider": MODEL_PROVIDER,
                "name": MODEL_NAME,
                "parameter_count_billion": MODEL_PARAMETER_BILLION,
                "maximum_allowed_billion": 10.0,
                "role": "read-only final consistency audit",
                "llm_audit_enabled": self.llm_audit,
                "successful_audits": audit_successes,
            },
            "framework": {
                "name": "custom-python-a2a",
                "version": __version__,
                "dependencies": "python-standard-library-only",
            },
            "runtime": {
                "python_version": platform.python_version(),
                "platform": platform.platform(),
                "duration_ms": round(duration_ms, 2),
            },
            "artifacts": {
                "case_count": len(outputs),
                "primary_issue_counts": dict(sorted(counts.items())),
                "trace_path": "logging/trace.jsonl",
                "output_directory": "output",
                "output_digest": json_digest(outputs),
            },
            "security": {
                "api_key_source": ".env:OPENROUTER_API_KEY" if self.llm_audit else None,
                "secret_logged": False,
            },
        }
        path = self.logging_dir / "metadata.json"
        path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
