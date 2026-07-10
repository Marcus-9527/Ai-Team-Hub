# AI Team Hub — Production Ready Report

> 商业化收敛检查 · 生成于审计当日
> 范围：工程交付形态整理，**不修改核心业务逻辑**
> 项目路径：`/home/liunx/workspace/ai-team-hub`
> 技术栈：FastAPI + SQLAlchemy(async) + SQLite / React18 + Vite / Cloudflare Worker(备选) / Python+TS SDK

---

## 一、当前成熟度评分

| 维度 | 得分 | 说明 |
|------|------|------|
| 功能完整度 | 🟢 8.5/10 | 多队友协作、任务执行、记忆、RAG、观测齐全，530 个测试函数 |
| 代码工程质量 | 🟡 6.5/10 | 模块划分清晰，但存在未完成 merge、死代码、依赖不一致 |
| 部署可交付性 | 🟠 4.5/10 | Dockerfile 有语法错误、无 .dockerignore、README 与实际部署不符 |
| 安全性 | 🔴 3.0/10 | **真实 API Key 已提交进 git**、`/api/*` 全线无鉴权、CORS 非法配置 |
| 文档与新用户上手 | 🟡 6.0/10 | 有部署文档，但 README 只讲 Windows、与 Docker 路径矛盾 |
| **综合** | **🟠 5.3 / 10** | **可用作内部工程原型，但距离对外商业交付有明确差距** |

**一句话结论**：功能层面已相当成熟，但仓库当前处于"未完成合并 + 机密泄露 + 无鉴权"三重阻塞状态，**在修复 P0 项之前不可对外交付**。修复后可快速提升到 7.5+。

---

## 二、已满足项 ✅

- **加密存储**：API Key 使用 Fernet（AES-128-CBC + HMAC）加密落库，`key_vault_service` 统一入口，解密仅在内存，响应从不回传明文（`key_vault_service.py`）。
- **日志脱敏**：`main.py` 挂了 `APIKeyFilter`，拦截 `sk-`/`cfut_`/`Bearer`/`Authorization` 等模式，避免密钥进日志。
- **明文密钥自动迁移**：启动时 `migrate_plaintext_keys()` 扫描存量明文 Key 并加密。
- **启动期加密自检**：`validate_key()` 做加解密往返校验，失败即拒绝启动。
- **上传文件名安全**：落盘用 `uuid4()+ext` 重命名（`messages.py:283`），不使用用户原始文件名，天然规避路径穿越。
- **文件类型白名单**：RAG 上传限制 `pdf/docx/txt/md`（`files.py:120`）。
- **用户级数据隔离**：文件详情/删除校验 `file_obj.user_id != user_id`（`files.py:202,291`）。
- **依赖版本锁定**：`backend/requirements.txt` 精确 pin，并注释了 starlette / sse-starlette 的兼容性陷阱（很好的工程实践）。
- **DB 并发**：启用 WAL + `synchronous=NORMAL`，适配 SQLite 并发写。
- **测试覆盖**：530 个测试函数，覆盖 memory / task / security / streaming / stress。
- **健康检查**：`/api/health` + Docker HEALTHCHECK 到位。
- **MCP 路径防护**：`mcp-server.py` 的 `_safe_path()` 做了工作区越界校验。

---

## 三、风险项 ⚠️（应修，非阻塞）

| # | 风险 | 位置 | 影响 |
|---|------|------|------|
| R1 | `decrypt_value` 解密失败时**返回原文**而非报错 | `security/crypto.py:85` | 迁移兼容设计，但会掩盖密钥损坏，且让"是否加密"判断脆弱 |
| R2 | 自动生成 crypto key 落 `data/.crypto_key` | `security/crypto.py:51` | 换机/重建容器后旧密文无法解密；生产必须显式配 `AI_TEAM_HUB_CRYPTO_KEY` |
| R3 | `CORS_ORIGINS` 环境变量文档里有，代码里**根本没读** | `main.py:155` | 配置项失效，运维误以为可控 |
| R4 | 入口 `uvicorn.run(reload=True)` | `main.py:236` | 生产不应开 reload；且 Docker 用的是另一条 CMD，两条启动路径不一致 |
| R5 | RAG 用 `PyPDF2`，requirements 装的是 `pypdf` | `rag_pipeline.py:37` vs `requirements.txt:20` | 运行时 `ImportError`，PDF 上传直接失败 |
| R6 | 存在死代码/归档模块残留 | `_archived/old_services/*`、`collaboration/event_bus.py` 等 | 增加交付体积与理解成本 |
| R7 | 观测数据在内存、单实例 | `docs` 已注明 | 水平扩展会丢数据，需集中式日志 |
| R8 | 上传无大小上限 | `files.py:128`、`messages.py:285` | `await file.read()` 全量入内存，大文件可打爆内存（DoS） |
| R9 | 根目录 `requirements.txt` 与 `backend/requirements.txt` 内容不同 | 两份文件 | Dockerfile 用根目录那份（缺 cryptography/docx/pptx/pdf 等），**镜像会缺依赖** |

---

## 四、必须修复项 🔴（交付前阻塞）

### P0-1 · 真实 API Key 已提交进 Git 仓库 ⛔
- `.or_key_b64` 被 git 跟踪，base64 解码后为真实 OpenRouter Key：`sk-or-v1-136f9b20...`
- `data/aiteamhub.db`（含加密密钥体系下的业务数据）也被跟踪
- **动作**：① 立即在 OpenRouter 后台**吊销并轮换该 Key**；② `git rm --cached .or_key_b64 .cf_token data/aiteamhub.db`；③ 用 `git filter-repo`/BFG 清历史；④ 修正 `.gitignore`（现有 `.or_key` 不匹配实际 `.or_key_b64`）。

### P0-2 · 仓库处于未完成合并状态（34 个未合并文件）⛔
- `git status` 显示 `UU backend/main.py`、`UU backend/routes/apikeys.py`、`DU .gitignore`、`DU _archived/...` 等 34 项 `UU/DU` 冲突（无 MERGE_HEAD，疑似中断的 merge/rebase 残留）。
- 工作树文件本身可读、无冲突标记，但 git index 脏乱，**任何人 clone/CI 构建都会出错**。
- **动作**：清理 index 状态（`git add`/`git rm` 逐项定稿 → commit），确保 `git status` 干净。

### P0-3 · `/api/*` 全线无鉴权 ⛔
- Auth 中间件只保护 `/v1/*`（`middleware/auth.py:52`），而 `/api/apikeys`（增/删/查/轮换 Key）、`/api/channels`、`/api/teammates`、`/api/messages` **完全开放**。
- 部署文档甚至明示"legacy API — no auth needed"来创建 Key。任何能访问端口的人都能读写 Key 与全部业务数据。
- **动作**：给 `/api/*` 管理类路由加同一套鉴权（或至少 apikeys 管理接口），生产环境不暴露 legacy 无鉴权面。

### P0-4 · CORS 配置非法 + 通配 ⛔
- `allow_origins=[..., "*"]` 同时 `allow_credentials=True`（`main.py:155-156`）——浏览器规范下该组合无效/被拒，且 `*` 允许任意站点跨域。
- **动作**：改为读取 `CORS_ORIGINS` 环境变量的白名单，去掉 `*`，与 `allow_credentials` 二选一。

### P0-5 · Dockerfile 无法正确构建镜像 ⛔
- `COPY backend/ ./backend/ .`（`Dockerfile:11`）语法错误（多目标 COPY 末尾必须是目录且写法混乱）。
- 构建上下文 `context: ..` 且**无 `.dockerignore`**，会把 `.or_key_b64`、`.cf_token`、`data/.crypto_key`、整个 `data/`、`backend/venv`、`node_modules`、`.git` 全打进镜像——**机密进镜像 + 体积爆炸**。
- Dockerfile 装的是**根目录** `requirements.txt`（缺 cryptography 等），镜像启动即 `ImportError`。
- **动作**：修正 COPY；新增 `.dockerignore`；改用 `backend/requirements.txt`；确认前端 `dist` 是否需要一起 COPY（`main.py:230` 会挂载它）。

---

## 五、商业交付前建议（按优先级）

**第一批（阻塞，必须做）**
1. 轮换泄露的 OpenRouter Key，从 git 历史彻底清除 `.or_key_b64`/`.cf_token`/`*.db`。
2. 定稿并清理未完成的 merge（34 个冲突文件），使 `git status` 干净。
3. 给 `/api/*` 管理接口加鉴权；修正 CORS 白名单。
4. 修 Dockerfile + 加 `.dockerignore` + 统一到 `backend/requirements.txt`，本地 `docker build` 跑通。

**第二批（交付质量，强烈建议）**
5. 修 `PyPDF2`→`pypdf` 依赖不一致；上传加大小上限（如 25MB）与流式落盘。
6. 关生产 `reload`；提供 `gunicorn`/`uvicorn --workers` 生产启动方式并写进文档。
7. 生产强制 `AI_TEAM_HUB_CRYPTO_KEY` 显式配置（缺失时警告或拒启），避免自动生成 key 带来的解密漂移。
8. 让 `CORS_ORIGINS` 真正生效。

**第三批（交付体验与可维护性）**
9. 重写 README：区分 Windows(start.bat) / Linux+Mac / Docker 三条路径，与 `deploy/` 实际保持一致（当前 README 只讲 Windows，且 DEPLOYMENT_GUIDE 里的 `cp .env.example` 路径与 compose 挂载不符）。
10. 删除 `_archived/old_services/` 与确认无引用的 collaboration 死模块，缩小交付面。
11. 提供 `.env.example` → `.env` 的一键校验脚本（跨平台），首启即校验必需环境变量。
12. 观测/日志接入集中式方案（多实例部署前置条件）。

---

## 六、检查项对照表（任务清单逐项）

| 检查项 | 状态 | 结论摘要 |
|--------|------|----------|
| 环境变量管理 | 🟡 | 有 `.env.example`，但 `CORS_ORIGINS` 未被读取、两份 requirements 割裂 |
| secrets 管理 | 🔴 | 真实 Key 进 git（P0-1） |
| API Key 存储安全 | 🟢 | Fernet 加密 + 内存解密 + 日志脱敏，设计良好 |
| JWT/session 机制 | 🟡 | 无 JWT，用 X-API-Key 头 + DB 校验；仅覆盖 `/v1`，`/api` 裸奔（P0-3） |
| 文件上传安全 | 🟡 | 文件名安全 + 类型白名单 + 用户隔离，但无大小限制（R8） |
| 权限边界 | 🔴 | `/api/*` 无鉴权（P0-3） |
| 日志系统 | 🟢 | 有脱敏过滤器；缺结构化/集中化（R7） |
| 错误处理 | 🟢 | HTTPException 规范，RAG pipeline 有 error 包装 |
| 数据库迁移流程 | 🟡 | `create_all` 自动建表 + 明文 Key 迁移；无 Alembic 版本化迁移 |
| API 文档完整性 | 🟢 | FastAPI 自带 `/docs` + `PUBLIC_API_SPEC.md` + SDK_GUIDE |
| Dockerfile | 🔴 | 语法错误 + 错误 requirements（P0-5） |
| docker-compose | 🟡 | 基本可用，但依赖损坏的 Dockerfile；无 .dockerignore |
| 启动脚本 | 🟡 | `start.sh`(Docker) / `start.bat`(Win venv) 两套，逻辑 OK 但路径与 README 不完全一致 |
| 跨平台部署说明 | 🟠 | README 仅 Windows；Linux/Mac 只在 DEPLOYMENT_GUIDE 零散提及 |
| 一键启动 | 🟡 | `start.sh` / `start.bat` 存在，但受 Dockerfile/依赖问题影响未必开箱即用 |
| requirements 依赖管理 | 🟠 | 版本锁定好，但根/backend 两份不一致 + PyPDF2/pypdf 冲突 |
| 配置文件规范 | 🟡 | `.env.example` 规范；`.gitignore` 规则与实际文件名不匹配 |
| README 新用户友好度 | 🟠 | 单平台、与实际部署路径矛盾 |
| 开发/生产环境差异 | 🟠 | `reload=True` 混入入口；两条启动路径；观测仅单实例 |
| 命令执行风险 | 🟡 | `mcp-server.py` 用 `shell=True` 但有 `_safe_path` + guardrail；仅供本地开发，勿对外暴露 SSE 模式 |
| 权限绕过风险 | 🔴 | legacy `/api/*` 即绕过面（P0-3） |

---

*报告完 · 所有 P0/P1 修复均需"先分析再执行"，本报告仅诊断，未改动任何核心业务代码。*
