"""
ObjectStore - 对象存储

职责：
- 读写对象的JSON文件
- 维护对象的内存快照
- 提供对象查询能力

对应Palantir：对象数据库（简化版）

设计说明：
- 使用JSON文件存储对象实例
- 每个对象类型一个文件（例如 Supplier.json）
- 读取时全部加载到内存（Demo级别，生产环境需要按需加载）
"""

import json
from pathlib import Path
from typing import Dict, List, Any, Optional
from copy import deepcopy
from datetime import datetime


class ObjectStore:
    """对象存储"""
    
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # 内存中的对象缓存 {object_type: {pk: object_data}}
        self._cache: Dict[str, Dict[str, Any]] = {}
    
    def _get_file_path(self, object_type: str) -> Path:
        """获取对象类型的数据文件路径"""
        return self.data_dir / f"{object_type}.json"
    
    def load_objects(self, object_type: str) -> Dict[str, Any]:
        """
        从文件加载某个类型的所有对象到内存
        返回 {pk: object_data} 的字典
        """
        file_path = self._get_file_path(object_type)
        
        if not file_path.exists():
            # 文件不存在，返回空字典
            self._cache[object_type] = {}
            return {}
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                objects_list = json.load(f)
            
            # 转换为 {pk: object} 的字典格式
            objects_dict = {obj['pk']: obj for obj in objects_list}
            self._cache[object_type] = objects_dict
            return objects_dict
        
        except json.JSONDecodeError as e:
            raise ValueError(f"无法解析 {file_path}: {e}")
    
    def get_object(self, object_type: str, pk: str) -> Optional[Dict[str, Any]]:
        """获取单个对象（先从缓存，缓存没有则加载）"""
        if object_type not in self._cache:
            self.load_objects(object_type)
        
        return self._cache[object_type].get(pk)
    
    def query_objects(self, object_type: str, filter_fn=None) -> List[Dict[str, Any]]:
        """
        查询对象（简化版过滤）
        filter_fn: 过滤函数，接收对象，返回 True/False
        """
        if object_type not in self._cache:
            self.load_objects(object_type)
        
        objects = list(self._cache[object_type].values())
        
        if filter_fn:
            objects = [obj for obj in objects if filter_fn(obj)]
        
        return objects
    
    def create_snapshot(self, object_types: List[str] = None) -> Dict[str, Dict[str, Any]]:
        """
        创建当前状态的完整快照
        
        这是第5篇"第二个决策"的核心：审计日志存快照，而不是diff
        快照记录了执行时刻的完整对象状态，用于追溯决策上下文
        
        返回: {object_type: {pk: object_data}}
        """
        snapshot = {}
        
        if object_types is None:
            # 快照所有已加载的对象类型
            object_types = list(self._cache.keys())
        
        for obj_type in object_types:
            if obj_type in self._cache:
                # 深拷贝，避免后续修改影响快照
                snapshot[obj_type] = deepcopy(self._cache[obj_type])
        
        return snapshot
    
    def restore_snapshot(self, snapshot: Dict[str, Dict[str, Any]]):
        """
        恢复到某个快照状态（用于回滚）
        
        这是第5篇"第一个决策"的核心：规则在写入后执行
        如果规则失败，直接恢复到操作前的快照，实现回滚
        """
        for obj_type, objects in snapshot.items():
            self._cache[obj_type] = deepcopy(objects)
    
    def persist(self, object_type: str):
        """
        将某个类型的对象持久化到文件
        
        重要：这是唯一的写文件时机
        在此之前，所有修改都只在内存中
        """
        if object_type not in self._cache:
            return
        
        file_path = self._get_file_path(object_type)
        
        # 转换为列表格式
        objects_list = list(self._cache[object_type].values())
        
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(objects_list, f, ensure_ascii=False, indent=2)
    
    def persist_all(self):
        """持久化所有对象类型"""
        for obj_type in self._cache.keys():
            self.persist(obj_type)
    
    def update_object(self, object_type: str, pk: str, updates: Dict[str, Any]):
        """
        更新对象（仅在内存中）
        
        注意：这个方法不写文件，只修改内存缓存
        文件的写入由 persist() 统一处理
        """
        if object_type not in self._cache:
            self.load_objects(object_type)
        
        if pk not in self._cache[object_type]:
            raise ValueError(f"对象 {object_type}/{pk} 不存在")
        
        # 更新内存中的对象
        self._cache[object_type][pk].update(updates)
    
    def create_object(self, object_type: str, obj_data: Dict[str, Any]):
        """
        创建新对象（仅在内存中）
        
        注意：同样不写文件
        """
        if object_type not in self._cache:
            self.load_objects(object_type)
        
        pk = obj_data.get('pk')
        if not pk:
            raise ValueError("对象必须包含 pk 属性")
        
        if pk in self._cache[object_type]:
            raise ValueError(f"对象 {object_type}/{pk} 已存在")
        
        # 添加时间戳
        obj_data['created_at'] = datetime.now().isoformat()
        
        self._cache[object_type][pk] = obj_data
    
    def delete_object(self, object_type: str, pk: str):
        """删除对象（仅在内存中）"""
        if object_type not in self._cache:
            self.load_objects(object_type)
        
        if pk in self._cache[object_type]:
            del self._cache[object_type][pk]
