"""Task / AgentResult — ifclubdemo 核心任务类型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class Task:
    description: str
    user_id: str = "user"
    context: Dict[str, Any] = field(default_factory=dict)
    feedback: Optional[str] = None

    def __post_init__(self) -> None:
        if self.context is None:
            self.context = {}


@dataclass
class AgentResult:
    status: str  # completed / needs_input / rejected / ...
    output: Any = None
    next_agent: Optional[str] = None
    reason: Optional[str] = None
