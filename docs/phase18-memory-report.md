# Phase 18 — Semantic Memory 报告

## 概览

将 Memory 从关键词/metadata 检索升级为语义检索（embedding 余弦相似度）。

## 复用情况

| 模块 | 状态 |
|------|------|
| `MemoryService` | ✅ 复用 — 新增 `metadata_filters` 参数 |
| `BrainLoader` | ✅ 复用 — 新增 `semantic_recall()` + `build_prompt(query=)` |
| `memory_items` 表 | ✅ 复用 — `embedding_json` 列已存在 |
| `MemoryTaskHook` | ✅ 复用 — 自动 embedding 生成已存在 |

**无需新表、新 Model、新 Brain 系统。**

## 变更文件

| 文件 | 变更 |
|------|------|
| `services/memory/memory_service.py` | `semantic_search()` 增加 `metadata_filters` 参数（scope 隔离） |
| `services/brain/brain_loader.py` | 新增 `semantic_recall()`；`build_prompt()` 增加 `query` 参数 |
| `services/runtime/executor.py` | 传入 `task.description` 作为语义查询 |
| `services/runtime/teammate_runner.py` | 传入 `user_message` 作为语义查询（call_teammate + stream_teammate） |
| `tests/test_semantic_memory.py` | 7 个测试覆盖召回/隔离/注入 |

## 核心流程

```
用户消息 / 任务描述
         │
         ▼
BrainLoader.semantic_recall(query, teammate_id, scope?)
         │
         ├─ MemoryService.compute_embedding(query)
         │
         ▼
MemoryService.semantic_search(query_vector, metadata_filters={
    "teammate_id": tm_id,
    "scope": "private"|"workspace"|"channel"|"review"
})
         │
         ▼
cosine 相似度排序 → top-K → 格式化文本 → prompt 注入
```

## Scope 隔离

`metadata_filters` 在 `semantic_search()` 中作为后过滤（因为 SQLite 无 JSON 索引）。过滤规则：

| Filter | 来源 |
|--------|------|
| `teammate_id` | 始终传递（调用者参数） |
| `scope` | 可选，传则精准匹配 |

现有 `memory_items.metadata` 中已存储 `teammate_id`（由 `MemoryTaskHook` + `query_teammate_memory` 写入）。Scope 字段在 Phase 13 的 POST_EXECUTION 事件中已写入。

## 自动记忆生成

已在 Phase 13 实现，无需额外工作：

| 触发点 | 事件 |
|--------|------|
| TASK_CREATED | `MemoryTaskHook.on_task_created()` → MemoryType.TASK |
| TASK_COMPLETED | `MemoryTaskHook.on_task_completed()` → TASK + Summary + 触发 Intelligence |
| TASK_FAILED | `MemoryTaskHook.on_task_failed()` → MemoryType.EVENT |
| STEP_COMPLETED | `MemoryTaskHook.on_step_completed()` → MemoryType.EXECUTION |
| EXECUTION_COMPLETED | `MemoryTaskHook.on_execution_completed()` → DECISION + EXPERIENCE |

所有 event handler 调 `_store()` → `item.embedding = compute_embedding(content)` 自动生成。

## Test 覆盖

```
test_semantic_recall_returns_relevant_items       ✓
test_unrelated_items_not_recalled                 ✓
test_semantic_search_metadata_filters             ✓
test_scope_isolation_tm_a_not_leaked_to_tm_b      ✓
test_scope_private_does_not_include_workspace     ✓
test_build_prompt_semantic_recall_integration     ✓
test_build_prompt_without_query_uses_keyword      ✓
```

既存 24 个 brain/memory 测试全部通过。

## Ponytail 简化标记

| 任务需求 | 实际实现 | 理由 |
|----------|----------|------|
| 新建 `MemoryEmbeddingService` | 未新建 — 直接在 `MemoryService` 扩展 | `compute_embedding` + `semantic_search` 已存在，新 class 是纯 wrapper |
| 新建 Embedding 字段 | 已存在 — `embedding_json` 列 | Phase 13 已实现 |
| 新建自动记忆生成 | 已存在 — `MemoryTaskHook` | Phase 13 已实现 |

## 升级路径

- 哈希 embedding → 真实 embedding 模型：替换 `compute_embedding()` 即可
- SQLite 全表扫描 → 向量索引：memory_items > 10K 行时加 SQLite-VSS 或 pgvector
