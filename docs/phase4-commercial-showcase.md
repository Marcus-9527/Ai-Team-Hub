# AI Team Hub — 商业化展示说明

## 卖点概览

AI Team Hub 是一个**多智能体协作平台**，AI 队友以「数字员工」身份自动完成软件工程全流程。

### 30 秒电梯演讲

> 你的 AI 开发团队：输入需求 → 自动规划 → Engineer 编码 → Reviewer 审查 → 交付代码。
> 一个人工审批门把控风险。全过程可追溯。

### 竞品对比

| 竞品 | AI Team Hub |
|------|-------------|
| GitHub Copilot | 单行补全。我们是**全流程协作** |
| Cursor Agent | 单 Agent。我们是**多角色团队** |
| Devin | 封闭系统。我们**开源可控** |
| AutoGPT | 玩具。我们有**审批门 + 交付追踪** |

### 三大核心能力

| 能力 | 可见于 |
|---|---|
| 🤖 **多角色 AI 团队** — Engineer / Reviewer / TechLead 各自扮演数字员工角色 | 队友面板、任务指派 |
| 🔐 **人工审批门** — 高风险操作（部署、高成本调用）需人批准后才能执行 | 任务审批 Tab |
| 📦 **交付可追踪** — Code change → Test → Review → Commit 全链路可视 | 交付状态卡片 |

---

## 演示指引

### Demo 1: 创建并执行一个任务（核心流程）

1. 打开已配置好的频道——展示队友面板（Engineer / Reviewer / TechLead）
2. 输入任务："给登录页面加密码强度指示器"
3. 观察系统**自动规划** 3 步（显示在 Plan 面板）
4. Engineer 开始执行 → **流式实时输出**（代码、日志）
5. Engineer 完成后 → Reviewer 自动审查
6. 「交付状态」卡片出现：变更文件列表、测试结果、Git commit hash

### Demo 2: 人工审批流程

1. 创建高风险任务（如"生产环境部署"或"删除数据库表"）
2. 系统自动标记为 **MEDIUM 风险**，需审批
3. 「审批 Tab」显示待审核步骤
4. 点击「批准」→ Engineer 继续执行
5. 点击「拒绝」→ 任务暂停，记录原因

### Demo 3: 交付追踪

1. 已完成任务的概览页显示「交付状态」卡片
2. 查看 Code Review 结果（通过/拒绝）
3. 查看 Git Commit hash（可点击跳转）
4. 查看变更文件列表（带 diff 预览）
5. 展开测试结果详情

### Demo 4: 自定义队友

1. 进入队友面板 → 点击「创建队友」
2. 设置角色：名称、System Prompt、模型 Provider/Model
3. 保存后，新建频道中添加该队友
4. 新队友在下一轮自动协作出现在任务流中

---

## 商业化架构亮点

### 1. 统一运行时上下文

```
用户请求 → TaskPlan → TeammateRuntimeContext → ExecutionRuntime
                                                    │
                                        ┌───────────┤
                                        ▼           ▼
                                  Engineer       Reviewer
                                  Workflow       Workflow
```

每个执行单元携带完整的身份、模型、提示词、工作空间作用域信息，无需临时从数据库加载。

### 2. 分层记忆系统

```
GLOBAL       ← 系统全局规则
WORKSPACE    ← 工作空间约定
TEAMMATE     ← 队友个人偏好
CHANNEL      ← 频道对话上下文
TASK         ← 任务目标与约束
EXECUTION    ← 执行结果与性能信号
```

AI 队友在多次任务中学习用户偏好，保持风格一致性。

### 3. 安全防护

| 风险等级 | 行为 |
|---|---|
| LOW | 自动执行 |
| MEDIUM | 人工审批后方可执行 |
| HIGH | 策略阻断，无法执行 |

无需额外的权限系统或角色管理，满足最简商业安全需求。

---

## 部署方式

| 方式 | 适合客户 | 复杂度 |
|------|---------|--------|
| Docker Compose（推荐） | 中小团队 | 1 命令启动 |
| K8s（高级） | 企业客户 | 需要 K8s 集群 |
| Cloudflare Workers | 云原生团队 | 现有 wrangler.toml |

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python 3.12 + FastAPI + SQLAlchemy async |
| 前端 | React + Vite + Tailwind CSS + Framer Motion |
| 测试 | pytest + pytest-asyncio, 583 tests |
| 构建 | vite build (~7s, 871KB JS bundle) |
| LLM | 多 Provider（OpenAI / Anthropic / 自定义） |
| 部署 | Docker / K8s / Cloudflare Workers |

---

## 后续演进（按需）

- 外部开发者 API Key 管理（ClientKey 模型）
- Usage 统计面板（已有执行数据）
- K8s 部署清单
- 定价与许可模式
