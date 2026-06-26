"""
memory_aware_coordinator — Layer 5 × Layer 4 联动协调器（Phase 7）

P0：per-Agent InjectManifest + execute + writeback
P1：Plan Mode + manifest 解析 + Sim 制衡重试 + CoderAgent + wake 语义
"""

from __future__ import annotations

import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

DEMOCODE_ROOT = Path(__file__).parent.parent
PHASE6 = DEMOCODE_ROOT / "phase6"
sys.path.insert(0, str(PHASE6))
sys.path.insert(0, str(DEMOCODE_ROOT / "phase7"))
sys.path.insert(0, str(DEMOCODE_ROOT))

from agent_memory_scope import AgentMemoryScope, AgentMemoryScopeRegistry  # noqa: E402
from federated_graph import (  # noqa: E402
    DomainConfig,
    FederatedGraph,
    FederatedInjector,
    FederatedInjectManifest,
    build_routed_domain_budgets,
)
from intent_router import IntentRouter, RouteConfig  # noqa: E402
from memory_actions import MemoryActions  # noqa: E402
from memory_aware_agents import ManifestAwareAgent  # noqa: E402
from memory_writeback import MemoryWriteback  # noqa: E402
from ontology_registry import OntologyRegistry  # noqa: E402

from phase4.agent_coordinator import AgentCoordinator  # noqa: E402
from phase4.multi_agent_router import Task  # noqa: E402


class WakeMode(str, Enum):
    """对标 Codex send_message (queue-only) vs followup_task (trigger-turn)。"""
    QUEUE_ONLY = "queue_only"
    TRIGGER_TURN = "trigger_turn"


@dataclass
class AgentTurnRecord:
    agent_name: str
    scope: AgentMemoryScope
    route: RouteConfig
    manifest: Optional[FederatedInjectManifest] = None
    agent_output: Any = None
    writeback_id: Optional[str] = None
    wake_mode: Optional[WakeMode] = None
    step_label: str = ""


@dataclass
class CoordinatorResult:
    task_description: str
    execution_order: List[str]
    turns: List[AgentTurnRecord] = field(default_factory=list)
    status: str = "completed"
    retry_count: int = 0

    def summary(self) -> str:
        lines = [
            f"任务: {self.task_description[:60]}",
            f"状态: {self.status}  重试: {self.retry_count}",
            f"DAG 顺序: {' → '.join(self.execution_order)}",
            f"回合数: {len(self.turns)}",
        ]
        for t in self.turns:
            n_mem = t.manifest.total_memories if t.manifest else 0
            n_tok = t.manifest.total_tokens if t.manifest else 0
            wb = f" writeback={t.writeback_id}" if t.writeback_id else ""
            wake = f" wake={t.wake_mode.value}" if t.wake_mode else ""
            label = f" ({t.step_label})" if t.step_label else ""
            st = ""
            if t.agent_output is not None:
                st = f" status={getattr(t.agent_output, 'status', '?')}"
            lines.append(
                f"  [{t.agent_name}]{label} intent={t.route.intent.value} "
                f"memories={n_mem} tokens≈{n_tok}{st}{wb}{wake}"
            )
        return "\n".join(lines)


class MemoryAwareRouter:
    """包装 MultiAgentRouter，execute 时传入 manifest。"""

    def __init__(self, router, wrapped_agents: Dict[str, ManifestAwareAgent]):
        self.router = router
        self.wrapped_agents = wrapped_agents

    def execute_agent(
        self,
        agent_name: str,
        task: Task,
        manifest: Optional[FederatedInjectManifest] = None,
    ):
        agent = self.wrapped_agents.get(agent_name)
        if agent is None:
            return self.router.execute_agent(agent_name, task)
        return agent.execute(task, self.router, manifest=manifest)


class MemoryAwareCoordinator:
    DAG_AGENTS = ["IntentAgent", "OntologyAgent", "SimAgent"]
    FULL_DAG_AGENTS = ["IntentAgent", "OntologyAgent", "SimAgent", "CoderAgent"]
    MAX_RETRY = 3

    def __init__(
        self,
        fed_graph: FederatedGraph,
        domain_configs: List[DomainConfig],
        scope_registry: Optional[AgentMemoryScopeRegistry] = None,
        plan_dir: Optional[Path] = None,
    ):
        self.fed_graph = fed_graph
        self.domain_configs = domain_configs
        self.scope_registry = scope_registry or AgentMemoryScopeRegistry()
        self.intent_router = IntentRouter()
        self.fed_injector = FederatedInjector(fed_graph)
        self.coordinator = AgentCoordinator(router=None)
        self.plan_dir = Path(plan_dir) if plan_dir else None
        if self.plan_dir:
            self.plan_dir.mkdir(parents=True, exist_ok=True)

        self._actions_by_domain: Dict[str, MemoryActions] = {}
        for d_cfg in domain_configs:
            registry = OntologyRegistry(d_cfg.schema_root)
            self._actions_by_domain[d_cfg.name] = MemoryActions(
                d_cfg.instances_root, registry
            )
        self.writeback = MemoryWriteback(self._actions_by_domain)

    def build_execution_order(self, include_coder: bool = False) -> List[str]:
        agents = self.FULL_DAG_AGENTS if include_coder else self.DAG_AGENTS
        order: List[str] = []
        visited = set()

        def dfs(name: str) -> None:
            if name in visited:
                return
            visited.add(name)
            for dep in self.coordinator.AGENT_DEPENDENCIES.get(name, []):
                dfs(dep)
            order.append(name)

        for a in agents:
            dfs(a)
        return order

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
    ) -> AgentTurnRecord:
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

        manifest = self.fed_injector.inject(
            task=task.description,
            keywords=keywords + scope.concept_hints + route.concept_hints,
            domain_budgets=domain_budgets,
            domains=scope.domains,
        )

        return AgentTurnRecord(
            agent_name=agent_name,
            scope=scope,
            route=route,
            manifest=manifest,
        )

    def _build_memory_router(self, router, agent_names: List[str]) -> MemoryAwareRouter:
        wrapped = {
            name: ManifestAwareAgent(router._agents[name], fed_graph=self.fed_graph)
            for name in agent_names
            if name in router._agents
        }
        return MemoryAwareRouter(router, wrapped)

    def _attach_code_arch_graph(self, task: Task) -> None:
        g = self.fed_graph.get_graph("code-arch")
        if g is not None:
            task.context = task.context or {}
            task.context["_code_arch_graph"] = g

    def _execute_turn(
        self,
        agent_name: str,
        task: Task,
        keywords: List[str],
        memory_router: MemoryAwareRouter,
        dry_run: bool,
        wake_mode: Optional[WakeMode] = None,
        step_label: str = "",
    ) -> AgentTurnRecord:
        turn = self._inject_for_agent(agent_name, task, keywords)
        turn.wake_mode = wake_mode
        turn.step_label = step_label

        turn.agent_output = memory_router.execute_agent(
            agent_name, task, manifest=turn.manifest
        )
        memory_ids = [
            mid
            for m in (turn.manifest.domain_manifests.values() if turn.manifest else [])
            for mid in m.memory_ids
        ]
        primary_domain = turn.scope.domains[0]
        turn.writeback_id = self.writeback.record_turn(
            agent_name=agent_name,
            write_layers=turn.scope.write_layers,
            primary_domain=primary_domain,
            task_description=task.description,
            memory_ids=memory_ids,
            agent_output=getattr(turn.agent_output, "output", turn.agent_output),
            dry_run=dry_run,
        )
        return turn

    def plan(
        self,
        task: Task,
        keywords: Optional[List[str]] = None,
        include_coder: bool = True,
        persist: bool = True,
    ) -> str:
        """Plan Mode：各 Agent scope + InjectManifest 预览，不执行 Agent。"""
        kws = keywords or []
        self._ensure_schema_windows()
        order = self.build_execution_order(include_coder=include_coder)
        plan_id = f"plan-{uuid.uuid4().hex[:6]}"

        lines = [
            f"# 执行计划 {plan_id}",
            f"创建时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "## 任务描述",
            task.description,
            "",
            "## DAG 步骤与记忆 scope 预览",
        ]

        for i, agent_name in enumerate(order, 1):
            deps = self.coordinator.AGENT_DEPENDENCIES.get(agent_name, [])
            dep_str = f"（依赖：{', '.join(deps)}）" if deps else ""
            turn = self._inject_for_agent(agent_name, task, kws)
            scope = turn.scope
            lines.append(f"### Step {i}. {agent_name}{dep_str}")
            lines.append(f"- scope: {scope.summary()}")
            lines.append(f"- route: intent={turn.route.intent.value} domains={turn.route.domains}")
            if turn.manifest:
                for dom, m in turn.manifest.domain_manifests.items():
                    ids_preview = m.memory_ids[:6]
                    suffix = "..." if len(m.memory_ids) > 6 else ""
                    lines.append(
                        f"- inject[{dom}]: {len(m.memory_ids)} 条 "
                        f"tokens≈{m.estimated_tokens} ids={ids_preview}{suffix}"
                    )
            lines.append("")

        lines += [
            "## 终止条件",
            f"- 成功：SimAgent 通过" + (" → CoderAgent 校验通过" if include_coder else ""),
            f"- 失败：OntologyAgent 重试超过 {self.MAX_RETRY} 次",
            "",
            "## Wake 语义（P1）",
            "- SimAgent 拒绝 → queue-only 写回 feedback，trigger-turn 唤醒 OntologyAgent",
            "- SimAgent 通过 → trigger-turn 唤醒 CoderAgent",
        ]

        plan_text = "\n".join(lines)
        if persist and self.plan_dir:
            path = self.plan_dir / f"{plan_id}.md"
            path.write_text(plan_text, encoding="utf-8")
            print(f"  [Plan Mode] 计划已写入：{path}")
        return plan_text

    def run(
        self,
        task: Task,
        keywords: Optional[List[str]] = None,
        inject_only: bool = True,
        router: Any = None,
        dry_run: bool = False,
        full_dag: bool = False,
    ) -> CoordinatorResult:
        if full_dag and router is not None:
            return self.run_full_dag(task, keywords, router, dry_run=dry_run)

        kws = keywords or []
        self._ensure_schema_windows()
        order = self.build_execution_order(include_coder=False)
        result = CoordinatorResult(task_description=task.description, execution_order=order)

        memory_router = None
        if router is not None and not inject_only:
            memory_router = self._build_memory_router(router, order)

        for agent_name in order:
            turn = self._inject_for_agent(agent_name, task, kws)

            if memory_router is not None:
                turn.agent_output = memory_router.execute_agent(
                    agent_name, task, manifest=turn.manifest
                )
                memory_ids = [
                    mid
                    for m in (turn.manifest.domain_manifests.values() if turn.manifest else [])
                    for mid in m.memory_ids
                ]
                primary_domain = turn.scope.domains[0]
                turn.writeback_id = self.writeback.record_turn(
                    agent_name=agent_name,
                    write_layers=turn.scope.write_layers,
                    primary_domain=primary_domain,
                    task_description=task.description,
                    memory_ids=memory_ids,
                    agent_output=getattr(turn.agent_output, "output", turn.agent_output),
                    dry_run=dry_run,
                )

            result.turns.append(turn)

        if not dry_run and not inject_only:
            self.fed_graph.load()

        return result

    def run_full_dag(
        self,
        task: Task,
        keywords: Optional[List[str]] = None,
        router: Any = None,
        dry_run: bool = False,
    ) -> CoordinatorResult:
        """
        P1 完整 DAG：Intent → Ontology → Sim（可重试）→ Coder。
        Sim 拒绝时 queue-only 写 feedback，trigger-turn 重跑 Ontology。
        """
        kws = keywords or []
        self._ensure_schema_windows()
        self._attach_code_arch_graph(task)
        order = self.build_execution_order(include_coder=True)
        result = CoordinatorResult(task_description=task.description, execution_order=order)

        agent_names = [a for a in order if a in router._agents]
        memory_router = self._build_memory_router(router, agent_names)

        # Step 1: IntentAgent
        turn = self._execute_turn(
            "IntentAgent", task, kws, memory_router, dry_run,
            wake_mode=WakeMode.TRIGGER_TURN, step_label="initial",
        )
        result.turns.append(turn)
        task.context = task.context or {}
        task.context["intent"] = turn.agent_output.output

        retry_count = 0
        sim_passed = False

        while retry_count <= self.MAX_RETRY:
            # OntologyAgent
            label = "initial" if retry_count == 0 else f"retry-{retry_count}"
            turn = self._execute_turn(
                "OntologyAgent", task, kws, memory_router, dry_run,
                wake_mode=WakeMode.TRIGGER_TURN if retry_count else WakeMode.TRIGGER_TURN,
                step_label=label,
            )
            result.turns.append(turn)
            task.context["proposal"] = turn.agent_output.output

            # SimAgent
            turn = self._execute_turn(
                "SimAgent", task, kws, memory_router, dry_run,
                wake_mode=WakeMode.TRIGGER_TURN,
                step_label=label,
            )
            result.turns.append(turn)

            if turn.agent_output.status == "completed":
                sim_passed = True
                break

            if turn.agent_output.status == "rejected":
                # queue-only：feedback 入 context，不立即执行下游
                task.feedback = turn.agent_output.reason
                task.context["sim_feedback"] = turn.agent_output.reason
                turn.wake_mode = WakeMode.QUEUE_ONLY
                retry_count += 1
                if retry_count > self.MAX_RETRY:
                    result.status = "failed"
                    result.retry_count = retry_count - 1
                    return result
                print(
                    f"\n  → SimAgent 拒绝（queue-only feedback），"
                    f"trigger-turn Ontology 重试 {retry_count}/{self.MAX_RETRY}"
                )
                continue

            break

        if not sim_passed:
            result.status = "failed"
            result.retry_count = retry_count
            return result

        result.retry_count = retry_count if sim_passed else max(0, retry_count - 1)

        # CoderAgent（Sim 通过后 trigger-turn）
        if "CoderAgent" in router._agents:
            turn = self._execute_turn(
                "CoderAgent", task, kws, memory_router, dry_run,
                wake_mode=WakeMode.TRIGGER_TURN,
                step_label="post-sim",
            )
            result.turns.append(turn)
            if turn.agent_output.status == "rejected":
                result.status = "coder_failed"

        if not dry_run:
            self.fed_graph.load()

        return result
