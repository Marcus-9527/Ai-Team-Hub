# Phase 15: Product Dashboard — UI 说明

## 组件结构

```
DashboardPage.jsx (单页仪表盘)
├── Header             — 标题 + 概述
├── Team Overview      — 队友数 / 总执行 / 成功率 / DAG 数
├── Execution Overview — 已完成 / 失败 / 运行中 / Token / 成本
├── Memory Statistics  — 总记忆 + 类型分布柱状图
└── Teammate Growth    — 队友创建时间线
```

## 入口

侧边栏新增「仪表盘」按钮（BarChart3 图标），点击切换显示。

## 状态

- **加载中** — Loader2 旋转动画
- **加载失败** — XCircle 红色错误提示
- **数据正常** — 4 段 StatCard 网格布局

## 数据源

全部来自 `GET /api/dashboard` 单次聚合请求，零冗余调用。
