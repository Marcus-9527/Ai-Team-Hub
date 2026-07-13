# Phase 15: Product Dashboard — 架构文档

## 概述

一个轻量聚合层，将已有的 observability 数据通过一个 `/api/dashboard` 端点暴露给前端。

## 设计原则

- **不修改核心 Runtime/DAG/Memory 逻辑** — 只读聚合，零侵入
- **复用现有 store/service** — ExecutionStore、MemoryService 直接调用
- **单一聚合端点** — 前端一次请求拿到所有 KPI

## 架构图

```
┌──────────────┐     GET /api/dashboard
│  Frontend    │─────────────────────────────┐
│  Dashboard   │                              │
│  Page        │                              ▼
└──────────────┘                   ┌──────────────────┐
                                   │  routes/         │
                                   │  dashboard.py    │
                                   │  (aggregator)    │
                                   └────┬─────┬────┬──┘
                                        │     │    │
                    ┌───────────────────┘     │    └────────────┐
                    ▼                         ▼                 ▼
           ┌──────────────┐        ┌──────────────┐   ┌──────────────┐
           │ Execution    │        │ Memory       │   │ SQLAlchemy   │
           │ Store        │        │ Service      │   │ (teammate    │
           │ (astats)     │        │ (stats)      │   │ + DAG query) │
           └──────────────┘        └──────────────┘   └──────────────┘
```

## 新增文件

| 文件 | 说明 |
|------|------|
| `backend/routes/dashboard.py` | `/api/dashboard` 聚合路由 |
| `frontend/src/components/Dashboard/DashboardPage.jsx` | 仪表盘主页面 |
| `backend/tests/test_dashboard.py` | API 测试 |

## 修改文件

| 文件 | 改动 |
|------|------|
| `backend/main.py` | 注册 dashboard_router |
| `frontend/src/App.jsx` | 添加 Dashboard 路由 + state |
| `frontend/src/components/Sidebar/Sidebar.jsx` | 添加仪表盘导航按钮 |

## API

**GET /api/dashboard**

```json
{
  "execution": { "total_executions": N, "completed": N, "failed": N, "running": N, "total_tokens": N, "total_cost_micro_usd": N },
  "teammate":   { "total_teammates": N, "total_executions": N, "avg_success_rate": 0.0, "growth": [...] },
  "dag":        { "total_dags": N, "dag_nodes_by_status": {"COMPLETED": N, "FAILED": N} },
  "memory":     { "total_items": N, "by_type": {"EXECUTION": N, "TASK": N, ...} }
}
```

## DB Migration

`data/aiteamhub.db` 缺 `teammates.skills/capabilities/success_rate/average_score/execution_count` 等列。已通过 ALTER TABLE 一次性迁移。
