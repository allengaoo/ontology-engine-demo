# 小模型场景：建议放入的种子记忆

面向 **多智能体 + 动态本体 Schema + 记忆系统** 驱动 ~30B 写业务代码。  
种子记忆的原则：**把上一轮已经反复踩过的坑，提前变成 Constraint / Pattern / Anti / Schema**，而不是指望模型「自己记住」。

## 为什么要种子记忆？

| 小模型弱点 | 种子记忆对策 |
|-----------|-------------|
| 字段名漂移（team / slot / Roster.engineers） | Schema 硬字段 + CN 禁造字段 |
| 集成测写飘（无 primary、404、串库） | PAT 测法 + CN primary-per-day |
| 一轮改太多文件 | 架构 CN：Unit 预算 + Impl/Test/Repair |
| 前端 `@/` / 围栏污染 | 前端 CN + ANTI |
| 失败后重复同样错误 | FAIL→ANTI 热记忆（运行时写回） |

种子（inject 前写进 brief）负责 **开局契约**；ANTI/DEC（EP 写回）负责 **过程学习**。

## A. 业务域种子（`business_brief` → `inject`）

### Constraint（必须有）

1. **每天至少一条 `shift_type=primary`** — 上一轮「No primary shift for date…」主因  
2. **`shift_type` 仅 `primary|backup`** — 禁止测试自造枚举  
3. **`Roster(shifts=…)`，禁止 `Roster(engineers=…)`**  
4. **`CreateEngineerRequest={name,is_active?}`** — 禁止 Engineer 当 request body  
5. **409 → `detail.code=ROSTER_CONFLICT`**  
6. **`validate_roster` 纯函数 / `generate_week` 空 active 抛 `RuleViolation`**  
7. **API 前缀 `/api/v1`**

### Pattern（强烈建议）

1. **周循环排班**：active 工程师 round-robin，每天 primary（+可选 backup）  
2. **冲突返回明确错误码**，前端只展示不重算  
3. **落地顺序**：models → repositories → schemas → rules → scheduler → services → API → FE  
4. **测试**：monkeypatch `config.DB_PATH` + `repositories.factory.reset_repository_cache()`，API 用 TestClient  
5. **仓储只经 factory**：禁止 api/services 直接 connect  
6. 写码前对齐上游签名  

### AntiPattern（强烈建议）

1. API 层写排班规则 / 直接 SQL  
2. 发明 `RosterEntry` / `Engineer.team`  
3. freeze 后仍改 models  
4. 用错 `response_model` / generate 返回空 shifts  
5. 测试连 mysql 或写死生产 DB 路径  

## B. 架构域种子（`architecture_brief` → `inject-arch`）

1. 分层与写范围（禁错误路径整路径匹配）  
2. SchemaGate + freeze + Unit 预算 + 分层门禁（pytest / vite）  
3. 前端禁止 `@/`、页面/组件白名单、禁止围栏语言标签落盘  
4. Impl/Test/Repair 分轮；FAIL→ANTI  
5. DB 经 repositories；默认 sqlite，可切换 mysql  

## C. 硬 Schema（`oncall_schema.json`，机器校验）

- models 必填/禁填字段  
- schemas.CreateEngineerRequest DTO 路径与字段  
- frontend pages/components 白名单  
- `domain_contracts`：primary-per-day、generate→Roster、空 active→RuleViolation  
- `freeze_defaults.after_models`

## D. 不必预先塞进种子的（留给运行时）

| 类型 | 原因 |
|------|------|
| 具体某次 EP 的 diff / 文件内容 | 应由 DEC 写回，不是 brief |
| 某次 Vite 报错全文 | ANTI digest 即可 |
| 业务排班偏好（谁多值几天） | 非第一期硬约束 |
| 大段示例源码 | 易过期；用签名注入代替 |

## E. 注入后如何验收

```bash
python cli.py init-app oncall
python cli.py inject docs/business_brief.md --workspace workspace/oncall
python cli.py inject-arch docs/architecture_brief.md --workspace workspace/oncall
python cli.py memory list --workspace workspace/oncall
```

业务侧应看到多条 `CN-ONCALL-*` / `PAT-ONCALL-*` / `ANTI-ONCALL-*`；  
架构侧应看到 `CN-ARCH-*`（分层/写路径/写范围/前端）与 `PAT-*` / `ANTI-*`。
