# Phase 13 — Autonomous Collaboration 架构报告

## 总览

Phase 13 实现 Helio 风格的 Teammate 自主协作机制。五个子模块复用现有服务（TaskOrchestrator、ExecutionRuntime、BrainLoader、MemoryService、AutomationRule），无新建 FSM/调度器/引擎。

### 模块结构

```
backend/services/autonomous/
├── __init__.py                  — 模块入口
├── teammate_state.py            — TeammateRuntimeState (Phase 13.4)
├── cede_protocol.py             — Cede Protocol (Phase 13.1)
├── task_claim.py                — Task Claim Protocol (Phase 13.2)
├── event_wakeup.py              — Event Wakeup Bus (Phase 13.3)
└── brain_proposal.py            — Brain Proposal Approval (Phase 13.5)

backend/routes/autonomous.py     — 14 个 API 端点

frontend/src/components/Brain/
├── BrainPage.jsx                — (已有) 展示 fragments + Prompt 预览
└── ProposalApprovalPage.jsx     — 提案审批 UI
```

---

## Phase 13.1 — Cede Protocol

**文件**: `backend/services/autonomous/cede_protocol.py`

**功能**: 每个 teammate 判断是否响应消息，避免多个 AI 重复回复。

**决定类型**:
| 决策 | 说明 |
|------|------|
| RESPOND | 该队友有相关内容要回复 |
| CEDE | 没有新信息，让给其他人 |
| IGNORE | 消息彻底不相关 |

**策略 (Tiered)**:
1. **Tier 1**: 已回应过 → CEDE（同消息同 teammate 不重复）
2. **Tier 2**: 已有其他 teammate RESPOND → CEDE（单消息单回复）
3. **Tier 3**: Role-based 关键词匹配 → RESPOND/CEDE/IGNORE

**记录**: 所有决策写入 memory (MemoryType.DECISION)，支持通过 API 查询 (`GET /cede/decisions/{message_id}`)

**集成点**: `team_collaboration.py::generate_team_response()` 在遍历 teammate 前调用 `cede_protocol.decide()`，过滤不等于 RESPOND 的队友。

---

## Phase 13.2 — Task Claim Protocol

**文件**: `backend/services/autonomous/task_claim.py`

**功能**: Task 创建后多个 teammate 竞争 claim，原子确认 owner。

**机制**:
1. Claim 窗口期 (30s) — 允许最多 10 个 claimer 竞争
2. 原子锁 — `asyncio.Lock` 确保第一个 caller 获胜
3. 后续 claim 被拒绝，但记录所有 attempt
4. Claim 成功后 teammate state → WORKING

**记录**: 通过 memory (MemoryType.DECISION) 持久化 claim 记录。

---

## Phase 13.3 — Event Wakeup

**文件**: `backend/services/autonomous/event_wakeup.py`

**功能**: 事件驱动 teammate 唤醒。

**事件类型**:
| 事件 | 触发时机 | 默认处理 |
|------|----------|----------|
| TASK_CREATED | 新任务创建 | 枚举 available teammates → claim 竞争 |
| TASK_FAILED | 任务失败 | 写入 alert memory（等开发者决定） |
| REVIEW_REJECTED | Review 驳回 | 写入 alert memory（orchestrator 已创建 fix task） |
| BRAIN_UPDATED | Brain 片段更新 | 空（未来可做 cache 失效） |

**设计**: 
- 事件总线模式 — `subscribe() / fire()` 
- 默认处理器通过 `register_default_handlers()` 启动时注册
- 离线处理器记录历史 (max 200)
- 复用 asyncio.create_task 做 fire-and-forget

---

## Phase 13.4 — Teammate Runtime State

**文件**: `backend/services/autonomous/teammate_state.py`

**状态**:
| 状态 | 说明 | is_available |
|------|------|-------------|
| ACTIVE | 在线就绪 | ✅ |
| IDLE | 在线但空闲 | ✅ |
| WORKING | 执行任务中 | ❌ |
| OFFLINE | 已离线 | ❌ |

**功能**:
- 状态迁移记录（每次变更写入 memory）
- `is_available` — Cede Protocol 和 Task Claim 的基础
- 状态历史（最多 100 条）
- 空闲计时器 (`idle_seconds` / `consecutive_idle_seconds`)

---

## Phase 13.5 — Brain Proposal Approval

**文件**: `backend/services/autonomous/brain_proposal.py`

**流程**: Reflection → Proposal → 人工批准 → 写入 Brain

**Proposal 生命周期**:
```
CREATED → APPROVED → 自动写入 BrainFragment
       → REJECTED → 无操作
       → EXPIRED  → 72h 超时自动过期
```

**Proposal 内容**:
- `target_type`: 要修改的 BrainFragmentType
- `proposed_content` / `original_content`: 变更前后对照
- `diff_summary`: 自动生成的变更摘要（关键词级 diff）
- `task_id`: 触发的 task

**集成**: 
- ReflectionService 检测到核心人格需修改时创建 proposal
- UI 审批后自动写入 BrainFragmentStore
- 批准后 fire BRAIN_UPDATED event

---

## API 端点 (14 个)

| Method | Path | 说明 |
|--------|------|------|
| GET | `/api/autonomous/states` | 列出所有 state |
| GET | `/api/autonomous/states/{id}` | 获取单个 state |
| POST | `/api/autonomous/states` | 设置 state |
| POST | `/api/autonomous/cede/decide` | Cede 决策 |
| GET | `/api/autonomous/cede/decisions/{msg_id}` | 查询决策记录 |
| POST | `/api/autonomous/claim` | Task claim |
| GET | `/api/autonomous/claim/{task_id}` | 查询 claim 记录 |
| DELETE | `/api/autonomous/claim/{task_id}` | 清除 claim |
| POST | `/api/autonomous/event` | Fire wakeup event |
| GET | `/api/autonomous/events` | Event 历史 |
| GET | `/api/autonomous/proposals` | 列出 proposals |
| GET | `/api/autonomous/proposals/pending` | 待审批列表 |
| POST | `/api/autonomous/proposals` | 创建 proposal |
| POST | `/api/autonomous/proposals/approve` | 批准 |
| POST | `/api/autonomous/proposals/reject` | 拒绝 |
| POST | `/api/autonomous/proposals/expire` | 过期清理 |

## 测试结果

```
19 passed in 0.59s
```

| 测试文件 | 用例 | 覆盖 |
|----------|------|------|
| `test_cede_protocol.py` | 3 | 单响应、不重复、记录完整 |
| `test_task_claim.py` | 5 | 先到先得、拒绝、并发原子性、记录、清理 |
| `test_event_wakeup.py` | 4 | 分发、空订阅者、历史、默认注册 |
| `test_brain_proposal.py` | 3 | 创建、批准写入、拒绝无写入、pending 计数 |
| `test_teammate_state.py` | 3 | 迁移、历史回放、available 过滤 |

## 关键设计决策

1. **无新 FSM/调度器/引擎** — 所有模块绕过系统，纯 async 函数 + asyncio.Lock + fire-and-forget
2. **Ponytail 不简化** — 每个 Protocol 独立文件，含完整错误处理、日志、memory 持久化
3. **State 在内存** — state 是瞬态的，通过 memory 做 crash recovery。重启后状态丢失但 history 可回放
4. **Cede 决策是 heuristic 的** — 当前用 role-based 关键词。可升级为 LLM 判断（POST body 含 teammate 完整 system_prompt）
5. **Proposal 自动过期** — 72h TTL，防止 pending proposal 堆积
6. **Event Wakeup 默认处理** — TASK_CREATED 直接触发 claim 竞争，无需人工干预
