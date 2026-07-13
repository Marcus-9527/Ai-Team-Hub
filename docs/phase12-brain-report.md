# Phase 12 — Brain Core Parity 架构报告

## 总览

完成 Teammate Brain 系统，将 AI 从"带记忆的 Agent"升级为"长期成长的 AI Teammate"。

### 阶段覆盖

| Phase | 内容 | 状态 |
|-------|------|------|
| 12.1 | Brain Fragment 数据模型 | ✅ |
| 12.2 | BrainLoader — 统一 Prompt 构建 | ✅ |
| 12.3 | Reflection System | ✅ |
| 12.4 | Brain UI 前端 | ✅ |
| 12.5 | Memory Fusion | ✅ |

## Phase 12.1 — Brain Fragment 数据模型

**文件**: `backend/services/brain/fragment_store.py`

**设计原则**:
- 不新增 SQLAlchemy Model/表 — 复用现有 `memory_items` 表和 `MemoryService`
- `BrainFragment` = 带 type namespace (`brain:*`) 的 `MemoryItem` 薄封装
- 版本号存储在 `metadata["fragment_version"]`，每次 `store()` 自动递增

**Fragment 类型 (BrainFragmentType)**:
- `brain:identity` — AI 身份/角色定义
- `brain:personality` — 性格特征
- `brain:principles` — 核心原则
- `brain:responsibilities` — 职责范围
- `brain:skills` — 技能列表
- `brain:lessons` — 经验教训 (Reflection 自动生成)
- `brain:decisions` — 过往决策记录
- `brain:preferences` — 偏好
- `brain:behavior_suggestion` — 行为改进建议
- `brain:proposal` — 待批准核心人格修改 (保留用)

**版本历史**: 每个 `store()` 是新行，不修改现有行
**回滚**: 复制目标版本的 content 为新行，source 标记为 `rollback_from_v{N}`

## Phase 12.2 — BrainLoader

**文件**: `backend/services/brain/brain_loader.py`

**调用链**:
```
TeammateRuntimeContext → BrainLoader.build_prompt() → LLM
```

**加载内容**:
1. Identity — 你是谁
2. Personality — 你的性格
3. Principles — 你的原则
4. Skills & Abilities — 你会什么
5. Lessons Learned — 你学到什么
6. Past Decisions — 过去怎么决策
7. Preferences — 偏好什么
8. Recent Memory — 近期经验

**集成点**: `build_turn_prompt()` 在 `teammate_runner.py` 中用于 chat 路径。
`run_engineer_workflow()` 和 `run_reviewer_workflow()` 通过 system_prompt 前缀接收 Brain 上下文。

## Phase 12.3 — Reflection System

**文件**: `backend/services/brain/reflection.py`
**Hook**: `backend/services/brain/task_hook.py`

**触发点**:
| 事件 | 来源 | 生成内容 |
|------|------|----------|
| Task 完成 | `MemoryTaskHook` → `BrainTaskHook.on_task_completed()` | LESSON (what worked) |
| Task 失败 | `BrainTaskHook.on_task_failed()` | LESSON (what went wrong) |
| Review rejected | `TaskOrchestrator._reflect_rejection()` | BEHAVIOR_SUGGESTION |

**注册**: `main.py` 中 `BrainTaskHook` 已注册到 `TaskHookRegistry`。

**安全限制**:
- 核心人格 (identity/personality/principles) 的修改通过 `brain:proposal` 类型走 pending proposal
- Reflection 只生成 LESSONS 和 BEHAVIOR_SUGGESTION

## Phase 12.4 — Brain UI

**文件**: `frontend/src/components/Brain/BrainPage.jsx`

**功能**:
- Teammate 选择器 (左侧)
- Fragment 列表 (展开显示 content + 版本历史)
- 版本历史浏览 + 回滚按钮
- Brain 概览 (数量/类型/来源分布)
- Prompt 预览 (BrainLoader 构建的实际 prompt)
- 入口: 开发者模式下侧边栏 Brain 按钮

**API 客户端**: `frontend/src/services/api.js` 新增 8 个 brain API 方法

## Phase 12.5 — Memory Fusion

**文件**: `backend/services/brain/consolidation.py`

**规则**: Memory = 短期经验 → Brain = 长期知识

**流程**:
1. 扫描最近 48h 的 teammate-scoped memory items
2. 对 teammate + type 分组
3. 每组关键词提取 + Jaccard 聚类
4. 3+ 同类事件 → 创建 consolidated brain fragment
5. 与已有 fragment 对比，避免重复 (Jaccard > 0.6 跳过)

**触发**: `BrainTaskHook.on_task_completed()` fire-and-forget + POST `/api/brain/consolidate`

## API 端点

| Method | Path | 说明 |
|--------|------|------|
| GET | `/api/brain` | 概览 (memory + insights + evaluations) |
| GET | `/api/brain/memory` | 查询 memory items |
| GET | `/api/brain/search` | 语义搜索 |
| POST | `/api/brain/reflect` | 触发 insight generation |
| GET | `/api/brain/fragments/{tm_id}` | 列出一个 teammate 的所有 fragment |
| GET | `/api/brain/fragments/{tm_id}/{type}` | 获取最新版本 |
| GET | `/api/brain/fragments/{tm_id}/{type}/versions` | 列出版本历史 |
| POST | `/api/brain/fragments/{tm_id}/{type}/rollback` | 回滚到指定版本 |
| GET | `/api/brain/loader/{tm_id}` | 预览 BrainLoader prompt |
| GET | `/api/brain/fragment-types` | 列出所有 fragment 类型 |
| POST | `/api/brain/consolidate` | 触发 Memory→Brain consolidation |

## 测试结果

```
8 passed in 0.39s
```

- `test_brain_version.py` — 版本递增、回滚、get_latest 正确性
- `test_brain_loader.py` — 构建 prompt、teammate 隔离
- `test_reflection.py` — 完成/失败/拒绝 三种触发路径
