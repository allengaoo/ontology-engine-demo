#!/usr/bin/env python3
"""
测试脚本 - 验证本体引擎的三个场景

场景1：Happy Path - 正常采购（供应商ACME，认证有效365天）
场景2：拦截场景 - 认证即将过期（供应商Beta，剩余13天）
场景3：边界条件 - 同时违反多条规则（供应商Gamma）
"""

import sys
from pathlib import Path

# 添加democode到Python路径
democode_dir = Path(__file__).parent
sys.path.insert(0, str(democode_dir))

from engine import (
    SchemaLoader,
    ObjectStore,
    RuleEngine,
    ActionEngine,
    AuditLogger
)

def print_separator(title):
    print("\n" + "=" * 60)
    print(f"  {title}")
    print("=" * 60 + "\n")

def main():
    # 初始化引擎
    schema_dir = democode_dir / "schema"
    data_dir = democode_dir / "data"
    log_dir = democode_dir / "logs"
    
    schema_loader = SchemaLoader(schema_dir)
    object_store = ObjectStore(data_dir)
    audit_logger = AuditLogger(log_dir)
    rule_engine = RuleEngine(schema_loader, object_store)
    action_engine = ActionEngine(schema_loader, object_store, rule_engine, audit_logger)
    
    # 加载初始数据
    object_store.load_objects('Supplier')
    object_store.load_objects('Certification')
    object_store.load_objects('PurchaseOrder')
    
    print_separator("场景1：Happy Path - 正常采购")
    print("供应商：ACME 精密部件")
    print("认证状态：有效期剩余 365 天")
    print("信用额度：500,000 元，已用 180,000 元")
    print("采购金额：280,000 元\n")
    
    result1 = action_engine.execute_action(
        action_id='create_purchase_order',
        params={
            'supplier_pk': 'S-ACME-001',
            'material': '精密轴承',
            'amount': 280000,
            'quantity': 1000
        },
        caller='procurement-agent-v2'
    )
    
    if result1.success:
        print(f"✅ {result1.message}")
        print(f"事件ID: {result1.event_id}")
        print(f"创建的对象: {result1.created_objects}")
    else:
        print(f"❌ {result1.message}")
        if result1.violations:
            for v in result1.violations:
                print(f"   - {v['rule_id']}: {v['message']}")
    
    print_separator("场景2：拦截场景 - 认证即将过期")
    print("供应商：Beta 工业材料")
    print("认证状态：有效期剩余 13 天（< 30天阈值）")
    print("信用额度：300,000 元，已用 120,000 元")
    print("采购金额：80,000 元\n")
    
    result2 = action_engine.execute_action(
        action_id='create_purchase_order',
        params={
            'supplier_pk': 'S-BETA-002',
            'material': '工业胶水',
            'amount': 80000,
            'quantity': 500
        },
        caller='procurement-agent-v2'
    )
    
    if result2.success:
        print(f"✅ {result2.message}")
    else:
        print(f"❌ 操作被拦截！")
        print(f"原因: {result2.message}")
        if result2.violations:
            print("\n违反的规则:")
            for v in result2.violations:
                print(f"   - {v['rule_id']}: {v['message']}")
    
    print_separator("场景3：边界条件 - 同时违反多条规则")
    print("供应商：Gamma 化工原料")
    print("认证状态：有效期剩余 8 天（< 30天阈值）")
    print("信用额度：300,000 元，已用 280,000 元")
    print("采购金额：50,000 元")
    print("预期：未结金额 = 280,000 + 50,000 = 330,000 > 300,000（超额度）\n")
    
    result3 = action_engine.execute_action(
        action_id='create_purchase_order',
        params={
            'supplier_pk': 'S-GAMMA-003',
            'material': '化工原料X',
            'amount': 50000,
            'quantity': 200
        },
        caller='procurement-agent-v2'
    )
    
    if result3.success:
        print(f"✅ {result3.message}")
    else:
        print(f"❌ 操作被拦截！")
        print(f"原因: {result3.message}")
        if result3.violations:
            print(f"\n违反的规则（共 {len(result3.violations)} 条）:")
            for v in result3.violations:
                print(f"   - {v['rule_id']}: {v['message']}")
            print("\n💡 关键发现：引擎一次性返回了所有违规，而不是遇到第一个就停止")
            print("   这是第6篇会讨论的边界条件")
    
    print_separator("审计日志查询")
    print("查询所有决策事件...\n")
    
    events = audit_logger.query_events(limit=10)
    print(f"共记录 {len(events)} 个决策事件:\n")
    
    for i, event in enumerate(events, 1):
        print(f"{i}. 事件ID: {event.event_id}")
        print(f"   操作: {event.action_id}")
        print(f"   调用方: {event.caller}")
        print(f"   结果: {event.outcome}")
        if event.outcome == 'rejected':
            print(f"   拒绝原因: {event.rejection_reason}")
        else:
            print(f"   通过的规则: {', '.join(event.passed_rules)}")
        print()
    
    print_separator("总结")
    print("✅ 场景1（ACME）: 正常采购，全部规则通过")
    print("❌ 场景2（Beta）: 认证过期拦截")
    print("❌ 场景3（Gamma）: 同时违反认证有效期 + 信用额度，一次性返回所有问题")
    print("\n所有决策都已记录在 logs/decisions.jsonl")
    print("每条日志包含完整的对象快照，可追溯决策上下文\n")

if __name__ == '__main__':
    main()
