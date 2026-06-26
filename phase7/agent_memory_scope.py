"""
agent_memory_scope — Agent × Domain × Tier × RW 权限表（Phase 7）

把 Phase 4 的 Agent 权限矩阵映射到 Phase 6 的联邦记忆 scope。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class AgentMemoryScope:
    """单个 Agent 在本轮可访问的记忆范围"""
    agent_name: str
    domains: List[str]
    tiers: List[str]
    read_layers: List[str] = field(default_factory=list)
    write_layers: List[str] = field(default_factory=list)
    budget_multiplier: float = 1.0
    concept_hints: List[str] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"{self.agent_name}: domains={self.domains} tiers={self.tiers} "
            f"read={self.read_layers} write={self.write_layers} budget×{self.budget_multiplier}"
        )


# Phase 4 Agent → Phase 6 联邦记忆 scope
DEFAULT_AGENT_SCOPES: Dict[str, AgentMemoryScope] = {
    "IntentAgent": AgentMemoryScope(
        agent_name="IntentAgent",
        domains=["purchasing"],
        tiers=["hot", "warm"],
        read_layers=["context"],
        write_layers=["context"],
        budget_multiplier=0.8,
        concept_hints=["procurement", "vendor"],
    ),
    "OntologyAgent": AgentMemoryScope(
        agent_name="OntologyAgent",
        domains=["code-arch", "purchasing"],
        tiers=["hot", "warm"],
        read_layers=["critical", "rule", "context"],
        write_layers=["rule"],
        budget_multiplier=1.0,
        concept_hints=["architecture", "compliance", "pattern"],
    ),
    "SimAgent": AgentMemoryScope(
        agent_name="SimAgent",
        domains=["purchasing"],
        tiers=["hot"],
        read_layers=["critical", "rule"],
        write_layers=["context"],
        budget_multiplier=0.6,
        concept_hints=["compliance", "vendor"],
    ),
    "CoderAgent": AgentMemoryScope(
        agent_name="CoderAgent",
        domains=["code-arch", "purchasing"],
        tiers=["hot", "warm"],
        read_layers=["critical", "rule", "pattern"],
        write_layers=[],
        budget_multiplier=1.0,
        concept_hints=["idempotency", "procurement", "architecture"],
    ),
}


class AgentMemoryScopeRegistry:
    """查询 / 覆盖 Agent 记忆 scope"""

    def __init__(self, scopes: Optional[Dict[str, AgentMemoryScope]] = None):
        self._scopes = dict(scopes or DEFAULT_AGENT_SCOPES)

    def for_agent(self, agent_name: str) -> AgentMemoryScope:
        if agent_name not in self._scopes:
            raise KeyError(f"未注册 Agent scope: {agent_name}")
        return self._scopes[agent_name]

    def list_agents(self) -> List[str]:
        return list(self._scopes.keys())
