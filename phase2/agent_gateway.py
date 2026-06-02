"""
AgentGateway - Agent 与本体引擎的交互层

职责：
- 能力发现 → Agent 决策 → 引擎执行 → 结构化拒绝/成功响应
- 支持被拦截后自动重试（双路径：真实 LLM / mock fallback）
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
PHASE1_DIR = REPO_ROOT / "phase1"
sys.path.insert(0, str(PHASE1_DIR))

from engine import (  # noqa: E402
    SchemaLoader,
    ObjectStore,
    RuleEngine,
    ActionEngine,
    AuditLogger,
)
from .capability_provider import CapabilityProvider
from .llm_client import LLMClient


@dataclass
class GatewayResponse:
    status: str  # success | rejected
    action_id: str
    agent_source: str
    reasoning: str
    message: str
    event_id: Optional[str] = None
    violations: Optional[List[Dict[str, str]]] = None
    triggered_rule: Optional[str] = None
    current_state: Optional[Dict[str, Any]] = None
    suggestion: Optional[str] = None
    created_objects: Optional[Dict[str, str]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


class AgentGateway:
    """Agent 交互网关"""

    FALLBACK_SUPPLIER = "S-ACME-001"

    def __init__(self, phase1_dir: Optional[Path] = None, scenario: str = "intercept_and_retry"):
        self.phase1_dir = Path(phase1_dir or PHASE1_DIR)
        schema_dir = self.phase1_dir / "schema"
        data_dir = self.phase1_dir / "data"
        log_dir = self.phase1_dir / "logs"

        self.schema_loader = SchemaLoader(schema_dir)
        self.object_store = ObjectStore(data_dir)
        self.audit_logger = AuditLogger(log_dir)
        self.rule_engine = RuleEngine(self.schema_loader, self.object_store)
        self.action_engine = ActionEngine(
            self.schema_loader, self.object_store, self.rule_engine, self.audit_logger
        )
        self.capability_provider = CapabilityProvider(schema_dir)
        self.llm_client = LLMClient(scenario=scenario)

        self.object_store.load_objects("Supplier")
        self.object_store.load_objects("Certification")
        self.object_store.load_objects("PurchaseOrder")

    @property
    def agent_mode(self) -> str:
        return self.llm_client.mode_label

    def get_tools(self) -> List[Dict[str, Any]]:
        return self.capability_provider.generate_openai_tools()

    def execute_agent_task(
        self,
        task: str,
        caller: str = "procurement-agent-v2",
        max_retries: int = 2,
    ) -> List[GatewayResponse]:
        """执行 Agent 任务，支持拦截后重试"""
        print(f"Agent 模式: {self.agent_mode}\n")

        tools = self.get_tools()
        context: Dict[str, Any] = {}
        responses: List[GatewayResponse] = []

        for attempt in range(1, max_retries + 1):
            print(f"--- 第 {attempt} 轮决策 ---")
            decision = self.llm_client.decide(task, tools, context)
            print(f"Agent 选择: {decision.action_id}")
            print(f"参数: {json.dumps(decision.params, ensure_ascii=False)}")
            print(f"理由: {decision.reasoning}\n")

            result = self.action_engine.execute_action(
                action_id=decision.action_id,
                params=decision.params,
                caller=caller,
            )

            if result.success:
                resp = GatewayResponse(
                    status="success",
                    action_id=decision.action_id,
                    agent_source=decision.source,
                    reasoning=decision.reasoning,
                    message=result.message,
                    event_id=result.event_id,
                    created_objects=result.created_objects,
                )
                responses.append(resp)
                print("✅ 操作成功")
                print(json.dumps(resp.to_dict(), ensure_ascii=False, indent=2))
                break

            rejection = self._build_rejection_response(
                decision.action_id,
                decision.source,
                decision.reasoning,
                result,
                decision.params,
            )
            responses.append(rejection)
            context["last_rejection"] = rejection.to_dict()

            print("❌ 操作被拦截")
            print(json.dumps(rejection.to_dict(), ensure_ascii=False, indent=2))
            print()

        return responses

    def _build_rejection_response(
        self,
        action_id: str,
        agent_source: str,
        reasoning: str,
        result,
        params: Dict[str, Any],
    ) -> GatewayResponse:
        supplier_pk = params.get("supplier_pk")
        current_state = self._extract_supplier_state(supplier_pk)
        triggered_rule = None
        if result.violations:
            triggered_rule = result.violations[0]["rule_id"]

        suggestion = self._build_suggestion(triggered_rule, supplier_pk, current_state)

        return GatewayResponse(
            status="rejected",
            action_id=action_id,
            agent_source=agent_source,
            reasoning=reasoning,
            message=result.message,
            violations=result.violations,
            triggered_rule=triggered_rule,
            current_state=current_state,
            suggestion=suggestion,
        )

    def _extract_supplier_state(self, supplier_pk: Optional[str]) -> Dict[str, Any]:
        if not supplier_pk:
            return {}

        state: Dict[str, Any] = {}
        supplier = self.object_store.get_object("Supplier", supplier_pk)
        if supplier:
            state[f"Supplier/{supplier_pk}"] = supplier

        certs = self.object_store.query_objects(
            "Certification",
            lambda c: c.get("supplier_pk") == supplier_pk,
        )
        for cert in certs:
            state[f"Certification/{cert['pk']}"] = cert

        return state

    def _build_suggestion(
        self,
        triggered_rule: Optional[str],
        supplier_pk: Optional[str],
        current_state: Dict[str, Any],
    ) -> str:
        if triggered_rule == "certification_validity":
            return (
                f"供应商 {supplier_pk} 认证即将过期，"
                f"建议选择认证有效的备选供应商 {self.FALLBACK_SUPPLIER}（ACME）"
            )
        if triggered_rule == "credit_limit_check":
            return "采购金额超过信用额度，建议减少金额或选择未结金额更低的供应商"
        return "请检查操作参数或更换供应商后重试"
