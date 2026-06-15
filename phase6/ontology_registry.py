"""
OntologyRegistry — 加载记忆本体 Schema，校验实例 front-matter

职责（Article 029 §4.1）：
  - 从 schema/objects/*.yaml 加载 ObjectType 定义
  - 从 schema/_config/layers.yaml 加载合法 layer 枚举
  - validate(instance_dict, object_type_id) → ValidationResult
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import yaml


@dataclass
class ValidationResult:
    ok: bool
    errors: List[str] = field(default_factory=list)


class OntologyRegistry:
    """记忆本体注册表（骨架实现）"""

    def __init__(self, schema_root: Path):
        self.schema_root = schema_root
        self.object_types: Dict[str, dict] = {}
        self.layers: Set[str] = set()
        self.tiers: Set[str] = {"hot", "warm", "cold", "archive"}
        self._load()

    def _load(self) -> None:
        layers_path = self.schema_root / "_config" / "layers.yaml"
        if layers_path.exists():
            data = yaml.safe_load(layers_path.read_text(encoding="utf-8"))
            for item in data.get("layers", []):
                self.layers.add(item["id"])

        objects_dir = self.schema_root / "objects"
        for path in sorted(objects_dir.glob("*.yaml")):
            if path.name.startswith("_"):
                continue
            doc = yaml.safe_load(path.read_text(encoding="utf-8"))
            if doc and doc.get("type") == "object":
                self.object_types[doc["id"]] = doc

    def list_object_types(self) -> List[str]:
        return sorted(self.object_types.keys())

    def validate(self, instance: Dict[str, Any]) -> ValidationResult:
        """校验记忆实例 front-matter"""
        errors: List[str] = []
        obj_type = instance.get("object_type")
        if not obj_type:
            errors.append("缺少 object_type")
            return ValidationResult(False, errors)

        if obj_type not in self.object_types:
            errors.append(f"未知 object_type: {obj_type}")
            return ValidationResult(False, errors)

        # 基础字段（_memory_base）
        for key in ("id", "title", "layer", "tier", "tags"):
            if key not in instance:
                errors.append(f"缺少必填字段: {key}")

        layer = instance.get("layer")
        if layer and self.layers and layer not in self.layers:
            errors.append(f"非法 layer: {layer}")

        tier = instance.get("tier")
        if tier and tier not in self.tiers:
            errors.append(f"非法 tier: {tier}")

        # 类型特有必填（骨架：只检查 required: true 的 specific_properties）
        spec = self.object_types[obj_type].get("specific_properties", {})
        for name, meta in spec.items():
            if meta.get("required") and instance.get(name) is None:
                errors.append(f"{obj_type} 缺少字段: {name}")

        return ValidationResult(len(errors) == 0, errors)
