"""
AgentGateway - Agent 与本体引擎的交互层

OAG 三层能力在此组装：
  Layer 1 - Capability Discovery : CapabilityProvider 把 Schema → LLM tools
  Layer 2 - Execution Constraints: ActionEngine 实时拦截，结构化拒绝响应
  Layer 3 - Decision Lineage     : TaskAuditLogger 记录完整任务决策链

主流程：
  任务接入 → 能力发现 → Agent 决策（LLM/mock）→ 引擎执行/拦截
  → 结构化拒绝（含 schema 驱动建议）→ Agent 重新生成决策 → 任务级日志
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import sys
import yaml

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


# ── 数据结构 ───────────────────────────────────────────────────────────────────

@dataclass
class GatewayResponse:
    status: str               # success | rejected
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


@dataclass
class DecisionRound:
    """一轮 Agent 决策的完整记录"""
    round: int
    agent_source: str
    action_id: str
    params: Dict[str, Any]
    reasoning: str
    engine_status: str           # success | rejected
    engine_message: str
    triggered_rule: Optional[str] = None
    suggestion: Optional[str] = None   # 来自 Schema，非硬编码
    event_id: Optional[str] = None


@dataclass
class TaskDecisionLog:
    """
    OAG 任务级审计日志 —— 记录一个任务的完整决策链

    对应 Layer 3 Decision Lineage 的核心数据结构：
    - 不只记录每次 Action，而是记录"Agent 为什么这样做、怎么调整的"
    - 包含 Agent 视角（reasoning）和引擎视角（violations/suggestion）
    """
    task_id: str
    task: str
    caller: str
    agent_mode: str
    rounds: List[Dict[str, Any]] = field(default_factory=list)
    final_outcome: str = "pending"
    total_rounds: int = 0
    executed_at: str = field(default_factory=lambda: datetime.now().isoformat())


# ── 任务级日志写入 ─────────────────────────────────────────────────────────────

class TaskAuditLogger:
    """写入任务级别的 OAG 决策链日志"""

    def __init__(self, log_dir: Path):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.log_file = self.log_dir / "task_decisions.jsonl"

    def write(self, log: TaskDecisionLog) -> None:
        with open(self.log_file, "a", encoding="utf-8") as f:
            data = asdict(log)
            f.write(json.dumps(data, ensure_ascii=False) + "\n")

    def load_all(self) -> List[Dict[str, Any]]:
        if not self.log_file.exists():
            return []
        tasks = []
        with open(self.log_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        tasks.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        return tasks


# ── AgentGateway ──────────────────────────────────────────────────────────────

class AgentGateway:
    """
    OAG 三层能力的组装入口

    Layer 1: capability_provider  → Agent 能看懂自己可以做什么
    Layer 2: action_engine        → 强制拦截违规操作
    Layer 3: task_audit_logger    → 记录完整决策链（可事后追溯）
    """

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
        self.task_audit_logger = TaskAuditLogger(log_dir)

        # 从 Schema 加载规则建议（OAG Layer 2：建议来自本体，不是应用代码）
        self._rule_suggestions = self._load_rule_suggestions(schema_dir)

        self.object_store.load_objects("Supplier")
        self.object_store.load_objects("Certification")
        self.object_store.load_objects("PurchaseOrder")

    def _load_rule_suggestions(self, schema_dir: Path) -> Dict[str, str]:
        """从 rules.yaml 读取每条规则的 suggestion 字段"""
        path = schema_dir / "rules.yaml"
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return {
            r["rule_id"]: r.get("suggestion", "请检查操作参数后重试")
            for r in data.get("rules", [])
        }

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
        """
        执行 Agent 任务——OAG 完整闭环

        Layer 1: 先把本体 Schema 转成 tools 交给 Agent（能力发现）
        Layer 2: 引擎执行时实时拦截，把约束响应结构化返回给 Agent（执行约束）
        Layer 3: 每轮决策都记录到任务日志，形成可追溯的决策链（决策血统）
        """
        print(f"Agent 模式: {self.agent_mode}\n")

        # Layer 1 - Capability Discovery：把 Schema 变成 Agent 的"操作手册"
        tools = self.get_tools()

        task_log = TaskDecisionLog(
            task_id=f"task-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6]}",
            task=task,
            caller=caller,
            agent_mode=self.agent_mode,
        )

        context: Dict[str, Any] = {}
        responses: List[GatewayResponse] = []

        for attempt in range(1, max_retries + 1):
            print(f"--- 第 {attempt} 轮决策 ---")

            # ── OAG "G"（Generation）：Agent 基于 Schema 约束生成决策 ──────────
            if context.get("last_rejection"):
                print(f"[OAG] Agent 收到本体层拒绝响应，正在重新生成决策...")
                print(f"[OAG] 拒绝原因: {context['last_rejection'].get('triggered_rule')}")
                print(f"[OAG] 本体建议: {context['last_rejection'].get('suggestion')}\n")

            decision = self.llm_client.decide(task, tools, context)
            print(f"Agent 选择: {decision.action_id}")
            print(f"参数: {json.dumps(decision.params, ensure_ascii=False)}")
            print(f"理由: {decision.reasoning}\n")

            # ── OAG Layer 2（Execution Constraints）：引擎执行或强制拦截 ────────
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

                task_log.rounds.append(asdict(DecisionRound(
                    round=attempt,
                    agent_source=decision.source,
                    action_id=decision.action_id,
                    params=decision.params,
                    reasoning=decision.reasoning,
                    engine_status="success",
                    engine_message=result.message,
                    event_id=result.event_id,
                )))
                task_log.final_outcome = "success"
                break

            # ── 构建结构化拒绝响应（suggestion 来自 Schema，不是硬编码）────────
            rejection = self._build_rejection_response(
                decision.action_id,
                decision.source,
                decision.reasoning,
                result,
                decision.params,
            )
            responses.append(rejection)
            context["last_rejection"] = rejection.to_dict()

            print("❌ 操作被本体层拦截")
            print(json.dumps(rejection.to_dict(), ensure_ascii=False, indent=2))
            print()

            task_log.rounds.append(asdict(DecisionRound(
                round=attempt,
                agent_source=decision.source,
                action_id=decision.action_id,
                params=decision.params,
                reasoning=decision.reasoning,
                engine_status="rejected",
                engine_message=result.message,
                triggered_rule=rejection.triggered_rule,
                suggestion=rejection.suggestion,
            )))

        else:
            task_log.final_outcome = "max_retries_exceeded"

        task_log.total_rounds = len(task_log.rounds)

        # ── OAG Layer 3（Decision Lineage）：写入任务级决策链日志 ─────────────
        self.task_audit_logger.write(task_log)
        print(f"\n[OAG] 任务决策链已记录: {task_log.task_id}（共 {task_log.total_rounds} 轮）")

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

        # suggestion 从 Schema 读取，体现"本体层主动告知 Agent 如何调整"
        suggestion = self._rule_suggestions.get(triggered_rule, "请检查操作参数后重试")

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
