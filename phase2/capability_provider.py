"""
CapabilityProvider - 从 Schema 生成 LLM 可消费的能力清单

职责：
- 读取 action_types.yaml，生成 OpenAI Function Calling / tool use 格式
- 同一份 YAML：对人可读（第5篇），对 Agent 可调用（第9篇）
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import yaml


TYPE_MAP = {
    "string": "string",
    "number": "number",
    "integer": "integer",
    "boolean": "boolean",
}


class CapabilityProvider:
    """从本体 Schema 生成能力清单"""

    def __init__(self, schema_dir: Path):
        self.schema_dir = Path(schema_dir)
        self._action_types = self._load_action_types()

    def _load_action_types(self) -> Dict[str, Any]:
        path = self.schema_dir / "action_types.yaml"
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data.get("action_types", {})

    def generate_capability_manifest(self) -> List[Dict[str, Any]]:
        """生成 OpenAI tools 格式的能力清单"""
        tools: List[Dict[str, Any]] = []
        for action_id, spec in self._action_types.items():
            properties: Dict[str, Any] = {}
            required: List[str] = []

            for name, param in spec.get("parameters", {}).items():
                json_type = TYPE_MAP.get(param.get("type", "string"), "string")
                properties[name] = {
                    "type": json_type,
                    "description": param.get("description", ""),
                }
                if param.get("required"):
                    required.append(name)

            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": action_id,
                        "description": spec.get("description", ""),
                        "parameters": {
                            "type": "object",
                            "properties": properties,
                            "required": required,
                        },
                    },
                    "_meta": {
                        "preconditions": [
                            p.get("message", p.get("condition", ""))
                            for p in spec.get("preconditions", [])
                        ],
                        "triggered_rules": spec.get("triggered_rules", []),
                        "effects_summary": self._summarize_effects(spec.get("effects", [])),
                    },
                }
            )
        return tools

    def _summarize_effects(self, effects: List[Dict[str, Any]]) -> List[str]:
        summary = []
        for effect in effects:
            if "create_object" in effect:
                summary.append(f"创建 {effect['create_object'].get('type')} 对象")
            elif "update_object" in effect:
                summary.append(f"更新 {effect['update_object'].get('type')} 对象")
        return summary

    def generate_openai_tools(self) -> List[Dict[str, Any]]:
        """仅返回 OpenAI API 需要的 tools 字段（去掉 _meta）"""
        tools = []
        for item in self.generate_capability_manifest():
            tools.append(
                {
                    "type": item["type"],
                    "function": item["function"],
                }
            )
        return tools

    def print_manifest(self) -> None:
        manifest = self.generate_capability_manifest()
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
