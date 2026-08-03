"""
ep_coordinator — Phase 8 Harness 主循环（plan → execute → verify）

Harness 层（零 LLM）：IntentRouter → MemoryInjector → AtomicityCheck → VerifyGate → escalation
Agent 层（2 LLM 节点）：BSA + CA
"""

from __future__ import annotations

import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

DEMOCODE_ROOT = Path(__file__).parent.parent.parent
PHASE6 = DEMOCODE_ROOT / "phase6"
PHASE7 = DEMOCODE_ROOT / "phase7"
PHASE8 = DEMOCODE_ROOT / "phase8"
sys.path.insert(0, str(PHASE6))
sys.path.insert(0, str(PHASE7))
sys.path.insert(0, str(PHASE8))
sys.path.insert(0, str(DEMOCODE_ROOT))

from agent_memory_scope import AgentMemoryScope, AgentMemoryScopeRegistry  # noqa: E402
from agents.business_structure_agent import BusinessStructureAgent  # noqa: E402
from agents.coding_agent import CodingAgent, UnitDiff  # noqa: E402
from agents.structure_plan import StructurePlan  # noqa: E402
from background_task_store import BackgroundTaskStore  # noqa: E402
from federated_graph import (  # noqa: E402
    DomainConfig,
    FederatedGraph,
    FederatedInjectManifest,
    build_routed_domain_budgets,
)
from harness.atomicity_check import AtomicityCheck, CheckOutcome  # noqa: E402
from harness.dag_state import DagStateStore, EPCheckpoint  # noqa: E402
from harness.diff_applier import ApplyReport, DiffApplier  # noqa: E402
from harness.verify_gate import VerifyGate, VerifyOutcome, VerifyResult  # noqa: E402
from intent_router import IntentRouter  # noqa: E402
from manifest_parser import enrich_task_from_manifest  # noqa: E402
from memory_writeback import MemoryWriteback  # noqa: E402
from ontology_registry import OntologyRegistry  # noqa: E402
from memory_actions import MemoryActions  # noqa: E402

from phase4.multi_agent_router import Task  # noqa: E402


class EPPhase(str, Enum):
    ANCHOR = "anchor"
    PLAN = "plan"
    EXECUTE = "execute"
    VERIFY = "verify"
    DONE = "done"
    FAILED = "failed"


@dataclass
class EPTurnRecord:
    phase: EPPhase
    agent_name: str = ""
    step_label: str = ""
    tokens: int = 0
    memory_ids: List[str] = field(default_factory=list)
    outcome: str = ""
    rule_id: str = ""
    detail: str = ""


@dataclass
class EPResult:
    ep_id: str
    task_description: str
    status: str = "completed"
    struct_retry: int = 0
    impl_retry: int = 0
    turns: List[EPTurnRecord] = field(default_factory=list)
    writeback_id: Optional[str] = None
    apply_report: Optional[ApplyReport] = None
    diffs: List[UnitDiff] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            f"EP {self.ep_id}: {self.status}",
            f"  struct_retry={self.struct_retry} impl_retry={self.impl_retry}",
            f"  turns={len(self.turns)}",
        ]
        for t in self.turns:
            label = f" [{t.step_label}]" if t.step_label else ""
            extra = f" rule={t.rule_id}" if t.rule_id else ""
            lines.append(
                f"  - {t.phase.value}{label}: {t.agent_name or '-'} "
                f"tokens≈{t.tokens} {t.outcome}{extra}"
            )
        if self.apply_report is not None:
            lines.append(f"  apply: {self.apply_report.summary()}")
        if self.writeback_id:
            lines.append(f"  writeback: {self.writeback_id}")
        return "\n".join(lines)


# Phase 8 专用 scope（仅 BSA + CA）
PHASE8_DEFAULT_SCOPES: Dict[str, AgentMemoryScope] = {
    "BusinessStructureAgent": AgentMemoryScope(
        agent_name="BusinessStructureAgent",
        domains=["code-arch", "purchasing"],
        tiers=["hot", "warm"],
        read_layers=["critical", "rule", "context"],
        write_layers=[],
        budget_multiplier=1.0,
        concept_hints=["architecture", "compliance", "pattern", "idempotency"],
    ),
    "CodingAgent": AgentMemoryScope(
        agent_name="CodingAgent",
        domains=["code-arch"],
        tiers=["hot"],
        read_layers=["critical", "rule", "pattern"],
        write_layers=[],
        budget_multiplier=0.8,
        concept_hints=["idempotency", "procurement", "architecture"],
    ),
}


class EPCoordinator:
    """Phase 8 EP 协调器：Harness + 2 Agent。"""

    MAX_STRUCT_RETRY = 3
    MAX_IMPL_RETRY = 3
    TOKEN_WARN = 800

    def __init__(
        self,
        fed_graph: FederatedGraph,
        domain_configs: List[DomainConfig],
        scope_registry: Optional[AgentMemoryScopeRegistry] = None,
        state_dir: Optional[Path] = None,
        *,
        workspace_root: Optional[Path] = None,
        apply_enabled: bool = True,
        run_pytest: bool = True,
        allowed_write_globs: Optional[List[str]] = None,
        allowed_path_prefixes: Optional[tuple] = None,
    ):
        self.fed_graph = fed_graph
        self.domain_configs = domain_configs
        self.scope_registry = scope_registry or AgentMemoryScopeRegistry(PHASE8_DEFAULT_SCOPES)
        self.workspace_root = Path(
            workspace_root or (DEMOCODE_ROOT / "workspace" / "app")
        ).resolve()
        self.apply_enabled = apply_enabled
        self.intent_router = IntentRouter()
        self.fed_injector = FederatedInjectorWrapper(fed_graph)
        self.atomicity = AtomicityCheck(allowed_prefixes=allowed_path_prefixes)
        self.verify_gate = VerifyGate(
            workspace_root=self.workspace_root,
            run_compile=True,
            run_pytest=run_pytest,
        )
        self.applier = DiffApplier(
            self.workspace_root,
            allowed_globs=allowed_write_globs,
        )
        self.bsa = BusinessStructureAgent()
        self.ca = CodingAgent()
        self.bg_store = BackgroundTaskStore()
        self.state_store = DagStateStore(state_dir or DEMOCODE_ROOT / "workspace" / "ep_state")

        self._actions_by_domain: Dict[str, MemoryActions] = {}
        for d_cfg in domain_configs:
            registry = OntologyRegistry(d_cfg.schema_root)
            self._actions_by_domain[d_cfg.name] = MemoryActions(
                d_cfg.instances_root, registry
            )
        self.writeback = MemoryWriteback(self._actions_by_domain)

    def _ensure_schema_windows(self) -> None:
        for d_cfg in self.domain_configs:
            g = self.fed_graph.get_graph(d_cfg.name)
            if g is None:
                continue
            active_versions = sorted({
                n.schema_version for n in g.all_nodes()
                if n.status == "active"
            })
            if not active_versions:
                active_versions = [1]
            max_v = max(active_versions)
            self.fed_injector.set_schema_window(
                d_cfg.name,
                active_version=max_v,
                compatible_versions=active_versions,
            )

    def _inject_for_agent(
        self,
        agent_name: str,
        task: Task,
        keywords: List[str],
    ) -> FederatedInjectManifest:
        scope = self.scope_registry.for_agent(agent_name)
        route = self.intent_router.route(
            task.description, keywords + scope.concept_hints
        )
        primary_domains = [d for d in scope.domains if d in route.domains] or scope.domains
        domain_budgets = build_routed_domain_budgets(
            self.domain_configs,
            route_domains=primary_domains,
            budget_multiplier=scope.budget_multiplier,
            auxiliary_multiplier=0.5,
        )
        return self.fed_injector.inject(
            task=task.description,
            keywords=keywords + scope.concept_hints + route.concept_hints,
            domain_budgets=domain_budgets,
            domains=scope.domains,
        )

    def _attach_graph(self, task: Task) -> None:
        g = self.fed_graph.get_graph("code-arch")
        if g is not None:
            task.context = task.context or {}
            task.context["_code_arch_graph"] = g

    def run_ep(
        self,
        task: Task,
        keywords: Optional[List[str]] = None,
        dry_run: bool = False,
        ep_id: Optional[str] = None,
        resume: bool = False,
    ) -> EPResult:
        kws = keywords or []
        self._ensure_schema_windows()
        self._attach_graph(task)

        checkpoint = None
        if resume and ep_id:
            checkpoint = self.state_store.load(ep_id)
            if checkpoint is None:
                raise ValueError(f"找不到 EP 状态: {ep_id}")

        ep_id = ep_id or self.state_store.new_ep_id()
        result = EPResult(ep_id=ep_id, task_description=task.description)
        struct_retry = checkpoint.struct_retry if checkpoint else 0
        impl_retry = checkpoint.impl_retry if checkpoint else 0
        completed_units: List[str] = list(checkpoint.completed_units) if checkpoint else []

        # ── 0. 锚定 + IntentRouter ──
        route = self.intent_router.route(task.description, kws)
        task.context = task.context or {}
        task.context["route"] = {"intent": route.intent.value, "domains": route.domains}
        task.context["_workspace_root"] = str(self.workspace_root)
        task.context["_ep_id"] = ep_id
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        result.turns.append(EPTurnRecord(
            phase=EPPhase.ANCHOR,
            agent_name="IntentRouter",
            outcome=f"intent={route.intent.value}",
        ))
        print(f"\n[Harness] 锚定 intent={route.intent.value} domains={route.domains}")

        structure_plan: Optional[StructurePlan] = None

        # ── 外层：Plan（FAIL_STRUCT → BSA replan）──
        while struct_retry <= self.MAX_STRUCT_RETRY:
            injected = self.bg_store.inject_into_context(task)
            if injected:
                self.bg_store.flush()
                print(f"  [bg_store] 注入 {injected} 条后台结果")

            manifest = self._inject_for_agent("BusinessStructureAgent", task, kws)
            enrich_task_from_manifest(task, self.fed_graph, manifest)
            mem_ids = self._collect_memory_ids(manifest)
            tokens = manifest.total_tokens if manifest else 0
            if tokens > self.TOKEN_WARN:
                print(f"  [Harness] token 警告: {tokens} > {self.TOKEN_WARN}")

            bsa_out = self.bsa.plan(task, manifest=manifest)
            structure_plan = self._dict_to_plan(bsa_out.output)

            result.turns.append(EPTurnRecord(
                phase=EPPhase.PLAN,
                agent_name="BusinessStructureAgent",
                step_label=f"struct-retry-{struct_retry}" if struct_retry else "initial",
                tokens=tokens,
                memory_ids=mem_ids,
                outcome="plan_ready",
            ))

            check = self.atomicity.check(structure_plan)
            print(f"\n[Harness] AtomicityCheck: {check.outcome.value} {check.detail or 'OK'}")
            if not check.passed:
                result.turns.append(EPTurnRecord(
                    phase=EPPhase.PLAN,
                    agent_name="AtomicityCheck",
                    outcome=CheckOutcome.FAIL_STRUCT.value,
                    rule_id=check.rule_id,
                    detail=check.detail,
                ))
                struct_retry += 1
                task.context["_struct_retry_done"] = True
                if struct_retry > self.MAX_STRUCT_RETRY:
                    result.status = "failed_struct"
                    result.struct_retry = struct_retry - 1
                    self._save_checkpoint(ep_id, task, "plan", struct_retry, impl_retry, completed_units, structure_plan)
                    return result
                print(f"  → FAIL_STRUCT，BSA replan {struct_retry}/{self.MAX_STRUCT_RETRY}")
                task.context["_struct_feedback"] = check.detail
                completed_units = []
                impl_retry = 0
                continue

            # ── 内层：Execute + Verify（FAIL_IMPL → CA retry）──
            while impl_retry <= self.MAX_IMPL_RETRY:
                if impl_retry > 0:
                    task.context.pop("_force_impl_fail", None)
                all_diffs: List[UnitDiff] = []
                units = structure_plan.unit_order()

                for unit in units:
                    if unit.unit_id in completed_units:
                        print(f"\n[Harness] 跳过已完成 Unit {unit.unit_id}")
                        continue

                    manifest = self._inject_for_agent("CodingAgent", task, kws)
                    enrich_task_from_manifest(task, self.fed_graph, manifest)
                    mem_ids = self._collect_memory_ids(manifest)
                    tokens = manifest.total_tokens if manifest else 0

                    diff = self.ca.execute_unit(
                        unit, task, action=structure_plan.action
                    )
                    all_diffs.append(diff)
                    completed_units.append(unit.unit_id)

                    result.turns.append(EPTurnRecord(
                        phase=EPPhase.EXECUTE,
                        agent_name="CodingAgent",
                        step_label=unit.unit_id,
                        tokens=tokens,
                        memory_ids=mem_ids,
                        outcome=f"diff {diff.lines}L → {diff.target_path}",
                    ))

                result.diffs = list(all_diffs)

                # 1) 内存侧架构/约束校验
                verify = self.verify_gate.verify(all_diffs, task, applied=False)
                print(f"\n[Harness] VerifyGate(memory): {verify.summary()}")

                # 2) 通过后落盘，再做 compile/pytest
                if verify.outcome == VerifyOutcome.PASS and self.apply_enabled and not dry_run:
                    apply_report = self.applier.apply(all_diffs, ep_id=ep_id, dry_run=False)
                    result.apply_report = apply_report
                    print(f"[Harness] DiffApplier: {apply_report.summary()}")
                    result.turns.append(EPTurnRecord(
                        phase=EPPhase.EXECUTE,
                        agent_name="DiffApplier",
                        step_label=f"apply-{impl_retry}" if impl_retry else "apply",
                        outcome="ok" if apply_report.ok else "failed",
                        detail=apply_report.summary(),
                    ))
                    if not apply_report.ok:
                        verify = VerifyResult(
                            outcome=VerifyOutcome.FAIL_IMPL,
                            rule_id="APPLY-001",
                            detail="落盘失败: " + "; ".join(
                                f"{i.target_path}:{i.detail}" for i in apply_report.failed
                            ),
                            violations=[i.detail for i in apply_report.failed],
                        )
                    else:
                        verify = self.verify_gate.verify(
                            all_diffs, task, applied=True, run_pytest_stub=False
                        )
                        print(f"[Harness] VerifyGate(disk): {verify.summary()}")
                        if verify.outcome != VerifyOutcome.PASS:
                            rolled = self.applier.rollback(ep_id)
                            print(f"  [DiffApplier] 验证失败，已回滚 {len(rolled)} 个文件")
                elif verify.outcome == VerifyOutcome.PASS and (dry_run or not self.apply_enabled):
                    apply_report = self.applier.apply(all_diffs, ep_id=ep_id, dry_run=True)
                    result.apply_report = apply_report
                    print(f"[Harness] DiffApplier(dry-run): {apply_report.summary()}")

                result.turns.append(EPTurnRecord(
                    phase=EPPhase.VERIFY,
                    agent_name="VerifyGate",
                    step_label=f"impl-retry-{impl_retry}" if impl_retry else "initial",
                    outcome=verify.outcome.value,
                    rule_id=verify.rule_id,
                    detail=verify.detail,
                ))

                if verify.outcome == VerifyOutcome.PASS:
                    wb_manifest = self._inject_for_agent("BusinessStructureAgent", task, kws)
                    memory_ids = self._collect_memory_ids(wb_manifest)
                    result.writeback_id = self.writeback.record_turn(
                        agent_name="EPCoordinator",
                        write_layers=["rule"],
                        primary_domain="code-arch",
                        task_description=task.description,
                        memory_ids=memory_ids,
                        agent_output={
                            "ep_id": ep_id,
                            "plan_id": structure_plan.plan_id,
                            "status": "pass",
                            "units": [d.unit_id for d in all_diffs],
                            "applied": bool(
                                result.apply_report and result.apply_report.written
                            ),
                        },
                        dry_run=dry_run,
                    )
                    result.status = "completed"
                    result.struct_retry = struct_retry
                    result.impl_retry = impl_retry
                    self._save_checkpoint(ep_id, task, "done", struct_retry, impl_retry, completed_units, structure_plan)
                    return result

                if verify.outcome == VerifyOutcome.FAIL_STRUCT:
                    struct_retry += 1
                    completed_units = []
                    impl_retry = 0
                    task.context["_struct_retry_done"] = True
                    if struct_retry > self.MAX_STRUCT_RETRY:
                        result.status = "failed_struct"
                        result.struct_retry = struct_retry - 1
                        return result
                    print(f"  → FAIL_STRUCT（VerifyGate），BSA replan {struct_retry}/{self.MAX_STRUCT_RETRY}")
                    break

                self.bg_store.submit(
                    "VerifyGate",
                    result={
                        "rule_id": verify.rule_id,
                        "detail": verify.detail,
                        "violations": verify.violations,
                        "command_output": getattr(verify, "command_output", "")[:1500],
                    },
                    label=f"impl-fail-{impl_retry + 1}",
                )
                impl_retry += 1
                completed_units = []
                if impl_retry > self.MAX_IMPL_RETRY:
                    result.status = "failed_impl"
                    result.struct_retry = struct_retry
                    result.impl_retry = impl_retry - 1
                    self._save_checkpoint(ep_id, task, "verify", struct_retry, impl_retry, completed_units, structure_plan)
                    return result
                print(f"  → FAIL_IMPL，CA retry {impl_retry}/{self.MAX_IMPL_RETRY}")
                continue
            else:
                result.status = "failed_impl"
                result.struct_retry = struct_retry
                result.impl_retry = impl_retry
                return result

            continue

        result.status = "failed_struct"
        result.struct_retry = struct_retry
        return result

    def _save_checkpoint(
        self,
        ep_id: str,
        task: Task,
        phase: str,
        struct_retry: int,
        impl_retry: int,
        completed_units: List[str],
        plan: Optional[StructurePlan],
    ) -> None:
        cp = EPCheckpoint(
            ep_id=ep_id,
            phase=phase,
            struct_retry=struct_retry,
            impl_retry=impl_retry,
            completed_units=completed_units,
            plan_id=plan.plan_id if plan else None,
            task_description=task.description,
        )
        path = self.state_store.save(cp)
        print(f"  [DagState] 已保存 checkpoint → {path}")

    @staticmethod
    def _collect_memory_ids(manifest: FederatedInjectManifest) -> List[str]:
        return [
            mid
            for m in manifest.domain_manifests.values()
            for mid in m.memory_ids
        ]

    @staticmethod
    def _dict_to_plan(data: dict) -> StructurePlan:
        from agents.structure_plan import PlanUnit, UnitKind
        units = [
            PlanUnit(
                unit_id=u["unit_id"],
                kind=UnitKind(u["kind"]),
                target_path=u["target_path"],
                description=u.get("description", ""),
                depends_on=u.get("depends_on", []),
                pattern_ids=u.get("pattern_ids", []),
                constraint_ids=u.get("constraint_ids", []),
            )
            for u in data.get("units", [])
        ]
        return StructurePlan(
            plan_id=data.get("plan_id", ""),
            action=data.get("action", ""),
            units=units,
            rationale=data.get("rationale", ""),
            derived_from=data.get("derived_from", []),
        )


class FederatedInjectorWrapper:
    """薄包装 phase6 FederatedInjector，便于 EP 内调用。"""

    def __init__(self, fed_graph: FederatedGraph):
        from federated_graph import FederatedInjector
        self._inj = FederatedInjector(fed_graph)

    def inject(self, **kwargs):
        return self._inj.inject(**kwargs)

    def set_schema_window(self, *args, **kwargs):
        return self._inj.set_schema_window(*args, **kwargs)
