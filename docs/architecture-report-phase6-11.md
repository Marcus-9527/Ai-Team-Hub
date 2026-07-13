# AI Team Hub — 架构报告 (Phase 6-11 产品化升级)

> 生成时间: 2026-07-13 · 报告版本: 1.0

---

## 一、架构总览

```
frontend/  ── React + Vite + Tailwind + Framer Motion + GSAP
   │
   ├── http://localhost:8910/api/*  (dev proxy)
   │
backend/   ── FastAPI + SQLAlchemy + aiosqlite
   │
   ├── routes/         ← HTTP 层 (9 个 router)
   ├── services/       ← 业务逻辑 (task, memory, runtime, teammate)
   ├── models.py       ← SQLAlchemy 模型 (14 个 Base 子类)
   ├── database.py     ← DB 引擎 + session 工厂
   └── main.py         ← FastAPI app + lifespan
```

### 路由拓扑 (Phase 6-11 新增以 → 标记)

| 路由 | 方法 | 用途 | Phase |
|------|------|------|-------|
| `/api/brain` | GET | 聚合 memory + insight + evaluation 统计 | **6** |
| `/api/brain/memory` | GET | 查询记忆项 (brain fragments) | **6** |
| `/api/brain/search` | GET | 语义搜索 (embedding cosine similarity) | **9** |
| `/api/brain/reflect` | POST | 触发反射 (insight 生成) | **6** |
| `/api/automation` | GET | 列出自定自动化规则 | **7** |
| `/api/automation` | POST | 创建规则 | **7** |
| `/api/automation/{id}` | DELETE | 删除规则 | **7** |
| `/api/automation/{id}` | PATCH | 启用/禁用规则 | **7** |
| `/api/demo/init` | POST | 初始化 demo workspace | **11** |

### 核心变更行数统计

| 文件 | 操作 | 行数 |
|------|------|------|
| `backend/routes/brain.py` | 新建+重写 | 104 |
| `backend/routes/automation.py` | 新建 | 140 |
| `backend/routes/demo.py` | 新建 | 118 |
| `backend/services/task/task_orchestrator.py` | 修改 (+28) | ✅ |
| `backend/models.py` | 修改 (+23) | ✅ |
| `backend/main.py` | 修改 (+9) | ✅ |
| **总计净增** | **(不含前端) ~350 行** | |

---

## 二、Phase 6: Brain Layer

### 设计原则
Brain 不是新引擎——它是已有子系统 (`MemoryService`, `MemoryIntelligenceService`, `EvaluationService`) 的**薄聚合层**。

### brain_fragments
现有 `memory_items` 表 (model: `MemoryItemModel`) 已存储：
- `content` — 记忆片段文本
- `embedding_json` — 语义向量 (JSON float list)
- `memory_type` — WORKFLOW_INSIGHT / DECISION / FEEDBACK / THOUGHT
- `source_id` — 关联任务 ID (多对一)

`/api/brain/memory` 直接转发 `MemoryService.query()`，不做二次封装。

### BrainLoader 和 Reflection Worker
- **BrainLoader** = `MemoryService.store()` + `MemoryTaskHook`（任务生命周期 → 自动存储）
- **Reflection Worker** = `MemoryIntelligenceService.process_task_completion()`
- 触发路径：任务完成 → `_techlead_relay`/`_review_relay` → 记忆事件 → 批处理 → `_reflect()`
- `/api/brain/reflect` 提供手动触发端点（202 异步返回）

### Brain UI
DeveloperCenter 第四张 Brain 卡片，显示：
- 记忆条目计数
- 评价统计 (总分/均分)
- 最新 Insight 摘要
- 依赖：`/api/brain` GET 端点

### Ponytail 简化
- 未创建 "BrainEngine" 或类似抽象——Brain 是命名空间而非实现
- Reflection 复用已有的 task completion hook 路径

---

## 三、Phase 7: Automation Layer

### AutomationRule 模型
```python
class AutomationRuleModel(Base):
    id, name, description, schedule_interval_sec,
    task_title, task_intent, channel_id, team_ids,
    is_active, last_triggered_at, created_at, updated_at
```

### 轮询机制
不是独立调度器——是 `lifespan` 中一个 `asyncio.create_task` 后台循环：
1. 每 30 秒扫描 `is_active='1'` 的规则
2. 检查 `last_triggered_at` + `schedule_interval_sec` 是否到期
3. 到期 → 通过 `TaskManager.create_task()` 创建任务
4. `asyncio.create_task(orch.start_task())` 异步编排
5. 更新 `last_triggered_at`

### Ponytail 简化
- 未创建 cron / FSM / scheduler 引擎
- 30 秒轮询硬编码 → 可升级为精确调度（当前无业务需要）
- 错误不影响主循环（`try/except` 包裹）

---

## 四、Phase 8: TechLead DAG 协作

### 协作流程
```
Task → TaskOrchestrator → DAG (多 Teammate 并行)
   │
   ├── Engineer step(s)
   ├── Reviewer review (existing _review_relay)
   ├── TechLead synthesis ** (Phase 8 NEW)
   └── COMPLETED / FAILED
```

### _techlead_relay 实现
1. 检测 `detect_role(teammate) == "techlead"` 的现有 teammate
2. 收集所有 TaskStep 的 `output` 字段
3. 以 "synthesis" 标签存入 TechLead 的 teammate memory
4. 触发 SSE 事件 `techlead_synthesis`

### DAG 节点去重
TechLead 如果已存在于 DAG 节点中直接参与执行，则 relay 跳到 reviewer。未参与则自动充当聚合格。

### Ponytail 简化
- 未创建新的 `TechLeadEngine` 或 `DAGCoordinator` 类
- 复用 `_store_review_memory` 作为存储通用方法
- 单次 fire-and-forget，不阻塞主执行流

---

## 五、Phase 9: Embedding Memory

### 已有基础设施
- `MemoryService.compute_embedding()` — 静态方法，基于 sentence-transformers + 哈希缓存
- `MemoryService.semantic_search()` — numpy 余弦相似度 + top-k 筛选
- `MemoryItemModel.embedding_json` — 存储列
- `memory_event_handler._store()` — 自动在存储时计算 embedding

### Phase 9 增量
- 新增 `/api/brain/search?q=TEXT&top_k=10` 端点
- 前端 MemoryPanel 可使用此端点实现搜索栏（API 已就绪）

### Ponytail 简化
- 未创建新的 embedding 服务或 FAISS 索引
- 线上搜索 = 全量余弦扫描（O(n)） → 足够当前规模 (<10K items)
- `ponytail: O(n²) naive scan, add vector index (ANN) when items exceed 10K`

---

## 六、Phase 10: Docker 部署

### 多阶段构建
```
Stage 1 (frontend-builder):
  node:20-alpine → npm ci → vite build → /app/frontend/dist/

Stage 2 (runtime):
  python:3.12-slim → pip install → copy backend/ + built frontend → uvicorn
```

### docker-compose
- Named volume `aiteamhub_data` → `/app/data/`
- Health check via `/api/health`
- `restart: unless-stopped`
- 环境变量模板 (`.env.example`)

### 部署文档
`deploy/README.md` 包含：
- Docker 快速启动步骤
- 环境变量表格
- 生产清单 (加密密钥, CORS, PostgreSQL, 反向代理)
- 手动启动步骤 (无 Docker)

---

## 七、Phase 11: Demo 流程

### `/api/demo/init` 端点
幂等地创建：
1. 3 个 demo teammates (工程师 / PM / TechLead)
2. 1 个 "Demo" channel
3. 1 个示例任务（自动触发后台编排）

### 幂等性
已存在的 teammate/channel 基于 `name` 跳过创建，仅返回已有 ID。

### Ponytail 简化
- 硬编码 demo 数据 — 无配置化/模板化（一次性使用场景）
- 后台编排 fire-and-forget — 非阻塞

---

## 八、技术债务标记

| 标记 | 位置 | 说明 | 升级路径 |
|------|------|------|----------|
| `ponytail` | `brain.py` | Brain 是聚合标签而非独立服务 | 当需要独立 Brain 计算集群时解耦 |
| `ponytail` | `automation.py` | 30s 硬编码轮询间隔 | `schedule_interval_sec` 字段已就绪，只是检查频率硬编码 |
| `ponytail` | `memory_service.py` | 全向量余弦扫描 | 当 items > 10K 时换 FAISS/ANN |
| `ponytail` | `task_orchestrator.py` | TechLead 合成内存而非执行流 | 当需要 TechLead 修改 DAG 结构时改为异步调用 |
| `ponytail` | `automation.py` | 无精确 cron 调度 | 需升级到 apscheduler 时再加 |

---

## 九、总结

Phase 6-11 以 **~350 行后端净变更** 完成了从 "团队协作 Hub" 到 "AI Team OS" 的核心升级：

- **Brain Layer** — 现有服务的聚合窗口（+104 行）
- **Automation** — 30 行模型 + 110 行轮询引擎（复用 TaskOrchestrator）
- **TechLead** — 28 行 relay 方法注入 DAG 流程
- **Embedding** — 自动计算已存在，仅需搜索端点（0 新业务行）
- **Docker** — 多阶段构建 + Compose + 文档
- **Demo** — 幂等初始化端点（118 行）

全部遵循 Ponytail 原则：复用超过新建，删除超过增加，无新引擎/FSM/调度器。
