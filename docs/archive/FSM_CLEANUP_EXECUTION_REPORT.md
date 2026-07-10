# Legacy FSM Cleanup — 执行报告

**日期**: 2026-07-08
**范围**: Phase A + Phase B
**状态**: ✅ 完成

---

## Phase A — 文件与字段清理

### A1. 删除备份文件
| 文件 | 状态 |
|------|------|
| `worker/index.ts.bak` | ✅ 已删除 |
| `worker/index.js.bak` | ✅ 已删除 |
| `worker/index.js.archived` | ✅ 已删除 |

### A2. 删除 GlobalBounds.max_fsm_transitions
- **文件**: `backend/services/orchestrator_routing.py`
- **操作**: 移除 `max_fsm_transitions: int = 10` 字段
- **测试**: `test_stress.py::test_cost_budget_enforcement` 不依赖此字段，通过

### A3. 删除 SDK get_fsm_transitions()
- **文件**: `sdk/python/ai_team_hub/client.py`
- **操作**: 移除 `get_fsm_transitions()` 方法（L230-232）
- **说明**: 后端路由 `/v1/fsm-transitions/` 早已删除，此 SDK 方法会产生 404

### A4. 归档 shadow_verify.py
- **源**: `scripts/debug/shadow_verify.py`
- **目标**: `scripts/archive/shadow_verify.py`
- **状态**: ✅ 已移动

---

## Phase B — Worker 代码清理

### B1. worker/index.mjs
| 项 | 行号（原） | 操作 |
|----|-----------|------|
| `REVIEW_SCHEMA` 常量 | 951-959 | ✅ 删除 |
| `runOrchestrator()` | 960-1121 | ✅ 删除 |
| `classifyIntent()` | 1122-1131 | ✅ 删除（仅 legacy 使用） |
| `getAgentsForIntent()` | 1132-1140 | ✅ 删除（仅 legacy 使用） |
| `buildDag()` | 1142-1172 | ✅ 删除（仅 legacy 使用） |
| `saveTrace()` | 1218-1225 | ✅ 删除（仅 legacy 使用） |
| `adaptive=false` 分支 | 1737-1752 | ✅ 删除，路由简化 |
| `const adaptive` 变量 | 1712 | ✅ 移除 |
| `/api/orchestrator/state` | 1760-1762 | ✅ 删除 |

**保留**: `parseReviewEnhanced()` — 仍被 `runAdaptiveOrchestrator` 使用

### B2. worker/index.ts
| 项 | 行号（原） | 操作 |
|----|-----------|------|
| ③ v2 TeamEngine 节点头 | 1055-1057 | ✅ 删除 |
| `OrchState` 类型 | 1059 | ✅ 删除 |
| `OrchContext` 接口 | 1061-1072 | ✅ 删除 |
| `REVIEW_SCHEMA` 常量 | 1086-1094 | ✅ 删除 |
| `ReviewResult` 接口 | 1096-1103 | ✅ 删除 |
| `runTeamEngine()` | 1105-1288 | ✅ 删除 |
| `classifyIntent()` | 1290-1296 | ✅ 删除 |
| `getTeammatesForIntent()` | 1298-1306 | ✅ 删除 |
| `buildDag()` | 1308-1331 | ✅ 删除 |
| `saveTrace()` | 1381-1389 | ✅ 删除 |
| `adaptive=false` 分支 | 1712-1727 | ✅ 删除，路由简化 |
| `const adaptive` 变量 | 1688 | ✅ 移除 |
| `/api/team/status` | 1735-1737 | ✅ 删除 |

**保留**: `TraceEvent` 接口、`parseReviewEnhanced()` — 仍被 adaptive 引擎使用
**变更**: `parseReviewEnhanced()` 返回类型从 `ReviewResult` 改为内联结构体

---

## 验证

### 1. FSM 关键词 grep

| 关键词 | 匹配分布 |
|--------|---------|
| `FSMWorker` | 仅 docs + `maeos.py`（活跃类名，非 FSM 逻辑）|
| `FSMContext` | 仅 docs + `maeos.py`（活跃类名，非 FSM 逻辑）|
| `FSMOrchestrator` | 仅 docs（代码中已删除） |
| `max_fsm` | 仅 docs |
| `fsm-transitions` | 仅 docs |

**结论**: 代码中无隐蔽的 FSM 编排逻辑生产路径。剩余 `FSMWorker`/`FSMContext` 类名属命名残留（内部已调 `run_pipeline()`），按约束保留。

### 2. 测试结果
```
531 passed, 40 warnings in 59.42s
```

全部通过，无回归。

---

## 约束遵守情况

| 约束 | 状态 |
|------|------|
| 不修改 MAEOS 核心逻辑 | ✅ |
| 不修改 Task Runtime | ✅ |
| 不修改 Planner | ✅ |
| 不修改 Chat 流程 | ✅ |
| 仅删除旧 FSM 编排遗留 | ✅ |
