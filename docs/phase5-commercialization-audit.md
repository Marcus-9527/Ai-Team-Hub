# Phase 5 — 商业化审计报告

> 基于 2026-07-13 代码库状态。禁止新增 Agent 能力、复杂 Runtime、大规模重构。

---

## 核心商业策略：Self-Hosted First

**不做 SaaS 多租户。** 产品作为可部署的私有 AI 团队平台售卖。

理由：
- 多租户 = 用户系统 + org 模型 + 数据隔离 + 计费 + 合规，至少 3-6 人月
- 用户明确禁止企业级过度工程
- 当前产品卖点（数字员工、审批门、交付追踪）在单租户场景下已完整可展
- 切换到 PostgreSQL 即可支持单客户多用户（同一 org 内），无需租户隔离层

---

## 1. 多租户改造成本估算

| 方案 | 成本 | 说明 |
|------|------|------|
| **Self-hosted（推荐）** | **0 人日** | 客户自己部署，无需改造 |
| SaaS 单 DB + tenant_id | ~45 人日 | 加 Org/User 模型、所有表加 tenant_id、路由过滤 |
| SaaS 独立 DB 实例 | ~60 人日 | 连接池管理、数据库迁移、备份策略 |

**结论：跳过。** 自我部署模式零改造成本。

---

## 2. 数据隔离方案

现状：单 SQLite 文件，全用户共享。

**推荐路径：**
- Self-hosted 客户：自带 DB（SQLite 或 PostgreSQL），天然隔离
- **只需加一行文档**：`DATABASE_URL` 指向客户自有 PostgreSQL 实例
- 同一 Org 内多用户：PostgreSQL schema + `user_id` 字段过滤（`FileUpload.user_id` 已存在）

**ponytail: 已有 `user_id` 在 `FileUpload` 表和 `created_by` 在 `TaskModel` 表。复用即可。无需新抽象。**

---

## 3. API Key 管理

现状（已完善）：

| 能力 | 状态 |
|------|------|
| 加密存储 | ✅ Fernet 加密 + Key Vault Service |
| 多 Provider 支持 | ✅ openai/deepseek/anthropic/自定义 |
| 轮换/吊销 | ✅ POST /rotate, POST /revoke |
| Admin 防护 | ✅ AI_TEAM_HUB_ADMIN_KEY |
| 日志过滤 | ✅ APIKeyFilter 阻止 key 泄漏 |

**缺失：** 外部开发者 API Key（不是 provider key，是 client key）。

**改动：** 新增 `ClientKey` 模型（比 `APIKey` 精简，只存 hash + label + is_active）。
- `POST /v1/keys` 创建（返回完整 key 仅一次）
- `GET /v1/keys` 列表（不返回值）
- `DELETE /v1/keys/{id}` 吊销

**ponytail: 5 个文件，~80 行后端逻辑。当前 AuthMiddleware 已处理 `X-API-Key` 验证框架。**

---

## 4. Usage 统计

现状：

| 数据 | 位置 |
|------|------|
| Token 用量 | `TaskExecutionModel.input_tokens/output_tokens/total_tokens` |
| 成本（微美元） | `TaskExecutionModel.estimated_cost` |
| 执行耗时 | `TaskExecutionModel.execution_time_ms` |
| 执行记录 | `ExecutionRecordModel` |
| 统计端点 | `GET /api/executions/stats` 已注册 |

**ponytail: 统计管线已完整运行。缺的是一层聚合到可计费单位。**

**最小改动：** 新增 `GET /v1/usage` 端点，聚合过去 30 天：
- 请求数、token 数、成本（µ$）、平均延迟
- 按日聚合，返回时间序列

```python
# routes/usage.py — 约 40 行
@router.get("/v1/usage")
async def v1_usage(days: int = 30):
    # SELECT DATE(created_at), COUNT(*), SUM(total_tokens), SUM(estimated_cost)
    # FROM task_executions WHERE created_at > NOW() - days
    # GROUP BY DATE(created_at) ORDER BY DATE(created_at)
```

**跳过计费系统。** 客户部署时用量只是一个数字，不触发任何自动动作。

---

## 5. SaaS 部署方案

**不推荐 SaaS。** 如果客户要求托管部署：

- 前端：Cloudflare Workers（已有 `wrangler.toml`）
- 后端：单容器跑在客户 VPS（Docker Compose）
- DB：客户提供 PostgreSQL（RDS / Supabase / Neon）
- 监控：客户自己加 Sentry/Grafana

**改动：零。** 写一页部署架构说明文档。

---

## 6. Docker/K8s 部署

现状：

| 组件 | 状态 |
|------|------|
| Dockerfile | ✅ Python 3.12-slim, 25 行, uvicorn |
| docker-compose.yml | ✅ 单服务 + named volume + healthcheck |
| K8s manifests | ❌ 不存在 |

**所需改动：**

### 6.1 Docker 增强（2 文件，~15 行）
- `Dockerfile`：增加 `HEALTHCHECK` 指令（已有）+ 非 root 用户
- `docker-compose.yml`：加 `restart: unless-stopped`（已有）+ 资源限制

### 6.2 K8s 清单（新建目录 `deploy/k8s/`）

**最小集合（4 文件，每个 ~30 行）：**

```
deploy/k8s/
├── deployment.yaml    # Deployment + Service (NodePort)
├── configmap.yaml     # 环境变量
├── pvc.yaml           # 持久化数据
└── ingress.yaml       # (可选) Ingress
```

**ponytail: K8s 清单没有运行时依赖。一次性编写，客户按需修改。跳过 Helm chart（Helm 本身是过度工程）。**

---

## 7. Demo 场景打磨

现状：Phase 4 已输出 3 个 Demo 场景（任务执行、审批流、交付追踪）。

**增强方向：**

### Demo 1: 30 秒电梯演讲
```
"你的 AI 开发团队：输入需求 → 自动规划 → Engineer 编码 → Reviewer 审查 → 交付代码。
一个人工审批门把控风险。全过程可追溯。"
```

### Demo 2: 产品亮点对比表

| 竞品 | AI Team Hub |
|------|-------------|
| GitHub Copilot | 单行补全。我们是全流程协作 |
| Cursor Agent | 单 Agent。我们是多角色团队 |
| Devin | 封闭系统。我们开源可控 |
| AutoGPT | 玩具。我们有审批门+交付追踪 |

### Demo 3: 可视化 Demo 脚本
```
1. 打开已配置好的频道——展示队友面板（Engineer/Reviewer/TechLead）
2. 输入任务：“给登录页面加密码强度指示器”
3. 系统自动规划 3 步 → Engineer 执行 → 实时流式输出
4. 切换「审批」Tab 展示高风险步骤待批准
5. 批准 → Reviewer 审查 → 交付状态卡片出现
6. 展示：变更文件列表、测试结果、Git commit hash
```

**改动：** 只需要修改 `docs/phase4-commercial-showcase.md`，增加上述内容。

---

## 8. 产品定价模型

### 方案 A：Self-hosted 按年许可（推荐）

| 套餐 | 价格（估算） | 包含 |
|------|------------|------|
| **Starter** | $499/年 | 单项目，3 AI 队友，社区支持 |
| **Team** | $1,999/年 | 无限项目，10 AI 队友，邮件支持 |
| **Enterprise** | $7,999/年 | 无限用户/队友，SSO，SLA，专属支持 |

### 方案 B：SaaS 月付（仅当有托管需求时）

| 套餐 | 价格 | 包含 |
|------|------|------|
| Free | $0 | 1 频道，2 队友，50 次/月 |
| Pro | $29/月 | 5 频道，10 队友，无限次数 |
| Team | $99/月 | 无限，自定义模型，审批门 |

**ponytail: 定价先写文档。不写计费代码，因为自我部署模式下我们只收许可证费，不存在计量环节。**

---

## 技术改造清单（按优先级）

| # | 任务 | 文件数 | 行数估 | 优先级 |
|---|------|--------|--------|--------|
| P0 | 写这份文档 + 定价文案 | 1 | ~200 | **本周** |
| P1 | 增强 Docker 部署（非 root 用户 + 资源限制） | 2 | ~15 | **本周** |
| P1 | 写 K8s 部署清单 | 4 | ~120 | 第 2 周 |
| P2 | 新增 ClientKey 模型（外部开发者 API Key） | 5 | ~80 | 第 2 周 |
| P2 | 新增 `/v1/usage` 聚合统计端点 | 2 | ~60 | 第 2 周 |
| P3 | 写部署架构说明文档 | 1 | ~50 | 第 3 周 |
| P3 | Demo 脚本打磨（更新 showcase.md） | 1 | ~50 | 第 3 周 |
| Px | 前端登录页 / API Key 输入 UI | 3 | ~150 | 按需 |

**总计工作量：~675 行，5-7 人日。**

---

## 商业化路线图

```
Week 1          Week 2          Week 3          Week 4
│               │               │               │
├─ 定价文档     ├─ K8s 清单     ├─ 部署文档     ├─ 准备 Pitch Deck
├─ Docker 增强  ├─ ClientKey    ├─ Demo 脚本     ├─ 客户演示
│▲              ├─ Usage API    │                │
││              │▲              │                │
││  MVP 可售    ││  二次迭代     │  打磨          │  签约
```

---

## 禁止清单确认

| ❌ 不做 | 理由 |
|---------|------|
| 用户注册/登录系统 | Self-hosted 客户自己管控 |
| Org 多租户隔离 | 零收入贡献，3 人月投入 |
| SaaS 计费系统 | 无 SaaS 部署就不需要计费代码 |
| 角色权限 RBAC | 单一 org 内团队信任模型 |
| 审计日志系统 | PostgreSQL 日志 + 客户自己的 ELK |
| 自定义审批链 | 当前单级审批覆盖 80% 场景 |
| 第三方集成 webhook | 无客户需求信号前不做 |
| Helm chart | K8s 清单已够用，Helm 是 DSL 过度工程 |
