# 架构记忆（code-arch）说明

架构记忆描述「代码应如何组织」，与会议室预订业务规则无关。

## 两条来源（优先级）

```text
1) 工作区（优先）
   docs/architecture_brief.md
     → python cli.py inject-arch
     → .ontology_agent/arch_memory/

2) 包内精简种子（未 inject-arch 时回退）
   ifclubdemo/instances/
   ├── CROSS_CUTTING/   # 分层、写回滚、写范围
   └── DOMAIN/          # 架构反模式
```

## 在 EP 中的角色

作为联邦域 `code-arch` 注入；BSA / CA 的 scope 默认会读取该域。  
业务规则请走 `inject` → 域 `domain`，不要写进架构记忆。

## 命令

```bash
# 预览
python cli.py inject-arch docs/architecture_brief.md --dry-run

# 写入工作区
python cli.py inject-arch docs/architecture_brief.md

# 查看（工作区优先，否则包内种子）
python cli.py memory list
```

## 种子示例

- `CN-ARCH-001`：分层边界（API → Service → Repository）
- `CN-ARCH-002`：写路径必须可回滚（DiffApplier + VerifyGate）
- `CN-ARCH-003`：写范围受 `workspace.toml` 约束
- `PAT-ARCH-001`：FastAPI + SQLite + React 标准骨架
- `ANTI-ARCH-001`：不要把业务规则硬塞进架构记忆
