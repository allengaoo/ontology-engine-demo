"""从 ifclubdemo 主链压缩出的可运行示例。

运行：
    python3 ifclubdemo_ontology_fs.py

它不调用真实模型。coding_agent() 代替一次模型调用，目的是只展示：
OntologyFS -> InjectManifest -> Agent -> VerifyGate -> writeback。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Callable


@dataclass(frozen=True)
class MemoryObject:
    id: str
    kind: str
    domain: str
    concepts: tuple[str, ...]
    text: str


@dataclass(frozen=True)
class AgentMemoryScope:
    domains: tuple[str, ...]
    kinds: tuple[str, ...]
    max_items: int = 4


@dataclass(frozen=True)
class InjectManifest:
    memory_ids: tuple[str, ...]
    context_text: str


class OntologyFS:
    """以有类型对象保存约束、模式、反模式和决策。"""

    def __init__(self, objects: list[MemoryObject]) -> None:
        self._objects = {obj.id: obj for obj in objects}

    def inject(
        self, scope: AgentMemoryScope, concept_hints: set[str]
    ) -> InjectManifest:
        candidates = [
            obj
            for obj in self._objects.values()
            if obj.domain in scope.domains
            and obj.kind in scope.kinds
            and concept_hints.intersection(obj.concepts)
        ]
        priority = {"Constraint": 0, "AntiPattern": 1, "Pattern": 2, "Decision": 3}
        candidates.sort(key=lambda obj: (priority[obj.kind], obj.id))
        selected = candidates[: scope.max_items]
        return InjectManifest(
            memory_ids=tuple(obj.id for obj in selected),
            context_text="\n".join(
                f"[{obj.id}][{obj.kind}] {obj.text}" for obj in selected
            ),
        )

    def writeback(self, obj: MemoryObject) -> None:
        self._objects[obj.id] = obj


@dataclass(frozen=True)
class UnitDiff:
    target_path: str
    content: str


class VerifyGate:
    """确定性门禁；不再调用另一个模型做自我评价。"""

    ALLOWED_PREFIX = "backend/src/meeting_order/domain/"

    def check(self, diff: UnitDiff) -> list[str]:
        failures: list[str] = []
        if not diff.target_path.startswith(self.ALLOWED_PREFIX):
            failures.append("CN-PATH: 本轮只能修改 domain 目录")
        if "def check_no_overlap(" not in diff.content:
            failures.append("CN-SIGNATURE: 缺少 check_no_overlap")
        if "HTTPException" in diff.content:
            failures.append("ANTI-LAYER: domain 不得依赖 HTTP 层")
        return failures


class Harness:
    def __init__(self, ontology: OntologyFS, root: Path) -> None:
        self.ontology = ontology
        self.root = root.resolve()
        self.gate = VerifyGate()

    def run_ep(
        self,
        task: str,
        agent: Callable[[str, InjectManifest], UnitDiff],
    ) -> bool:
        scope = AgentMemoryScope(
            domains=("domain", "code-arch"),
            kinds=("Constraint", "AntiPattern", "Pattern", "Decision"),
        )
        manifest = self.ontology.inject(
            scope, {"booking", "overlap", "domain"}
        )
        print("inject:", manifest.memory_ids)

        proposal = agent(task, manifest)
        failures = self.gate.check(proposal)
        if failures:
            self.ontology.writeback(
                MemoryObject(
                    id="ANTI-EP-001",
                    kind="AntiPattern",
                    domain="code-arch",
                    concepts=("booking", "domain"),
                    text="；".join(failures),
                )
            )
            print("rejected:", failures)
            return False

        target = (self.root / proposal.target_path).resolve()
        if not target.is_relative_to(self.root):
            raise ValueError("resolved path escapes workspace")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(proposal.content, encoding="utf-8")

        self.ontology.writeback(
            MemoryObject(
                id="DEC-EP-001",
                kind="Decision",
                domain="domain",
                concepts=("booking", "overlap"),
                text=f"已通过门禁并写入 {proposal.target_path}",
            )
        )
        print("written:", target.relative_to(self.root))
        return True


def coding_agent(task: str, manifest: InjectManifest) -> UnitDiff:
    """真实项目在这里调用编码模型；示例返回一份候选完整文件。"""
    assert "CN-OVERLAP" in manifest.memory_ids
    return UnitDiff(
        target_path="backend/src/meeting_order/domain/rules.py",
        content='''from datetime import datetime


def check_no_overlap(
    start_at: datetime,
    end_at: datetime,
    existing: list[tuple[datetime, datetime]],
) -> bool:
    """首尾相接允许；真正相交时返回 False。"""
    return all(end_at <= old_start or start_at >= old_end
               for old_start, old_end in existing)
''',
    )


def main() -> None:
    ontology = OntologyFS(
        [
            MemoryObject(
                "CN-OVERLAP",
                "Constraint",
                "domain",
                ("booking", "overlap"),
                "同一房间的预订不得重叠；首尾相接允许。",
            ),
            MemoryObject(
                "CN-DOMAIN-PURE",
                "Constraint",
                "code-arch",
                ("domain", "booking"),
                "domain 只能写纯函数，不得依赖 FastAPI。",
            ),
            MemoryObject(
                "PAT-REPOSITORY",
                "Pattern",
                "code-arch",
                ("repository",),
                "持久化只能经过 MeetingRepository。",
            ),
        ]
    )

    with TemporaryDirectory() as workspace:
        harness = Harness(ontology, Path(workspace))
        assert harness.run_ep("实现会议室预订时间冲突检查", coding_agent)

        next_manifest = ontology.inject(
            AgentMemoryScope(
                ("domain", "code-arch"),
                ("Constraint", "Decision"),
                max_items=8,
            ),
            {"booking", "overlap", "domain"},
        )
        assert "DEC-EP-001" in next_manifest.memory_ids
        print("next inject:", next_manifest.memory_ids)


if __name__ == "__main__":
    main()
