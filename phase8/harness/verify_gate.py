"""
verify_gate — 三路判定：PASS / FAIL_IMPL / FAIL_STRUCT（Phase 8 Harness）

1) ConstraintMemory / CodeValidator（内存）
2) compileall（落盘后）
3) 真实 pytest（落盘后，可配置）
"""

from __future__ import annotations

import py_compile
import subprocess
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import List, Optional, Sequence

from agents.coding_agent import UnitDiff
from code_validator import CodeValidator

from phase4.multi_agent_router import Task


class VerifyOutcome(str, Enum):
    PASS = "pass"
    FAIL_IMPL = "fail_impl"
    FAIL_STRUCT = "fail_struct"


@dataclass
class VerifyResult:
    outcome: VerifyOutcome
    rule_id: str = ""
    memory_id: str = ""
    detail: str = ""
    checks_run: int = 0
    violations: List[str] = field(default_factory=list)
    command_output: str = ""

    def summary(self) -> str:
        if self.outcome == VerifyOutcome.PASS:
            return f"✓ PASS ({self.checks_run} checks)"
        return f"✗ {self.outcome.value.upper()} rule={self.rule_id} {self.detail}"


class VerifyGate:
    """Harness 侧确定性验证门。"""

    def __init__(
        self,
        *,
        workspace_root: Optional[Path] = None,
        run_compile: bool = True,
        run_pytest: bool = True,
        pytest_args: Optional[Sequence[str]] = None,
        pytest_timeout: int = 60,
    ):
        self.workspace_root = Path(workspace_root).resolve() if workspace_root else None
        self.run_compile = run_compile
        self.run_pytest = run_pytest
        self.pytest_args = list(pytest_args or ["-q"])
        self.pytest_timeout = pytest_timeout

    def verify(
        self,
        diffs: List[UnitDiff],
        task: Task,
        *,
        run_pytest_stub: bool = True,
        applied: bool = False,
    ) -> VerifyResult:
        """
        applied=False：仅做内存侧 CodeValidator（兼容旧调用）
        applied=True ：在 workspace 上继续 compileall + pytest
        """
        graph = task.context.get("_code_arch_graph")
        checks = 0
        all_violations: List[str] = []

        if graph is not None:
            validator = CodeValidator(graph)
            for diff in diffs:
                report = validator.validate(diff.code)
                checks += report.checks_run
                if not report.passed:
                    for v in report.violations:
                        all_violations.append(f"[{diff.unit_id}] {v.detail}")
                        return VerifyResult(
                            outcome=VerifyOutcome.FAIL_IMPL,
                            rule_id=v.rule or "ARCH-001",
                            memory_id=v.memory_id,
                            detail=v.detail,
                            checks_run=checks,
                            violations=all_violations,
                        )

        if not applied:
            # 旧路径：未落盘时保留空测试文件检查
            if run_pytest_stub:
                checks += 1
                test_diffs = [d for d in diffs if "tests/" in d.target_path.replace("\\", "/")]
                if test_diffs and not test_diffs[0].code.strip():
                    return VerifyResult(
                        outcome=VerifyOutcome.FAIL_IMPL,
                        rule_id="TEST-001",
                        detail="测试文件为空",
                        checks_run=checks,
                    )
            return VerifyResult(outcome=VerifyOutcome.PASS, checks_run=checks)

        # ── 落盘后：compile + pytest ──
        root = self.workspace_root
        if root is None:
            root = Path(task.context.get("_workspace_root") or ".").resolve()

        if self.run_compile:
            compile_result = self._compile_diffs(diffs, root)
            checks += compile_result.checks_run
            if compile_result.outcome != VerifyOutcome.PASS:
                self._store_feedback(task, compile_result)
                return compile_result

        if self.run_pytest:
            has_tests = any(
                "tests/" in d.target_path.replace("\\", "/") or d.target_path.startswith("test_")
                for d in diffs
            )
            # 即使本轮没生成测试，只要 workspace 有 tests/ 也可跑
            tests_dir = root / "tests"
            if has_tests or tests_dir.exists():
                pytest_result = self._run_pytest(root)
                checks += pytest_result.checks_run
                if pytest_result.outcome != VerifyOutcome.PASS:
                    self._store_feedback(task, pytest_result)
                    return pytest_result
            elif run_pytest_stub:
                checks += 1
                test_diffs = [d for d in diffs if "tests/" in d.target_path.replace("\\", "/")]
                if test_diffs and not test_diffs[0].code.strip():
                    return VerifyResult(
                        outcome=VerifyOutcome.FAIL_IMPL,
                        rule_id="TEST-001",
                        detail="测试文件为空",
                        checks_run=checks,
                    )

        return VerifyResult(outcome=VerifyOutcome.PASS, checks_run=checks)

    def _compile_diffs(self, diffs: List[UnitDiff], root: Path) -> VerifyResult:
        checks = 0
        violations: List[str] = []
        outputs: List[str] = []
        for diff in diffs:
            if not diff.target_path.endswith(".py"):
                continue
            path = (root / diff.target_path).resolve()
            if not path.exists():
                violations.append(f"文件不存在: {diff.target_path}")
                return VerifyResult(
                    outcome=VerifyOutcome.FAIL_IMPL,
                    rule_id="COMPILE-001",
                    detail=f"落盘后找不到 {diff.target_path}",
                    checks_run=checks + 1,
                    violations=violations,
                )
            checks += 1
            try:
                py_compile.compile(str(path), doraise=True)
            except py_compile.PyCompileError as e:
                msg = str(e)
                outputs.append(msg)
                violations.append(msg)
                return VerifyResult(
                    outcome=VerifyOutcome.FAIL_IMPL,
                    rule_id="COMPILE-001",
                    detail=f"语法错误: {diff.target_path}",
                    checks_run=checks,
                    violations=violations,
                    command_output="\n".join(outputs)[:4000],
                )
        return VerifyResult(outcome=VerifyOutcome.PASS, checks_run=checks)

    def _run_pytest(self, root: Path) -> VerifyResult:
        cmd = [sys.executable, "-m", "pytest", *self.pytest_args]
        # 若存在 tests/meeting_order 优先；否则 tests
        for candidate in ("tests/meeting_order", "tests"):
            if (root / candidate).exists():
                cmd.append(candidate)
                break
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(root),
                capture_output=True,
                text=True,
                timeout=self.pytest_timeout,
            )
        except subprocess.TimeoutExpired as e:
            out = (e.stdout or "") + "\n" + (e.stderr or "")
            return VerifyResult(
                outcome=VerifyOutcome.FAIL_IMPL,
                rule_id="TEST-TIMEOUT",
                detail=f"pytest 超时 ({self.pytest_timeout}s)",
                checks_run=1,
                violations=[f"timeout after {self.pytest_timeout}s"],
                command_output=out[:4000],
            )
        except FileNotFoundError:
            return VerifyResult(
                outcome=VerifyOutcome.FAIL_IMPL,
                rule_id="TEST-ENV",
                detail="无法启动 pytest（未安装？）",
                checks_run=1,
                violations=["pytest not available"],
            )

        output = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        if proc.returncode == 0:
            return VerifyResult(
                outcome=VerifyOutcome.PASS,
                checks_run=1,
                command_output=output[:4000],
            )
        # pytest 退出码 5 = no tests collected → 不视为失败（骨架阶段）
        if proc.returncode == 5:
            return VerifyResult(
                outcome=VerifyOutcome.PASS,
                checks_run=1,
                detail="无测试收集，跳过",
                command_output=output[:4000],
            )
        return VerifyResult(
            outcome=VerifyOutcome.FAIL_IMPL,
            rule_id="TEST-FAIL",
            detail="pytest 失败",
            checks_run=1,
            violations=[line for line in output.splitlines() if "FAILED" in line][:20],
            command_output=output[:4000],
        )

    @staticmethod
    def _store_feedback(task: Task, result: VerifyResult) -> None:
        task.context = task.context or {}
        task.context["_last_verify_feedback"] = {
            "rule_id": result.rule_id,
            "detail": result.detail,
            "violations": result.violations,
            "command_output": result.command_output[:2000],
        }
