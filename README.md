# 最小本体引擎 Demo

这是一个完整可运行的最小本体引擎实现，便于更好的理解公众号文章的内容。

---

## 🏗️ 架构设计

### 核心设计原则

本引擎基于Palantir本体架构的核心思想，做了三个关键简化：


| Palantir组件  | 解决的问题     | Demo实现               |
| ----------- | --------- | -------------------- |
| 对象数据库 + OSS | 海量数据查询和索引 | JSON文件 + 内存加载        |
| 对象数据漏斗      | 实时数据同步    | 手动初始化数据              |
| 分布式事务       | 并发写入一致性   | 内存事务 + 单线程           |
| OMS         | 元数据管理     | **YAML文件（保留）**       |
| 操作服务        | 规则校验 + 写回 | **ActionEngine（保留）** |
| 审计日志        | 决策追溯      | **JSONL文件（保留）**      |


### 五个核心组件

```
┌─────────────────────────────────────────────────────────┐
│                    ActionEngine                          │
│              （唯一写入入口 + 事务协调器）                  │
└────────────┬────────────────────────────┬────────────────┘
             │                            │
    ┌────────▼─────────┐         ┌───────▼────────┐
    │  SchemaLoader    │         │  ObjectStore   │
    │  (YAML定义加载)  │         │  (对象存储)    │
    └──────────────────┘         └────────────────┘
             │                            │
    ┌────────▼─────────┐         ┌───────▼────────┐
    │   RuleEngine     │         │  AuditLogger   │
    │  (规则校验)      │         │  (决策日志)    │
    └──────────────────┘         └────────────────┘
```

**组件职责**：

| 组件 | 职责 | 文件 |
|------|------|------|
| **ActionEngine** | 唯一写入入口，协调整个执行流程：校验前置条件、应用变更、评估规则、原子提交/回滚 | `action_engine.py` |
| **SchemaLoader** | 加载和解析YAML Schema定义（对象类型、操作类型、规则） | `schema_loader.py` |
| **ObjectStore** | 管理对象数据的读写和内存缓存，支持快照和回滚 | `object_store.py` |
| **RuleEngine** | 评估全局业务规则，支持单条或收集所有违规 | `rule_engine.py` |
| **AuditLogger** | 记录每次决策的完整上下文快照到JSONL文件 | `audit_logger.py` |

---

## 🚀 快速开始

### 前置要求

- Python 3.8+
- 无需安装任何第三方依赖（仅使用Python标准库）

### 运行Demo

```bash
# 克隆仓库
git clone https://github.com/allengaoo/ontology-engine-demo
cd ontology-engine-demo

# 直接运行测试场景
python3 test_scenarios.py
```

### 预期输出

```
============================================================
  场景1：Happy Path - 正常采购
============================================================

供应商：ACME 精密部件
认证状态：有效期剩余 365 天
✅ 操作 create_purchase_order 执行成功
事件ID: evt-20260530-ec9023

============================================================
  场景2：拦截场景 - 认证即将过期
============================================================

供应商：Beta 工业材料
认证状态：有效期剩余 13 天（< 30天阈值）
❌ 操作被拦截！
原因: 供应商认证有效期不足 30 天

============================================================
  场景3：边界条件 - 同时违反多条规则
============================================================

供应商：Gamma 化工原料
❌ 操作被拦截！
违反的规则（共 2 条）:
   - certification_validity: 认证有效期不足 30 天
   - credit_limit_check: 采购金额超过供应商信用额度

💡 关键发现：引擎一次性返回了所有违规
```

---

## 📁 目录结构

```
ontology-engine-demo/
├── README.md                    # 本文件
├── requirements.txt             # Python依赖（空文件，无外部依赖）
│
├── schema/                      # Schema定义（YAML格式）
│   ├── object_types.yaml        # 对象类型：Supplier, Certification, PurchaseOrder
│   ├── action_types.yaml        # 操作类型：create_purchase_order
│   └── rules.yaml               # 全局规则：certification_validity, credit_limit_check
│
├── data/                        # 测试数据（JSON格式）
│   ├── Supplier.json            # 3个供应商
│   ├── Certification.json       # 3张认证证书
│   └── PurchaseOrder.json       # 订单（初始为空）
│
├── logs/                        # 审计日志（运行后生成）
│   └── decisions.jsonl          # 每行一个决策事件
│
├── engine/                      # 核心引擎代码
│   ├── __init__.py
│   ├── schema_loader.py         # Schema加载器
│   ├── object_store.py          # 对象存储
│   ├── rule_engine.py           # 规则引擎
│   ├── action_engine.py         # 操作引擎（核心）
│   └── audit_logger.py          # 审计日志
│
└── test_scenarios.py            # 测试脚本：运行3个场景
```

---

## 🔑 三个关键设计决策

### 决策1：规则在写入"后"执行

**问题**：规则应该在写入前还是写入后检查？

**答案**：写入后（在内存中）。

**原因**：全局规则（不变式）需要检查"执行后的新状态"是否合法，而不是"当前状态能否执行"。

```python
# 4. 在内存中应用变更（文件未动）
new_state = action_def.apply_effects(snapshot, params)

# 5. 校验全局规则（写入后，但仍在内存）
for rule in rule_engine.get_triggered_rules(action_id):
    if not rule.evaluate(new_state):
        # 违反规则 → 回滚（丢弃内存，文件从未被写）
        return ActionResult.rejected(rule.violation_message)

# 6. 全部通过，提交（唯一一次写文件）
object_store.persist_all()
```

---

### 决策2：审计日志存"快照"而不是"变更"

**问题**：日志应该记录"改了什么"（diff）还是"当时状态是什么"（snapshot）？

**答案**：快照。

**原因**：三个月后需要回答"AI为什么这样决定"，diff无法还原决策上下文。

```python
@dataclass
class DecisionEvent:
    event_id: str
    action_id: str
    caller: str
    params: dict
    snapshot: dict           # ← 关键：完整对象状态
    passed_rules: list[str]
    outcome: str
    executed_at: datetime
```

---

### 决策3：Schema用YAML而不是Python类

**问题**：规则定义应该用YAML还是Python代码？

**答案**：YAML。

**原因**：业务人员需要审查规则，他们可能看不懂Python代码。

```yaml
# rules.yaml - 业务人员可以直接打开审查
- rule_id: certification_validity
  trigger_on: create_purchase_order
  expression: "cert_days_remaining >= 30"
  violation_message: 供应商认证有效期不足 30 天
```

---

## 🛠️ 自定义场景

### 修改测试数据

编辑 `data/Supplier.json`，例如添加一个新供应商：

```json
{
  "pk": "S-DELTA-004",
  "name": "Delta 电子元件",
  "status": "active",
  "credit_limit": 800000,
  "outstanding_amount": 0,
  "contract_status": "valid",
  "contract_expiry": "2027-12-31"
}
```

### 修改规则

编辑 `schema/rules.yaml`，例如修改认证有效期阈值：

```yaml
- rule_id: certification_validity
  expression: "cert_days_remaining >= 60"  # 从30改成60
  violation_message: 供应商认证有效期不足 60 天
```

### 添加新规则

在 `schema/rules.yaml` 添加：

```yaml
- rule_id: order_amount_threshold
  trigger_on: create_purchase_order
  expression: "amount <= 500000"
  violation_message: 单笔采购金额超过 50 万元，需财务总监审批
```

---

## 📄 开源协议

MIT License

---

## 💬 联系方式

- **公众号**：工程师的本体论
- **问题反馈**：提交GitHub Issue
- **商业咨询**：公众号后台留言

---

**最后更新**：2026-05-30

如果这个Demo对你有帮助，欢迎Star ⭐
