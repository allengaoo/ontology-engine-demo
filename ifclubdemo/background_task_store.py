"""
background_task_store — 跨轮次异步子任务结果缓存（Phase 7 P2）

问题背景：
  SimAgent 在制衡重试时，除了 status=rejected 还产生了详细分析报告。
  这份报告只在当前 turn 的消息流里，下一轮 OntologyAgent 重跑时看不到它——
  只能靠 coordinator 透传 sim_feedback，而这个字段容易被消息流截断。

BackgroundTaskStore 做三件事：
  1. submit()   : Agent 完成后把详细结果存入 Store
  2. inject()   : 下一轮开始前把未消费的结果注入 task.context["_bg_results"]
  3. flush()    : 已注入的结果标记消费，避免重复注入

类比：
  Codex 的 followup_task：把"下一步该做什么"存到队列，不依赖即时消息流传递。
  BackgroundTaskStore 把"刚才做了什么"存到队列，供下一轮的 Agent 读取。
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class BackgroundTask:
    task_id: str
    agent_name: str
    result: Any
    label: str = ""
    submitted_at: str = field(default_factory=lambda: datetime.now().isoformat())
    injected: bool = False

    def summary(self) -> str:
        result_str = str(self.result)[:80]
        return (
            f"[{self.task_id[:8]}] {self.agent_name}"
            + (f"/{self.label}" if self.label else "")
            + f" → {result_str}"
        )


class BackgroundTaskStore:
    """
    线程安全的跨轮次结果缓存。

    典型用法：
        store = BackgroundTaskStore()

        # SimAgent 完成一轮后
        tid = store.submit("SimAgent", result=sim_output, label="feedback")

        # 下一轮 OntologyAgent 开始前
        injected_count = store.inject_into_context(task)
        # → task.context["_bg_results"] 里可见 SimAgent 的详细报告

        # 轮次结束后清理已注入条目
        store.flush()
    """

    def __init__(self) -> None:
        self._tasks: Dict[str, BackgroundTask] = {}
        self._lock = threading.Lock()

    def submit(
        self,
        agent_name: str,
        result: Any,
        label: str = "",
    ) -> str:
        """提交一个后台任务结果，返回 task_id。"""
        tid = uuid.uuid4().hex[:8]
        with self._lock:
            self._tasks[tid] = BackgroundTask(
                task_id=tid,
                agent_name=agent_name,
                result=result,
                label=label,
            )
        return tid

    def pending(self) -> List[BackgroundTask]:
        """返回所有尚未注入的后台任务（按提交顺序）。"""
        with self._lock:
            return [t for t in self._tasks.values() if not t.injected]

    def inject_into_context(self, task: Any) -> int:
        """
        把所有待注入任务写入 task.context["_bg_results"]。
        返回注入的条目数。

        注：task 需有 .context 属性（dict 或 None）。
        """
        tasks = self.pending()
        if not tasks:
            return 0

        task.context = task.context or {}
        existing: List[dict] = task.context.get("_bg_results", [])
        for bt in tasks:
            existing.append(
                {
                    "task_id": bt.task_id,
                    "agent": bt.agent_name,
                    "label": bt.label,
                    "result": bt.result,
                    "submitted_at": bt.submitted_at,
                }
            )
            with self._lock:
                self._tasks[bt.task_id].injected = True

        task.context["_bg_results"] = existing
        return len(tasks)

    def flush(self) -> int:
        """移除所有已注入的任务条目。返回移除数量。"""
        with self._lock:
            done = [tid for tid, t in self._tasks.items() if t.injected]
            for tid in done:
                del self._tasks[tid]
        return len(done)

    def all_summaries(self) -> List[str]:
        with self._lock:
            return [t.summary() for t in self._tasks.values()]

    def __len__(self) -> int:
        with self._lock:
            return len(self._tasks)
