"""
verify_gate — 三路判定：PASS / FAIL_IMPL / FAIL_STRUCT（Phase 8 Harness）

1) ConstraintMemory / CodeValidator（内存）
2) compileall（落盘后）
3) 真实 pytest（落盘后，可配置）
"""

from __future__ import annotations

import os
import py_compile
import subprocess
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import List, Optional, Sequence

from agents.coding_agent import UnitDiff
from code_validator import CodeValidator
from harness.schema_gate import SchemaGate
from harness.fe_api_contract import check_fe_api_contract
from harness.api_url_contract import check_api_url_contract

from core.task import Task


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
                report = validator.validate(diff.code, file_path=diff.target_path)
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

        # Schema 硬校验（内存侧：优先检查 diffs 中的 models）
        schema_result = SchemaGate().check(
            Path(task.context.get("_workspace_root") or self.workspace_root or "."),
            diffs=diffs,
        )
        checks += schema_result.checks_run
        if not schema_result.ok:
            detail = schema_result.summary()
            self._store_feedback(
                task,
                VerifyResult(
                    outcome=VerifyOutcome.FAIL_STRUCT,
                    rule_id="SCHEMA-001",
                    detail=detail,
                    checks_run=checks,
                    violations=[f"{v.model}: {v.detail}" for v in schema_result.violations],
                ),
            )
            return VerifyResult(
                outcome=VerifyOutcome.FAIL_STRUCT,
                rule_id="SCHEMA-001",
                detail=detail,
                checks_run=checks,
                violations=[f"{v.model}: {v.detail}" for v in schema_result.violations],
            )

        root = self.workspace_root
        if root is None:
            root = Path(task.context.get("_workspace_root") or ".").resolve()

        # 会议域：禁跨应用 import + 禁臆造仓储符号 + 校验 import 可解析
        if root.name == "meeting_order" or "meeting_order" in str(root):
            leak = self._check_forbidden_imports(diffs, banned=("oncall",))
            checks += leak.checks_run
            if leak.outcome != VerifyOutcome.PASS:
                self._store_feedback(task, leak)
                return leak
            bad_sym = self._check_forbidden_symbols(
                diffs,
                banned=(
                    "BaseRoomRepository",
                    "BaseBookingRepository",
                    "BaseRepository",
                    "repositories.booking",
                    "repositories.room",
                ),
            )
            checks += bad_sym.checks_run
            if bad_sym.outcome != VerifyOutcome.PASS:
                self._store_feedback(task, bad_sym)
                return bad_sym
            seed_sig = self._check_seed_signature(diffs, root)
            checks += seed_sig.checks_run
            if seed_sig.outcome != VerifyOutcome.PASS:
                self._store_feedback(task, seed_sig)
                return seed_sig
            test_url = self._check_test_url_prefix(diffs)
            checks += test_url.checks_run
            if test_url.outcome != VerifyOutcome.PASS:
                self._store_feedback(task, test_url)
                return test_url
            fac_cache = self._check_factory_no_cache(diffs)
            checks += fac_cache.checks_run
            if fac_cache.outcome != VerifyOutcome.PASS:
                self._store_feedback(task, fac_cache)
                return fac_cache
            unresolved = self._check_import_resolution(diffs, root)
            checks += unresolved.checks_run
            if unresolved.outcome != VerifyOutcome.PASS:
                self._store_feedback(task, unresolved)
                return unresolved
            if applied:
                disk_leak = self._scan_tree_forbidden_imports(root, banned=("oncall",))
                checks += disk_leak.checks_run
                if disk_leak.outcome != VerifyOutcome.PASS:
                    self._store_feedback(task, disk_leak)
                    return disk_leak

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
        if self.run_compile:
            compile_result = self._compile_diffs(diffs, root)
            checks += compile_result.checks_run
            if compile_result.outcome != VerifyOutcome.PASS:
                self._store_feedback(task, compile_result)
                return compile_result

        # 落盘后再做一次 schema（防磁盘与 diff 不一致）
        schema_disk = SchemaGate().check(root, diffs=diffs)
        checks += schema_disk.checks_run
        if not schema_disk.ok:
            result = VerifyResult(
                outcome=VerifyOutcome.FAIL_STRUCT,
                rule_id="SCHEMA-001",
                detail=schema_disk.summary(),
                checks_run=checks,
                violations=[f"{v.model}: {v.detail}" for v in schema_disk.violations],
            )
            self._store_feedback(task, result)
            return result

        gate_layer = (task.context.get("_gate_layer") or "all").strip().lower()
        skip_pytest = bool(task.context.get("_skip_pytest")) or gate_layer == "frontend"
        vite_build = bool(task.context.get("_vite_build")) or gate_layer == "frontend"

        if self.run_pytest and not skip_pytest:
            has_tests = any(
                "tests/" in d.target_path.replace("\\", "/") or d.target_path.startswith("test_")
                for d in diffs
            )
            tests_dir = root / "tests"
            scoped = list(task.context.get("_pytest_paths") or [])
            # 分层门禁：domain/api 必须有 scoped paths，禁止默默跑全量拖死前端
            if gate_layer in ("domain", "api") and not scoped:
                return VerifyResult(
                    outcome=VerifyOutcome.FAIL_IMPL,
                    rule_id="GATE-001",
                    detail=f"gate_layer={gate_layer} 但未提供 _pytest_paths",
                    checks_run=checks + 1,
                )
            if has_tests or tests_dir.exists() or scoped:
                pytest_result = self._run_pytest(root, test_paths=scoped or None)
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

        if vite_build:
            vite_result = self._run_vite_build(root)
            checks += vite_result.checks_run
            if vite_result.outcome != VerifyOutcome.PASS:
                self._store_feedback(task, vite_result)
                return vite_result

        # 会议域：API URL 规范化 + 前端接线契约（专治 /api/v1 双写与页面假活）
        is_meeting = root.name == "meeting_order" or "meeting_order" in str(root)
        touched = [(d.target_path or "").replace("\\", "/") for d in diffs]
        touches_fe = any("frontend/" in p for p in touched)
        touches_api_surface = any(
            (
                "meeting_order/api/" in p
                or p.endswith("meeting_order/main.py")
                or p.endswith("meeting_order/config.py")
                or "frontend/" in p
            )
            for p in touched
        )
        force_fe = bool(task.context.get("_fe_api_contract"))
        force_url = bool(task.context.get("_api_url_contract"))
        if is_meeting and (
            touches_fe
            or touches_api_surface
            or force_fe
            or force_url
            or gate_layer == "frontend"
        ):
            url_c = check_api_url_contract(root)
            checks += url_c.checks_run
            if not url_c.ok:
                result = VerifyResult(
                    outcome=VerifyOutcome.FAIL_IMPL,
                    rule_id=url_c.violations[0].rule_id
                    if url_c.violations
                    else "API-URL-CONTRACT",
                    detail=url_c.summary(),
                    checks_run=checks,
                    violations=[f"{v.rule_id}: {v.detail}" for v in url_c.violations],
                )
                self._store_feedback(task, result)
                return result
            if touches_fe or force_fe or gate_layer == "frontend":
                fe_c = check_fe_api_contract(root)
                checks += fe_c.checks_run
                if not fe_c.ok:
                    result = VerifyResult(
                        outcome=VerifyOutcome.FAIL_IMPL,
                        rule_id=fe_c.violations[0].rule_id
                        if fe_c.violations
                        else "FE-API-CONTRACT",
                        detail=fe_c.summary(),
                        checks_run=checks,
                        violations=[f"{v.rule_id}: {v.detail}" for v in fe_c.violations],
                    )
                    self._store_feedback(task, result)
                    return result

        return VerifyResult(outcome=VerifyOutcome.PASS, checks_run=checks)

    @staticmethod
    def _forbidden_import_hits(code: str, *, banned: tuple) -> List[str]:
        import re

        hits: List[str] = []
        for name in banned:
            pats = (
                rf"^\s*import\s+{re.escape(name)}\b",
                rf"^\s*from\s+{re.escape(name)}\b",
            )
            for pat in pats:
                if re.search(pat, code, flags=re.M):
                    hits.append(name)
                    break
        return hits

    @classmethod
    def _check_forbidden_imports(
        cls, diffs: List[UnitDiff], *, banned: tuple = ("oncall",)
    ) -> VerifyResult:
        violations: List[str] = []
        for diff in diffs:
            path = (diff.target_path or "").replace("\\", "/")
            if not path.endswith(".py"):
                continue
            for name in cls._forbidden_import_hits(diff.code or "", banned=banned):
                violations.append(
                    f"{path}: 禁止导入 {name}（会议应用只能用 meeting_order）"
                )
        if violations:
            return VerifyResult(
                outcome=VerifyOutcome.FAIL_IMPL,
                rule_id="IMPORT-CROSS-APP",
                detail="; ".join(violations),
                checks_run=1,
                violations=violations,
            )
        return VerifyResult(outcome=VerifyOutcome.PASS, checks_run=1)

    @staticmethod
    def _check_forbidden_symbols(
        diffs: List[UnitDiff], *, banned: tuple
    ) -> VerifyResult:
        violations: List[str] = []
        for diff in diffs:
            path = (diff.target_path or "").replace("\\", "/")
            if not path.endswith(".py"):
                continue
            code = diff.code or ""
            for sym in banned:
                if sym in code:
                    violations.append(
                        f"{path}: 禁止符号/路径片段 {sym!r}（会议域请用 MeetingRepository+SqliteRepository）"
                    )
        if violations:
            return VerifyResult(
                outcome=VerifyOutcome.FAIL_IMPL,
                rule_id="SYMBOL-FORBIDDEN",
                detail="; ".join(violations[:8]),
                checks_run=1,
                violations=violations,
            )
        return VerifyResult(outcome=VerifyOutcome.PASS, checks_run=1)

    @staticmethod
    def _check_seed_signature(diffs: List[UnitDiff], root: Path) -> VerifyResult:
        """会议域：sqlite_repo 的种子方法必须自包含、无 conn 参数，且名为 seed_rooms_if_empty。

        防止 30B 在 sqlite_repo 写 _seed_rooms(self, conn) 而 factory 调 _seed_rooms() 造成签名不一致。
        """
        import re

        violations: List[str] = []
        for diff in diffs:
            path = (diff.target_path or "").replace("\\", "/")
            if "sqlite_repo.py" not in path:
                continue
            code = diff.code or ""
            # 禁止 _seed_rooms 命名（强制 seed_rooms_if_empty）
            if re.search(r"\bdef\s+_seed_rooms\s*\(", code):
                violations.append(
                    f"{path}: 种子方法必须叫 seed_rooms_if_empty（禁止 _seed_rooms）；"
                    "且必须 def seed_rooms_if_empty(self): 自包含，内部自己 sqlite3.connect，"
                    "禁止 def seed_rooms_if_empty(self, conn) 要外部传 conn。"
                )
            # 禁止 seed_rooms_if_empty(self, conn) 形式
            if re.search(r"def\s+seed_rooms_if_empty\s*\(\s*self\s*,\s*conn", code):
                violations.append(
                    f"{path}: seed_rooms_if_empty 必须无 conn 参数（自包含），"
                    "内部自己 sqlite3.connect(self.db_path)。"
                )
        if violations:
            return VerifyResult(
                outcome=VerifyOutcome.FAIL_IMPL,
                rule_id="SEED-SIGNATURE",
                detail="; ".join(violations[:8]),
                checks_run=1,
                violations=violations,
            )
        return VerifyResult(outcome=VerifyOutcome.PASS, checks_run=1)

    @staticmethod
    def _check_test_url_prefix(diffs: List[UnitDiff]) -> VerifyResult:
        """会议域：测试文件里访问 rooms/bookings 必须带 /api/v1 前缀，禁止裸用 "/rooms"/"/bookings"。

        30B 常在 test_api.py 写 client.get("/rooms") 导致 404（router 挂在 /api/v1 下）。
        """
        import re

        violations: List[str] = []
        for diff in diffs:
            path = (diff.target_path or "").replace("\\", "/")
            if "tests/" not in path or not path.endswith(".py"):
                continue
            code = diff.code or ""
            # 禁止裸 "/rooms" / "/bookings"（必须 "/api/v1/rooms" 等）。
            # 但要区分「真正的 API 调用」与「源码断言」：30B 常写
            #   text.count("/bookings") 或 ".../bookings" in text
            # 来断言前端源码提到该路径——这不是 API 调用，不能误判。
            # 仅当裸路径出现在 HTTP 调用参数位置（client.get/post/... 或 .get/.post/...）才判违规。
            http_call = re.compile(
                r"(?:client|c|self\.\w+|api|httpx|requests)\s*\.\s*"
                r"(?:get|post|put|patch|delete|head|options)\s*\(\s*"
                r"(?:f?\"|f?')"
            )
            for bare in ('"/rooms"', "'/rooms'", '"/bookings"', "'/bookings'",
                        '"/rooms/', "'/rooms/", '"/bookings/', "'/bookings/"):
                start = 0
                while True:
                    idx = code.find(bare, start)
                    if idx < 0:
                        break
                    start = idx + len(bare)
                    window = code[max(0, idx - 60):idx + len(bare)]
                    # 源码断言场景：跳过 text.count(...) / "..." in text / read_text / Path / re.search
                    if (
                        "count(" in window
                        or " in text" in window
                        or "read_text" in window
                        or "Path(" in window
                        or "re.search" in window
                        or "re.findall" in window
                        or "in page" in window
                    ):
                        continue
                    # 真正的 API 调用：前面是 .get(/.post( 等
                    if http_call.search(window):
                        violations.append(
                            f"{path}: 测试里访问 rooms/bookings 必须带 /api/v1 前缀"
                            "（如 client.get('/api/v1/rooms')）；router 挂在 /api/v1 下，"
                            f"裸用 {bare} 会 404。"
                        )
        if violations:
            return VerifyResult(
                outcome=VerifyOutcome.FAIL_IMPL,
                rule_id="TEST-URL-PREFIX",
                detail="; ".join(violations[:8]),
                checks_run=1,
                violations=violations,
            )
        return VerifyResult(outcome=VerifyOutcome.PASS, checks_run=1)

    @staticmethod
    def _check_factory_no_cache(diffs: List[UnitDiff]) -> VerifyResult:
        """会议域：factory.get_repository() 禁止全局缓存 _repository，否则 monkeypatch DB_PATH 失效。"""
        import re

        violations: List[str] = []
        for diff in diffs:
            path = (diff.target_path or "").replace("\\", "/")
            if "repositories/factory.py" not in path:
                continue
            code = diff.code or ""
            # 禁止 module-level _repository 缓存
            if re.search(r"^\s*_repository\s*=\s*None", code, flags=re.M) or re.search(
                r"global\s+_repository", code
            ):
                violations.append(
                    f"{path}: get_repository() 禁止全局缓存 _repository——"
                    "缓存会让 monkeypatch config.DB_PATH 失效（测试串库/409 误报）。"
                    "必须每次 return SqliteRepository()。"
                )
        if violations:
            return VerifyResult(
                outcome=VerifyOutcome.FAIL_IMPL,
                rule_id="FACTORY-NO-CACHE",
                detail="; ".join(violations[:8]),
                checks_run=1,
                violations=violations,
            )
        return VerifyResult(outcome=VerifyOutcome.PASS, checks_run=1)

    @staticmethod
    def _check_import_resolution(diffs: List[UnitDiff], root: Path) -> VerifyResult:
        """改后校验：from meeting_order.x.y import Z 的模块文件应存在（或本 EP 新建）。"""
        import re

        created = {
            (d.target_path or "").replace("\\", "/").lstrip("./")
            for d in diffs
            if (d.target_path or "").endswith(".py")
        }
        violations: List[str] = []
        for diff in diffs:
            path = (diff.target_path or "").replace("\\", "/")
            if not path.endswith(".py"):
                continue
            for mod, names in re.findall(
                r"^\s*from\s+(meeting_order(?:\.[A-Za-z_][\w]*)*)\s+import\s+([^\n#]+)",
                diff.code or "",
                flags=re.M,
            ):
                # meeting_order.repositories.booking -> backend/src/meeting_order/repositories/booking.py
                rel_mod = "backend/src/" + mod.replace(".", "/") + ".py"
                rel_pkg = "backend/src/" + mod.replace(".", "/") + "/__init__.py"
                if rel_mod in created or rel_pkg in created:
                    continue
                if (root / rel_mod).is_file() or (root / rel_pkg).is_file():
                    continue
                # allow importing symbols defined in same-file create of parent? still fail
                violations.append(
                    f"{path}: 无法解析 import `{mod}`（文件不存在且本 EP 未创建）；"
                    f"导入符号={names.strip()[:60]}"
                )
        if violations:
            return VerifyResult(
                outcome=VerifyOutcome.FAIL_IMPL,
                rule_id="IMPORT-RESOLVE",
                detail="; ".join(violations[:8]),
                checks_run=1,
                violations=violations,
            )
        return VerifyResult(outcome=VerifyOutcome.PASS, checks_run=1)

    @classmethod
    def _scan_tree_forbidden_imports(
        cls, root: Path, *, banned: tuple = ("oncall",)
    ) -> VerifyResult:
        violations: List[str] = []
        src = root / "backend" / "src" / "meeting_order"
        if not src.is_dir():
            return VerifyResult(outcome=VerifyOutcome.PASS, checks_run=1)
        for p in src.rglob("*.py"):
            try:
                code = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            rel = str(p.relative_to(root)).replace("\\", "/")
            for name in cls._forbidden_import_hits(code, banned=banned):
                violations.append(f"{rel}: 禁止导入 {name}")
        if violations:
            return VerifyResult(
                outcome=VerifyOutcome.FAIL_IMPL,
                rule_id="IMPORT-CROSS-APP-DISK",
                detail="; ".join(violations[:12]),
                checks_run=1,
                violations=violations,
            )
        return VerifyResult(outcome=VerifyOutcome.PASS, checks_run=1)

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

    def _run_pytest(
        self,
        root: Path,
        *,
        test_paths: Optional[Sequence[str]] = None,
    ) -> VerifyResult:
        cmd = [sys.executable, "-m", "pytest", *self.pytest_args]
        if test_paths:
            cmd.extend(list(test_paths))
        else:
            # 若存在 tests/oncall 或 tests/purchasing 优先；否则 tests
            for candidate in ("tests/oncall", "tests/purchasing", "tests"):
                if (root / candidate).exists():
                    cmd.append(candidate)
                    break
        # 工作区 backend/src + ifclubdemo 根（供 tests 引用 harness.fe_api_contract）
        env = os.environ.copy()
        path_parts = []
        for cand in ("backend/src", "src"):
            p = root / cand
            if p.is_dir():
                path_parts.append(str(p.resolve()))
        ifclub_root = Path(__file__).resolve().parents[1]
        if ifclub_root.is_dir():
            path_parts.append(str(ifclub_root))
        if path_parts:
            prev = env.get("PYTHONPATH", "")
            env["PYTHONPATH"] = os.pathsep.join(
                path_parts + ([prev] if prev else [])
            )
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(root),
                capture_output=True,
                text=True,
                timeout=self.pytest_timeout,
                env=env,
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
        interesting = []
        for line in output.splitlines():
            if any(
                k in line
                for k in (
                    "FAILED",
                    "ERROR",
                    "Error",
                    "TypeError",
                    "AttributeError",
                    "ImportError",
                    "AssertionError",
                    "E   ",
                )
            ):
                interesting.append(line)
        return VerifyResult(
            outcome=VerifyOutcome.FAIL_IMPL,
            rule_id="TEST-FAIL",
            detail="pytest 失败",
            checks_run=1,
            violations=interesting[:40],
            command_output=output[:8000],
        )

    def _run_vite_build(self, root: Path) -> VerifyResult:
        """前端分层门禁：npm run build（缺 frontend 时跳过）。"""
        fe = root / "frontend"
        if not fe.is_dir() or not (fe / "package.json").exists():
            return VerifyResult(
                outcome=VerifyOutcome.PASS,
                checks_run=0,
                detail="无 frontend/package.json，跳过 vite build",
            )
        env = os.environ.copy()
        # 首次可能无 node_modules
        if not (fe / "node_modules").exists():
            try:
                install = subprocess.run(
                    ["npm", "install", "--no-fund", "--no-audit"],
                    cwd=str(fe),
                    capture_output=True,
                    text=True,
                    timeout=180,
                    env=env,
                )
            except (FileNotFoundError, subprocess.TimeoutExpired) as e:
                return VerifyResult(
                    outcome=VerifyOutcome.FAIL_IMPL,
                    rule_id="VITE-ENV",
                    detail=f"npm install 失败: {e}",
                    checks_run=1,
                )
            if install.returncode != 0:
                out = (install.stdout or "") + "\n" + (install.stderr or "")
                return VerifyResult(
                    outcome=VerifyOutcome.FAIL_IMPL,
                    rule_id="VITE-INSTALL",
                    detail="npm install 失败",
                    checks_run=1,
                    command_output=out[:4000],
                )
        try:
            proc = subprocess.run(
                ["npm", "run", "build"],
                cwd=str(fe),
                capture_output=True,
                text=True,
                timeout=180,
                env=env,
            )
        except FileNotFoundError:
            return VerifyResult(
                outcome=VerifyOutcome.FAIL_IMPL,
                rule_id="VITE-ENV",
                detail="未找到 npm",
                checks_run=1,
            )
        except subprocess.TimeoutExpired:
            return VerifyResult(
                outcome=VerifyOutcome.FAIL_IMPL,
                rule_id="VITE-TIMEOUT",
                detail="vite build 超时",
                checks_run=1,
            )
        out = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        if proc.returncode == 0:
            return VerifyResult(
                outcome=VerifyOutcome.PASS,
                checks_run=1,
                command_output=out[:4000],
            )
        interesting = [
            line
            for line in out.splitlines()
            if any(k in line for k in ("error", "Error", "failed", "FAILED", "@/"))
        ]
        return VerifyResult(
            outcome=VerifyOutcome.FAIL_IMPL,
            rule_id="VITE-FAIL",
            detail="vite build 失败",
            checks_run=1,
            violations=interesting[:40],
            command_output=out[:8000],
        )

    @staticmethod
    def _store_feedback(task: Task, result: VerifyResult) -> None:
        task.context = task.context or {}
        task.context["_last_verify_feedback"] = {
            "rule_id": result.rule_id,
            "detail": result.detail,
            "violations": result.violations,
            "command_output": (result.command_output or "")[:6000],
        }
