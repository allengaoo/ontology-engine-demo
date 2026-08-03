"""
CodingAgent (CA) — 按 Unit 生成完整文件内容

有 LLM 时由模型生成；DEMOCODE_ALLOW_STUB=0（默认）时禁止 stub fallback。
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

IFCLUB_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(IFCLUB_ROOT))

from agents.code_context import extract_exports_summary, format_generated_so_far
from agents.structure_plan import PlanUnit, UnitKind
from code_validator import CodeValidator
from llm_chat import chat_complete, format_manifest_for_prompt, is_llm_available

from core.task import AgentResult, Task


_CA_SYSTEM = """你是 CodingAgent（CA），只为单个 Unit 生成完整源码（不是 diff）。
硬性要求（小模型友好）：
1) 只输出纯代码，不要 markdown 围栏，不要解释
2) import 包名必须与目标路径一致：meeting_order 目标只用 from meeting_order...
3) 写码前自检：每个 from/import 的模块与符号必须出现在「上游签名 / 依赖文件 / 磁盘现有内容」中；
   不存在就不要 invent（禁止 BaseRoomRepository、repositories.booking 等臆造）
4) 命名：文件/模块 snake_case；类 PascalCase；函数/变量 snake_case；会议域仓储只用 MeetingRepository + SqliteRepository
5) 长度：单文件尽量 ≤220 行；只做本 Unit 描述的一件事
6) 字段写死：Room(id,name,capacity,is_active)；Booking(id,room_id,title,booker,start_at,end_at)
7) 若提供「磁盘/scratch 现有内容」，在其上修改，不要无关重写；禁止改未点名的其他文件内容
8) domain 规矩纯函数禁访问 db；编排经 services；存取经 factory.get_repository/init_db
9) 兼容 Python 3.9；CreateBookingRequest 不要当错误的 response_model
10) 前端：禁止 @/；API 前缀 /api/v1；每轮只改当前 Unit 目标文件
"""


def allow_stub() -> bool:
    val = os.environ.get("DEMOCODE_ALLOW_STUB", "0").strip().lower()
    return val in ("1", "true", "yes", "on")


@dataclass
class UnitDiff:
    unit_id: str
    target_path: str
    code: str
    lines: int = 0

    def __post_init__(self) -> None:
        self.lines = len(self.code.splitlines())


@dataclass
class CodingResult:
    diffs: List[UnitDiff] = field(default_factory=list)

    def all_code(self) -> str:
        return "\n\n".join(d.code for d in self.diffs)


class CodingAgent:
    """Coding Agent — Execute 阶段"""

    name = "CodingAgent"

    def execute_unit(
        self,
        unit: PlanUnit,
        task: Task,
        action: str = "",
    ) -> UnitDiff:
        print(f"\n[{self.name}] 执行 Unit {unit.unit_id}: {unit.target_path}")
        force_impl_fail = task.context.get("_force_impl_fail") and unit.unit_id == "u1"
        if force_impl_fail and not is_llm_available():
            if not allow_stub():
                raise RuntimeError("force_impl_fail 需要 stub，但 DEMOCODE_ALLOW_STUB=0")
            code = self._generate_code_stub(unit, action, force_violation=True)
        else:
            code = self._generate_with_llm(unit, task, action, force_impl_fail)
            if code is None:
                if allow_stub():
                    print("  ⚠ LLM 不可用，使用 stub（DEMOCODE_ALLOW_STUB=1）")
                    code = self._generate_code_stub(
                        unit, action, force_violation=force_impl_fail
                    )
                else:
                    raise RuntimeError(
                        f"LLM 未能生成 {unit.target_path}，且 stub 已禁用"
                        "（设置 DEMOCODE_ALLOW_STUB=1 可临时放开）"
                    )
            else:
                print("  [LLM] 代码由大模型生成")

        err = self._validate_generated_code(unit.target_path, code, task)
        if err:
            raise RuntimeError(err)
        print(f"  生成代码：{len(code.splitlines())} 行")
        return UnitDiff(unit_id=unit.unit_id, target_path=unit.target_path, code=code)

    @staticmethod
    def _validate_generated_code(target_path: str, code: str, task: Task) -> Optional[str]:
        """小模型专用：生成后立刻拦路径/符号/命名/长度，避免落到 Verify 才失败。"""
        path = (target_path or "").replace("\\", "/")
        ws = str((task.context or {}).get("_workspace_root") or "")
        is_meeting = "meeting_order" in path or "meeting_order" in ws
        if not is_meeting:
            return None
        if re.search(r"(^|/)backend/src/repositories(/|$)", path):
            return (
                f"会议域禁止写入 {path}；必须写到 "
                "backend/src/meeting_order/repositories/"
            )
        # 禁符号/命名/长度/导入检查只对代码文件生效；.md 文档里提到
        # BaseRepository（如写"禁止用 BaseRepository"经验）是合法散文，不能误判。
        is_code = path.endswith((".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"))
        if not is_code:
            return None
        for bad in (
            "BaseRoomRepository",
            "BaseBookingRepository",
            "BaseRepository",
            "repositories.booking",
            "repositories.room",
            "SQLiteRoomRepository",
            "SQLiteBookingRepository",
        ):
            if bad in code:
                return (
                    f"{path}: 禁止臆造符号/路径 {bad!r}；"
                    "只用 MeetingRepository + SqliteRepository + get_repository/init_db"
                )
        if path.endswith(".py") and code.count("\n") + 1 > 220:
            return f"{path}: 单文件超过 220 行，请拆成更小 EP"
        camel_defs = re.findall(r"^\s*def\s+([A-Z][A-Za-z0-9_]*)\s*\(", code, flags=re.M)
        if camel_defs:
            return f"{path}: 函数名必须 snake_case，发现 {camel_defs[:3]}"
        return None

    def execute_unit_result(
        self,
        unit: PlanUnit,
        task: Task,
        action: str = "",
    ) -> AgentResult:
        try:
            diff = self.execute_unit(unit, task, action=action)
        except RuntimeError as exc:
            return AgentResult(status="failed", output={"error": str(exc)})
        return AgentResult(
            status="completed",
            output={
                "unit_id": diff.unit_id,
                "target_path": diff.target_path,
                "code": diff.code,
            },
        )

    def _generate_with_llm(
        self,
        unit: PlanUnit,
        task: Task,
        action: str,
        force_violation: bool,
    ) -> Optional[str]:
        if force_violation:
            return None
        ctx = task.context or {}
        prior = format_generated_so_far(list(ctx.get("_generated_so_far") or []))
        existing = self._load_existing_source(unit.target_path, ctx)
        related = self._load_related_sources(unit.target_path, ctx)
        upstream = ctx.get("_upstream_signatures") or ""
        anti_hint = ctx.get("_recent_anti_hint") or ""
        verify_hint = self._format_verify_feedback(ctx)
        exports = ""
        if getattr(unit, "exports", None):
            exports = f"本 Unit 须导出/实现：{unit.exports}\n"
        frozen = ctx.get("_frozen_prefixes") or []

        user = (
            f"任务：{task.description}\n"
            f"StructurePlan action：{action}\n"
            f"本 Unit：{unit.to_dict() if hasattr(unit, 'to_dict') else unit}\n"
            f"{exports}"
            f"目标路径：{unit.target_path}\n"
            f"freeze 前缀（禁止写入）：{frozen}\n"
            f"\n## 上游签名（只读，必须对齐）\n{upstream or '（无）'}\n"
            f"\n## 本 EP 已生成文件（必须对齐 API）\n{prior}\n"
            f"\n## 磁盘/scratch 现有内容（若有则基于此修改）\n{existing or '（无）'}\n"
            f"\n## 依赖文件（只读）\n{related or '（无）'}\n"
            f"\n## 近期失败避坑（ANTI）\n{anti_hint or '（无）'}\n"
            f"\n## ConstraintMemory\n{format_manifest_for_prompt(ctx)}\n"
            f"{verify_hint}"
        )
        try:
            raw = chat_complete(_CA_SYSTEM, user, max_tokens=4096)
            if not raw:
                return None
            return self._strip_code_fence(raw)
        except Exception as exc:
            print(f"  ⚠ LLM 代码生成失败: {exc}")
            return None

    @staticmethod
    def _format_verify_feedback(ctx: dict) -> str:
        detail = ctx.get("_last_verify_feedback")
        if isinstance(detail, dict):
            out = detail.get("command_output") or ""
            return (
                "\n## VerifyGate 上轮失败（必须修复）\n"
                f"rule={detail.get('rule_id')} detail={detail.get('detail')}\n"
                f"violations={detail.get('violations')}\n"
                f"pytest/compile 输出：\n{out[:6000]}\n"
            )
        bg = ctx.get("_bg_results") or []
        if not bg:
            return ""
        last = bg[-1].get("result")
        return f"\n## VerifyGate 上轮失败（须修正）\n{last}\n"

    @staticmethod
    def _load_existing_source(target_path: str, ctx: dict) -> str:
        rel = (target_path or "").replace("\\", "/").lstrip("./")
        roots: List[Path] = []
        scratch = ctx.get("_scratch_root")
        if scratch:
            roots.append(Path(scratch))
        ws = ctx.get("_workspace_root")
        if ws:
            roots.append(Path(ws))
        for root in roots:
            cand = root / rel
            if cand.is_file():
                try:
                    text = cand.read_text(encoding="utf-8")
                except OSError:
                    continue
                if len(text) > 6000:
                    text = text[:3000] + "\n…\n" + text[-2500:]
                src = "scratch" if scratch and str(root) == scratch else "workspace"
                return f"(from {src}) {rel}\n{text}"
        return ""

    @classmethod
    def _load_related_sources(cls, target_path: str, ctx: dict) -> str:
        """为 domain/api/tests 注入已有 models/rules 签名，避免发明字段。"""
        rel = (target_path or "").replace("\\", "/").lstrip("./")
        if not any(
            p in rel
            for p in (
                "domain/",
                "api/",
                "services/",
                "schemas/",
                "repositories/",
                "tests/",
                "scheduler",
                "main.py",
            )
        ):
            return ""
        deps = [
            "backend/src/meeting_order/models/room.py",
            "backend/src/meeting_order/models/booking.py",
            "backend/src/meeting_order/schemas/booking.py",
            "backend/src/meeting_order/domain/rules.py",
            "backend/src/meeting_order/repositories/base.py",
            "backend/src/meeting_order/repositories/factory.py",
            "backend/src/meeting_order/repositories/sqlite_repo.py",
            "backend/src/meeting_order/config.py",
        ]
        chunks: List[str] = []
        for dep in deps:
            if dep == rel:
                continue
            text = cls._load_existing_source(dep, ctx)
            if text:
                chunks.append(text)
        return "\n\n".join(chunks[:5])

    @staticmethod
    def _strip_code_fence(text: str) -> str:
        text = text.strip()
        # 语言标签须含 typescript（仅写 ts 时，```typescript 会把 typescript 留进正文）
        m = re.search(
            r"```(?:typescript|tsx|python|javascript|jsx|ts|js)?\s*\n?([\s\S]*?)```",
            text,
        )
        if m:
            text = m.group(1).strip()
        else:
            # 无闭合 fence 时：去掉开头单独一行的语言名
            text = re.sub(
                r"^(?:typescript|tsx|python|javascript|jsx|ts|js)\s*\n",
                "",
                text,
                count=1,
                flags=re.IGNORECASE,
            ).strip()
        # 再防一层：正文首行误留 language tag
        text = re.sub(
            r"^(?:typescript|tsx|python|javascript|jsx|ts|js)\s*\n",
            "",
            text,
            count=1,
            flags=re.IGNORECASE,
        )
        return text.strip()

    def validate_diffs(
        self,
        diffs: List[UnitDiff],
        task: Task,
    ) -> Optional[str]:
        for diff in diffs:
            path = (diff.target_path or "").replace("\\", "/")
            if "frontend/" in path and ("\"@/" in diff.code or "'@/" in diff.code):
                return "FE-ALIAS: 前端禁止 @/ 别名，请改用相对路径 import"
        graph = task.context.get("_code_arch_graph")
        if graph is None:
            return None
        validator = CodeValidator(graph)
        for diff in diffs:
            report = validator.validate(diff.code, file_path=diff.target_path)
            print(f"  CodeValidator[{diff.unit_id}]: {report.summary()}")
            if not report.passed:
                v = report.violations[0]
                return f"{v.rule or v.memory_id}: {v.detail}"
        return None

    def _generate_code_stub(
        self,
        unit: PlanUnit,
        action: str,
        force_violation: bool = False,
    ) -> str:
        if unit.kind == UnitKind.TEST:
            return (
                '"""stub test"""\n'
                "def test_stub():\n"
                "    assert True\n"
            )
        if force_violation:
            return (
                "from infrastructure.kafka_producer import send_event\n\n"
                "def bad():\n"
                "    send_event({})\n"
            )
        return f"# stub for {unit.target_path}\npass\n"


def summarize_diff_for_context(diff: UnitDiff) -> Dict[str, str]:
    return {
        "path": diff.target_path,
        "code": diff.code,
        "summary": extract_exports_summary(diff.code),
    }
