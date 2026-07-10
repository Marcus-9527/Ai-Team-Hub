/**
 * AI Team Hub — Cloudflare Workers (Team Chat Engine)
 *
 * Internal team execution engine:
 * - Multi-teammate collaboration with role-based perspectives
 * - Quality gates between interaction steps
 * - Smart retry and backup handling
 * - Creative variance injection for diverse responses
 */

// ── Types ──
type D1Database = any
type Env = { DB: D1Database; WORKER_ENV: string }

// ═══════════════════════════════════════════
// ① Information Flow Validation Layer (Quality Gate)
// ═══════════════════════════════════════════

interface QualityGate {
  inputUsed: boolean           // teammate 是否真正使用了上游输入
  decisionInfluenced: boolean  // 决策是否受上一步影响
  diffFromPrevious: number     // 与上一步的差异度 (0-1)，低于 0.37 视为低质量响应
  validationPassed: boolean    // 综合验证是否通过
  failureReason: string        // 失败原因
}

// ── v2.3: 验证信息流转 —— 防止低质量响应 ──
function validateInformationFlow(
  currentOutput: string,
  previousOutput: string,
  teammateRole: string,
  currentReasoning: string,  // v2.3: 加入 reasoning 字段验证
): QualityGate {
  // 1. 检查 input 是否被使用
  // 对于 engineer：检查 reasoning 中是否引用了 strategy_plan 的子任务名称
  // 对于 quality：检查 reasoning 中是否引用了代码中的函数/类名
  // 对于 research：检查 reasoning 中是否引用了原始任务的关键词
  let inputUsed = false
  if (teammateRole === 'engineer' && currentReasoning) {
    // engineer 的 reasoning 应该引用 strategy_plan 的子任务名称
    const planItems = extractPlanItemNames(previousOutput)
    inputUsed = planItems.some(name => currentReasoning.includes(name))
  } else if (teammateRole === 'quality' && currentReasoning) {
    // quality 的 reasoning 应该引用代码中的函数/类名
    const codeSymbols = extractCodeSymbols(previousOutput)
    inputUsed = codeSymbols.some(sym => currentReasoning.includes(sym))
  } else if (teammateRole === 'research' && currentReasoning) {
    // research 的 reasoning 应该引用原始任务关键词
    const taskKeywords = extractKeywords(previousOutput)
    inputUsed = taskKeywords.some(kw => currentReasoning.includes(kw))
  } else {
    // 默认：关键词匹配
    const prevKeywords = extractKeywords(previousOutput)
    inputUsed = prevKeywords.some(kw => currentOutput.includes(kw))
  }

  // 2. 检查决策是否受上一步影响
  const diff = computeDiff(previousOutput, currentOutput)
  const decisionInfluenced = diff > 0.1

  // 3. 综合验证（阈值根据角色调整）
  const threshold = teammateRole === 'engineer' ? 0.15 : 0.37
  const validationPassed = inputUsed && decisionInfluenced && diff > threshold
  let failureReason = ''
  if (!inputUsed) failureReason = `context_not_applied: ${teammateRole} 未在 reasoning 中引用上游输出`
  else if (!decisionInfluenced) failureReason = 'context_not_linked: 决策未受上一步影响'
  else if (diff <= threshold) failureReason = `variance_too_low: ${diff.toFixed(2)} < ${threshold}，疑似低质量响应`

  return { inputUsed, decisionInfluenced, diffFromPrevious: diff, validationPassed, failureReason }
}

// ── 从 plan JSON 中提取子任务名称 ──
function extractPlanItemNames(planOutput: string): string[] {
  try {
    // 尝试解析 JSON
    const jsonMatch = planOutput.match(/\[.*\]/s)
    if (jsonMatch) {
      const items = JSON.parse(jsonMatch[0])
      return items.map((item: any) => item.name || item.description || '').filter(Boolean)
    }
  } catch {}
  // backup：提取引号中的内容
  const matches = planOutput.match(/"name"\s*:\s*"([^"]+)"/g)
  return matches ? matches.map(m => m.replace(/"name"\s*:\s*"([^"]+)"/, '$1')) : []
}

// ── 从代码中提取函数/类名 ──
function extractCodeSymbols(codeOutput: string): string[] {
  const symbols: string[] = []
  // 匹配 class 定义
  const classMatches = codeOutput.matchAll(/class\s+(\w+)/g)
  for (const m of classMatches) symbols.push(m[1])
  // 匹配 def 定义
  const defMatches = codeOutput.matchAll(/def\s+(\w+)/g)
  for (const m of defMatches) symbols.push(m[1])
  // 匹配 import
  const importMatches = codeOutput.matchAll(/import\s+(\w+)/g)
  for (const m of importMatches) symbols.push(m[1])
  return [...new Set(symbols)].slice(0, 15)

function extractKeywords(text: string): string[] {
  // 提取有意义的关键词（去除停用词）
  const stopWords = ['的', '是', '在', '了', '和', '与', '或', 'the', 'a', 'an', 'is', 'are', 'was', 'were', 'to', 'of', 'in', 'for', 'on', 'with', 'at', 'by', 'from', 'as', 'into', 'through', 'during', 'before', 'after', 'above', 'below', 'between', 'out', 'off', 'over', 'under', 'again', 'further', 'then', 'once']
  const words = text.toLowerCase().split(/\s+/).filter(w => w.length > 2 && !stopWords.includes(w))
  return [...new Set(words)].slice(0, 20)  // 去重，取前20个
}

function computeDiff(a: string, b: string): number {
  // 简单的 Jaccard 距离作为差异度
  const setA = new Set(a.toLowerCase().split(/\s+/))
  const setB = new Set(b.toLowerCase().split(/\s+/))
  const intersection = new Set([...setA].filter(x => setB.has(x)))
  const union = new Set([...setA, ...setB])
  if (union.size === 0) return 0
  return 1 - (intersection.size / union.size)  // Jaccard 距离 = 1 - Jaccard 相似度
}

// ═══════════════════════════════════════════
// ② Recovery System — 智能错误恢复
// ═══════════════════════════════════════════

type RecoveryAction = 'retry' | 'backup' | 'backup_output' | 'stop'

interface RecoveryDecision {
  action: RecoveryAction
  reason: string
  retryDelay?: number
  backupTeammate?: string
  backupMode?: string
}

// ── v2.3: 智能恢复决策 —— 不再简单 stop ──
function decideRecovery(
  errorCategory: ErrorCategory,
  attempt: number,
  maxRetries: number,
  teammateId: string,
  previousResults: Record<string, string>,
): RecoveryDecision {
  // auth/format 错误：不可重试，尝试 backup 或 backup_output
  if (errorCategory === 'auth' || errorCategory === 'format') {
    // 如果有 backup teammate，切换
    const backupMap: Record<string, string> = {
      'strategy': 'engineer',     // strategy 失败，engineer 尝试直接执行
      'engineer': 'strategy',     // engineer 失败，strategy 尝试给出伪代码
      'quality': 'engineer',    // quality 失败，engineer 自审
      'research': 'strategy',   // research 失败，strategy 基于已有知识规划
    }
    const backup = backupMap[teammateId]
    if (backup && !previousResults[backup]) {
      return { action: 'backup', reason: `${teammateId} failed with ${errorCategory}, backup to ${backup}`, backupTeammate: backup }
    }
    // 无 backup，降级模式
    return { action: 'backup_output', reason: `${teammateId} failed, no backup available, entering backup mode`, backupMode: 'partial_output' }
  }

  // rate_limit/timeout 错误：可重试
  if (errorCategory === 'rate_limit' || errorCategory === 'timeout') {
    if (attempt < maxRetries - 1) {
      const delay = errorCategory === 'rate_limit' ? 5000 * Math.pow(2, attempt) : 2000 * Math.pow(2, attempt)
      return { action: 'retry', reason: `${errorCategory}, retrying in ${delay}ms`, retryDelay: delay }
    }
    // 重试耗尽，降级
    return { action: 'backup_output', reason: `${errorCategory} retries exhausted, entering backup mode`, backupMode: 'best_effort' }
  }

  // 网络错误：重试一次，然后 backup
  if (errorCategory === 'network') {
    if (attempt < 1) {
      return { action: 'retry', reason: 'network error, retrying', retryDelay: 3000 }
    }
    return { action: 'backup_output', reason: 'network error retries exhausted', backupMode: 'cached_response' }
  }

  // 未知错误：重试一次，然后 stop
  if (attempt < 1) {
    return { action: 'retry', reason: 'unknown error, retrying', retryDelay: 2000 }
  }
  return { action: 'stop', reason: 'unknown error retries exhausted' }
}

// ═══════════════════════════════════════════
// ③ Cognitive Diversity Amplifier
// ═══════════════════════════════════════════

// ── v2.3: 认知多样性注入 —— 防止 teammate 思维太像 ──

interface PerspectiveMode {
  reasoningConstraint: string   // 推理约束：强制使用特定推理方式
  viewpointBias: string    // 视点偏差：强制从特定角度看问题
  creativeVariance: string      // 创造性差异：随机扰动，防止输出过于确定性
}

function generatePerspectiveMode(teammateId: string, taskDescription: string): PerspectiveMode {
  // 每个 teammate 的约束不同，确保思维多样性
  const constraints: Record<string, () => PerspectiveMode> = {
    strategy: () => ({
      reasoningConstraint: `推理约束：你必须使用"逆向工程法"——从最终目标倒推，而不是从现状正向规划。先问"最终交付物是什么"，再问"需要什么前置条件"。`,
      viewpointBias: `视点偏差：你是一个"完美主义者"PM，对每个子任务都要问"如果这个环节失败了怎么办"。不允许输出"看起来合理"的方案，必须输出"经过压力测试"的方案。`,
      creativeVariance: `创造性差异：在拆解任务时，必须包含一个"反直觉子任务"——一个看起来与目标无关但实际上关键的步骤。当前任务哈希: ${hashString(taskDescription).slice(0, 8)}`,
    }),
    engineer: () => ({
      reasoningConstraint: `推理约束：你必须使用"测试驱动法"——先写测试用例，再写实现代码。不允许"先写代码再补测试"。`,
      viewpointBias: `视点偏差：你是一个"安全偏执狂"工程师，对每一行代码都要问"这里会被怎么攻击"。不允许输出"能用就行"的代码，必须输出"经过安全审查"的代码。`,
      creativeVariance: `创造性差异：在实现时，必须使用一种"非主流"的实现方式——如果任务通常用 for 循环，你必须用递归或函数式。当前任务哈希: ${hashString(taskDescription).slice(0, 8)}`,
    }),
    quality: () => ({
      reasoningConstraint: `推理约束：你必须使用"红队思维"——假设代码中有 3 个隐藏 bug，你的任务是找到它们。不允许"看起来没问题"的评审。`,
      viewpointBias: `视点偏差：你是一个"用户体验极端主义者"，从最差用户的角度评审代码。不允许输出"功能正确"的评审，必须输出"用户不会误用"的评审。`,
      creativeVariance: `创造性差异：在评审时，必须提出一个"违反直觉的改进建议"——一个看起来会让代码变差但实际上会变好的建议。当前任务哈希: ${hashString(taskDescription).slice(0, 8)}`,
    }),
    research: () => ({
      reasoningConstraint: `推理约束：你必须使用"第一性原理"——不接受"业界标准"作为理由，必须从基本原理出发论证。`,
      viewpointBias: `视点偏差：你是一个"技术怀疑论者"，对每个方案都要问"如果这个技术明天就过时了怎么办"。不允许输出"主流方案最好"的调研。`,
      creativeVariance: `创造性差异：在调研中，必须包含一个"冷门方案"——不主流但在特定场景下更优的方案。当前任务哈希: ${hashString(taskDescription).slice(0, 8)}`,
    }),
  }

  const generator = constraints[teammateId] || (() => ({
    reasoningConstraint: '推理约束：使用批判性思维，不接受表面答案。',
    viewpointBias: '视点偏差：从反对者的角度审视你的输出。',
    creativeVariance: `创造性差异：在输出中，必须包含一个"反直觉观点"。当前任务哈希: ${hashString(taskDescription).slice(0, 8)}`,
  }))

  return generator()
}

function hashString(str: string): string {
  let hash = 0
  for (let i = 0; i < str.length; i++) {
    const char = str.charCodeAt(i)
    hash = ((hash << 5) - hash) + char
    hash = hash & hash
  }
  return Math.abs(hash).toString(16)
}

// ═══════════════════════════════════════════
// ① Teammate Runtime
// ═══════════════════════════════════════════

// ── v2.3: Role Cognitive Lock + Cognitive Diversity ──
// 每个 teammate 严格的单一职责 + 视角模式 + 视点偏差 + 创造性差异
// 不允许跨角色、不允许泛分析、不允许"解释型输出"、不允许思维太像

interface TeammateProfile {
  role: string
  systemPrompt: string
  tools: string[]
  allowedOutput: string
}

const TEAMMATES: Record<string, TeammateProfile> = {
  strategy: {
    role: 'strategy',
    systemPrompt: `[ROLE LOCK — STRATEGY ONLY]
你是任务拆解专家。唯一职责：将复杂任务分解为可执行子任务。

严格规则：
- 只输出任务拆解方案（JSON），不写代码、不做分析、不做决策
- 不输出"解释性文字"或"建议"
- 如果输入不是拆解请求 → {"status":"error","result":"","reasoning":"非拆解请求","next_action":"reject"}

[PERSPECTIVE MODE — 逆向工程法]
你必须从最终目标倒推，不允许正向规划。先问"最终交付物是什么"，再问"需要什么前置条件"。

[VIEWPOINT BIAS — 完美主义者PM]
对每个子任务都要问"如果这个环节失败了怎么办"。不允许输出"看起来合理"的方案。

[CREATIVE VARIANCE]
拆解时必须包含一个"反直觉子任务"——看起来与目标无关但实际上关键的步骤。

输出格式（严格遵守）：
{"status":"success","result":"[子任务列表：name/description/assigned_to/dependencies]","reasoning":"[为什么这样拆解]","next_action":"[下一步]"}`,
    tools: ['decompose'],
    allowedOutput: 'task_decomposition_json',
  },

  engineer: {
    role: 'engineer',
    systemPrompt: `[ROLE LOCK — ENGINEER ONLY]
你是代码执行专家。唯一职责：根据 Strategy 的拆解方案编写可运行代码。

严格规则：
- 只输出代码（JSON，result字段=完整代码），不做分析、不写调研、不做决策
- 不输出"解释性文字"或"建议" — result字段只能是代码
- 如果输入不是代码请求 → {"status":"error","result":"","reasoning":"非代码请求","next_action":"reject"}

[CRITICAL — 必须引用上游输出]
你的代码 MUST 包含 Strategy 拆解方案中的所有子任务。不允许忽略任何子任务。
在你的 reasoning 字段中，必须列出你引用了 Strategy 的哪些子任务。

[PERSPECTIVE MODE — 测试驱动法]
必须先写测试用例，再写实现代码。不允许"先写代码再补测试"。

[VIEWPOINT BIAS — 安全偏执狂]
对每行代码都要问"这里会被怎么攻击"。不允许输出"能用就行"的代码。

[CREATIVE VARIANCE]
实现时必须使用一种"非主流"方式——如果通常用 for 循环，你必须用递归或函数式。

输出格式（严格遵守）：
{"status":"success","result":"[完整可运行代码，带注释]","reasoning":"[引用了哪些子任务，实现思路不超过50字]","next_action":"[代码已完成，等待审查]"}`,
    tools: ['code_exec', 'test'],
    allowedOutput: 'executable_code_json',
  },

  quality: {
    role: 'quality',
    systemPrompt: `[ROLE LOCK — QUALITY ONLY]
你是代码评审专家。唯一职责：评审代码质量、安全性、完整性。

严格规则：
- 只输出评审结果（JSON），不写代码、不改代码、不做分析
- 不输出"建议性代码" — 只能指出问题
- 如果输入不是评审请求 → {"status":"error","result":"","reasoning":"非评审请求","next_action":"reject"}

[CRITICAL — 必须验证代码是否覆盖了所有子任务]
你的评审 MUST 检查代码是否实现了 Strategy 拆解方案中的所有子任务。
在你的 reasoning 字段中，必须列出你检查了哪些子任务，哪些被覆盖，哪些缺失。

[PERSPECTIVE MODE — 红队思维]
假设代码中有 3 个隐藏 bug，你的任务是找到它们。不允许"看起来没问题"的评审。

[VIEWPOINT BIAS — 用户体验极端主义者]
从最差用户的角度评审。不允许输出"功能正确"，必须输出"用户不会误用"。

[CREATIVE VARIANCE]
评审时必须提出一个"违反直觉的改进建议"——看起来会让代码变差但实际上会变好的建议。

输出格式（严格遵守）：
{"status":"success","result":"[pass/fail, 问题列表，子任务覆盖情况]","reasoning":"[评审依据，检查了哪些子任务]","next_action":"[通过则标记完成，不通过则返回修改]"}`,
    tools: ['code_review', 'evaluate'],
    allowedOutput: 'quality_check_json',
  },

  research: {
    role: 'research',
    systemPrompt: `[ROLE LOCK — RESEARCH ONLY]
你是技术调研专家。唯一职责：调研现有方案、技术选型、最佳实践。

严格规则：
- 只输出调研报告（JSON），不写代码、不做决策、不评审
- 不输出"代码示例" — 只能描述方案
- 如果输入不是调研请求 → {"status":"error","result":"","reasoning":"非调研请求","next_action":"reject"}

[CRITICAL — 必须针对原始任务调研]
你的调研 MUST 直接针对原始任务的需求，不允许泛泛而谈。
在你的 reasoning 字段中，必须说明你的调研如何直接服务于原始任务。

[PERSPECTIVE MODE — 第一性原理]
不接受"业界标准"作为理由，必须从基本原理出发论证。

[VIEWPOINT BIAS — 技术怀疑论者]
对每个方案都要问"如果这个技术明天就过时了怎么办"。不允许输出"主流方案最好"。

[CREATIVE VARIANCE]
调研中必须包含一个"冷门方案"——不主流但在特定场景下更优的方案。

输出格式（严格遵守）：
{"status":"success","result":"[现有方案对比、优缺点、推荐方案]","reasoning":"[调研方法论，如何服务于原始任务]","next_action":"[调研完成，等待执行]"}`,
    tools: ['web_search', 'analyze'],
    allowedOutput: 'research_report_json',
  },
}

// ── v2.1: Strict Output Schema ──
const OUTPUT_SCHEMA = `{
  "status": "success" | "error" | "timeout",
  "result": "string (your main output — REQUIRED, non-empty)",
  "reasoning": "string (your thinking process)",
  "next_action": "string (suggested next step)"
}`

// ── v2.1: Error Classification ──
type ErrorCategory = 'network' | 'auth' | 'rate_limit' | 'timeout' | 'format' | 'unknown'

interface ClassifiedError {
  category: ErrorCategory
  httpCode: number
  message: string
  retryable: boolean
  retryDelay: number  // ms
}

function classifyError(httpCode: number, message: string): ClassifiedError {
  const msg = message.toLowerCase()
  if (httpCode === 429 || msg.includes('rate limit') || msg.includes('too many requests')) {
    return { category: 'rate_limit', httpCode, message, retryable: true, retryDelay: 5000 }
  }
  if (httpCode === 401 || httpCode === 403 || msg.includes('auth') || msg.includes('unauthorized') || msg.includes('forbidden') || msg.includes('insufficient credits')) {
    return { category: 'auth', httpCode, message, retryable: false, retryDelay: 0 }
  }
  if (httpCode === 408 || httpCode === 504 || msg.includes('timeout') || msg.includes('timed out')) {
    return { category: 'timeout', httpCode, message, retryable: true, retryDelay: 3000 }
  }
  if (httpCode >= 500 || msg.includes('internal') || msg.includes('server error') || msg.includes('bad gateway') || msg.includes('service unavailable')) {
    return { category: 'network', httpCode, message, retryable: true, retryDelay: 2000 }
  }
  if (httpCode === 400 && (msg.includes('no input') || msg.includes('invalid_prompt') || msg.includes('format'))) {
    return { category: 'format', httpCode, message, retryable: false, retryDelay: 0 }
  }
  if (httpCode >= 400) {
    return { category: 'network', httpCode, message, retryable: httpCode >= 500, retryDelay: 2000 }
  }
  return { category: 'unknown', httpCode, message, retryable: true, retryDelay: 2000 }
}

interface TeammateResult {
  teammateId: string
  status: string
  result: string
  reasoning: string
  nextAction: string
  tokensUsed: number
  latencyMs: number
  error: string
  errorCategory?: ErrorCategory
  retryCount?: number
}

// ── v2.2: Context Split — 每个 teammate 输入完全独立的 JSON ──
// 不再共享 contextBlock/historyBlock，每个 teammate 有自己的输入

interface TeammateInput {
  task: string           // 该 teammate 的具体任务
  roleContext: string    // 角色专属上下文（不是共享的）
  expectedOutput: string // 期望的输出类型
}

async function callTeammate(
  teammateId: string,
  input: TeammateInput,     // v2.2: 独立 JSON 输入，不再共享 context
  apiKey: string,
  provider: string,
  model: string,
  baseUrl: string | null,
): Promise<TeammateResult> {
  const start = Date.now()
  const def = TEAMMATES[teammateId]
  if (!def) {
    return { teammateId, status: 'error', result: '', reasoning: '', nextAction: '', tokensUsed: 0, latencyMs: 0, error: `Unknown teammate: ${teammateId}` }
  }

  // ── v2.2: 每个 teammate 的 prompt 完全独立，不共享任何 context ──
  const prompt = [
    def.systemPrompt,
    '',
    '[YOUR TASK — 这是你的唯一任务]',
    input.task,
    '',
    '[EXPECTED OUTPUT TYPE]',
    input.expectedOutput,
    '',
    '[ROLE CONTEXT — 仅你的角色可见]',
    input.roleContext,
    '',
    '[OUTPUT FORMAT — 严格遵守，无例外]',
    '输出纯 JSON，不要 markdown，不要解释性文字：',
    '{"status":"success","result":"[你的输出]","reasoning":"[简短推理]","next_action":"[下一步]"}',
    '',
    'KILL SWITCH 规则：',
    '1. 如果你无法完成你的任务，输出 {"status":"error","result":"","reasoning":"[原因]","next_action":"stop"}',
    '2. 不要输出"解释型文字"来替代实际输出',
    '3. 不要尝试做其他角色的工作',
  ].join('\n')

  const endpoint = getEndpoint(provider, baseUrl)
  const isAnthropic = provider === 'anthropic'
  const isResponsesApi = (baseUrl || '').includes('/responses')
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  let payload: any

  if (isAnthropic) {
    headers['x-api-key'] = apiKey
    headers['anthropic-version'] = '2023-06-01'
    payload = { model, system: def.systemPrompt, messages: [{ role: 'user', content: prompt }], max_tokens: 4096, stream: false }
  } else if (isResponsesApi) {
    headers['Authorization'] = `Bearer ${apiKey}`
    payload = { model, input: prompt, stream: false, temperature: 0.7, max_tokens: 4096 }
  } else {
    headers['Authorization'] = `Bearer ${apiKey}`
    payload = {
      model,
      messages: [
        { role: 'system', content: def.systemPrompt },
        { role: 'user', content: prompt },
      ],
      stream: false,
      temperature: 0.7,
      max_tokens: 4096,
    }
  }

  // ── v2.1: Smart retry with error classification ──
  const maxRetries = 3
  let lastError: ClassifiedError | null = null

  for (let attempt = 0; attempt < maxRetries; attempt++) {
    try {



      const res = await fetch(endpoint, { method: 'POST', headers, body: JSON.stringify(payload) })
      if (!res.ok) {
        const text = await res.text()
        const classified = classifyError(res.status, text)
        lastError = classified
        console.log(`[${teammateId}] attempt ${attempt+1}/${maxRetries} — ${classified.category}(${classified.httpCode}): ${text.slice(0, 100)}`)

        if (!classified.retryable || attempt >= maxRetries - 1) {
          return { teammateId, status: 'error', result: '', reasoning: '', nextAction: '', tokensUsed: 0, latencyMs: Date.now() - start, error: `${classified.category}(${classified.httpCode}): ${text.slice(0, 200)}`, errorCategory: classified.category, retryCount: attempt }
        }
        // Exponential backoff with category-aware delay
        const delay = classified.retryDelay * Math.pow(2, attempt)
        await sleep(delay)
        continue
      }

      const r = await res.json()
      let full = ''
      if (r.choices?.[0]?.message?.content) {
        full = r.choices[0].message.content
      } else if (r.output?.[0]?.content?.[0]?.text) {
        full = r.output[0].content[0].text
      }

      // ── v2.1: Strict JSON parsing with multi-strategy backup ──
      const parsed = parseTeammateJsonStrict(full)
      return {
        teammateId,
        status: parsed.status,
        result: parsed.result,
        reasoning: parsed.reasoning,
        nextAction: parsed.nextAction,
        tokensUsed: (prompt.length + full.length) / 4,
        latencyMs: Date.now() - start,
        error: parsed.status === 'error' ? 'Teammate reported error' : '',
        retryCount: attempt,
      }
    } catch (e: any) {
      const classified = classifyError(0, e.message)
      lastError = classified
      console.log(`[${teammateId}] attempt ${attempt+1}/${maxRetries} — ${classified.category}: ${e.message}`)
      if (!classified.retryable || attempt >= maxRetries - 1) {
        return { teammateId, status: 'error', result: '', reasoning: '', nextAction: '', tokensUsed: 0, latencyMs: Date.now() - start, error: `${classified.category}: ${e.message}`, errorCategory: classified.category, retryCount: attempt }
      }
      await sleep(classified.retryDelay * Math.pow(2, attempt))
    }
  }

  return { teammateId, status: 'error', result: '', reasoning: '', nextAction: '', tokensUsed: 0, latencyMs: Date.now() - start, error: lastError ? `${lastError.category}: ${lastError.message}` : 'Max retries exceeded', errorCategory: lastError?.category, retryCount: maxRetries }
}

// ── v2.1: Strict JSON parser — 5 strategies ──
function parseTeammateJsonStrict(text: string): { status: string; result: string; reasoning: string; nextAction: string } {
  if (!text || !text.trim()) {
    return { status: 'error', result: '', reasoning: 'Empty response from LLM', nextAction: 'retry' }
  }

  // Strategy 1: Direct parse
  try {
    const obj = JSON.parse(text)
    if (obj.status && obj.result) return normalizeResult(obj)
  } catch {}

  // Strategy 2: Strip markdown fences
  let cleaned = text.trim()
  if (cleaned.startsWith('```')) {
    cleaned = cleaned.split('\n').filter(l => !l.trim().startsWith('```')).join('\n').trim()
  }
  try {
    const obj = JSON.parse(cleaned)
    if (obj.status && obj.result) return normalizeResult(obj)
  } catch {}

  // Strategy 3: Extract first JSON object
  const start = cleaned.indexOf('{')
  const end = cleaned.lastIndexOf('}')
  if (start >= 0 && end > start) {
    try {
      const obj = JSON.parse(cleaned.slice(start, end + 1))
      if (obj.status) return normalizeResult(obj)
    } catch {}
  }

  // Strategy 4: Try to find JSON with regex for nested braces
  const jsonMatch = cleaned.match(/\{[^{}]*"status"[^{}]*\}/)
  if (jsonMatch) {
    try {
      const obj = JSON.parse(jsonMatch[0])
      return normalizeResult(obj)
    } catch {}
  }

  // Strategy 5: Fallback — treat entire text as result
  console.log('[parseTeammateJson] All JSON parse strategies failed, using raw text as backup')
  return { status: 'success', result: text, reasoning: '', nextAction: 'continue' }
}

function normalizeResult(obj: any): { status: string; result: string; reasoning: string; nextAction: string } {
  return {
    status: obj.status || 'success',
    result: obj.result || obj.output || obj.text || obj.content || '',
    reasoning: obj.reasoning || obj.thought || obj.explanation || '',
    nextAction: obj.next_action || obj.nextAction || obj.next || 'continue',
  }
}

// ═══════════════════════════════════════════
// ② Execution Flow Engine v2.3 — Quality Gate + Recovery System
// ═══════════════════════════════════════════

interface TaskNode {
  id: string
  teammateId: string
  taskDescription: string
  dependencies: string[]
  retryCount: number
  timeout: number
}

interface TaskResult {
  nodeId: string
  teammateId: string
  status: string
  result: string
  error: string
  errorCategory?: ErrorCategory
  latencyMs: number
  retries: number
  qualityGate?: QualityGate  // v2.3: 质量门验证结果
  recoveryAction?: RecoveryAction  // v2.3: 恢复动作
}

interface FlowContext {
  apiKey: string
  provider: string
  model: string
  baseUrl: string | null
  originalTask: string
  previousResults: Record<string, string>
}

class ExecutionFlowEngine {
  nodes: Map<string, TaskNode> = new Map()
  edges: [string, string][] = []
  results: Map<string, TaskResult> = new Map()
  private _killed = false
  private _backupMode = false  // v2.3: 降级模式

  addNode(node: TaskNode) { this.nodes.set(node.id, node) }
  addEdge(from: string, to: string) { this.edges.push([from, to]) }

  // ── v2.3: 构建每个 teammate 的独立输入（含视角模式）──
  private _buildTeammateInput(node: TaskNode, ctx: FlowContext, previousOutput: string): TeammateInput {
    const def = TEAMMATES[node.teammateId]
    let roleContext = ''
    let expectedOutput = ''

    switch (node.teammateId) {
      case 'strategy':
        roleContext = `原始任务：${ctx.originalTask}`
        expectedOutput = '任务拆解方案（JSON）'
        break
      case 'engineer':
        roleContext = `上游 Strategy 的拆解方案：${previousOutput}`
        expectedOutput = '可运行代码（JSON）'
        break
      case 'research':
        roleContext = `原始任务：${ctx.originalTask}`
        expectedOutput = '调研报告（JSON）'
        break
      case 'quality':
        roleContext = `待评审的代码：${previousOutput.slice(0, 2000)}`
        expectedOutput = '评审结果（JSON）'
        break
      default:
        roleContext = `任务：${node.taskDescription}`
        expectedOutput = 'JSON 格式输出'
    }

    return {
      task: node.taskDescription,
      roleContext,
      expectedOutput,
    }
  }

  async execute(ctx: FlowContext): Promise<Map<string, TaskResult>> {
    this.results = new Map()
    this._killed = false
    this._backupMode = false
    const { adj, inDeg } = this._buildGraph()
    const layers = this._topoLayers(adj, inDeg)

    for (const layer of layers) {
      if (this._killed) {
        for (const nodeId of layer) {
          this.results.set(nodeId, { nodeId, teammateId: this.nodes.get(nodeId)!.teammateId, status: 'killed', result: '', error: 'Flow killed by upstream failure', latencyMs: 0, retries: 0 })
        }
        continue
      }

      const tasks = layer.map(nodeId => {
        const node = this.nodes.get(nodeId)!
        const depsOk = node.dependencies.every(d => this.results.get(d)?.status === 'success')
        if (!depsOk) {
          this.results.set(nodeId, { nodeId, teammateId: node.teammateId, status: 'skipped', result: '', error: 'Dependencies not met', latencyMs: 0, retries: 0 })
          return Promise.resolve()
        }
        // v2.3: 获取上游输出，构建独立输入
        const previousOutput = node.dependencies.length > 0
          ? (this.results.get(node.dependencies[node.dependencies.length - 1])?.result || '')
          : ''
        const teammateInput = this._buildTeammateInput(node, ctx, previousOutput)
        return this._execNode(node, teammateInput, ctx, previousOutput)
      })
      await Promise.all(tasks)
    }
    return this.results
  }

  // ── v2.3: 执行节点 + 质量门验证 + 智能恢复 ──
  private async _execNode(node: TaskNode, input: TeammateInput, ctx: FlowContext, previousOutput: string): Promise<void> {
    const start = Date.now()
    let lastRecovery: RecoveryDecision | null = null

    for (let attempt = 0; attempt < node.retryCount; attempt++) {
      // v2.3: 注入视角模式
      const perspective = generatePerspectiveMode(node.teammateId, input.task)
      const enhancedInput: TeammateInput = {
        ...input,
        task: input.task + '\n\n' + perspective.reasoningConstraint + '\n' + perspective.viewpointBias + '\n' + perspective.creativeVariance,
      }

      const r = await callTeammate(node.teammateId, enhancedInput, ctx.apiKey, ctx.provider, ctx.model, ctx.baseUrl)

      // ── v2.3: Quality Gate ──
      let qualityGate: QualityGate | undefined
      if (r.status === 'success' && previousOutput) {
        qualityGate = validateInformationFlow(r.result, previousOutput, node.teammateId, r.reasoning)
        if (!qualityGate.validationPassed) {
          console.log(`[QUALITY GATE FAILED] ${node.teammateId}(${node.id}): ${qualityGate.failureReason}`)
          // 质量门验证失败 = 低质量响应，立即 kill
          this.results.set(node.id, {
            nodeId: node.id, teammateId: node.teammateId, status: 'quality_check_failed',
            result: r.result, error: qualityGate.failureReason,
            latencyMs: Date.now() - start, retries: attempt, qualityGate,
          })
          this._killed = true
          return
        }
      }

      this.results.set(node.id, {
        nodeId: node.id, teammateId: node.teammateId, status: r.status, result: r.result,
        error: r.error, errorCategory: r.errorCategory, latencyMs: r.latencyMs,
        retries: attempt, qualityGate,
      })

      if (r.status === 'success') return

      // ── v2.3: Recovery System — 智能恢复决策 ──
      const recovery = decideRecovery(r.errorCategory || 'unknown', attempt, node.retryCount, node.teammateId, Object.fromEntries(this.results.entries()))
      lastRecovery = recovery
      console.log(`[RECOVERY] ${node.teammateId}(${node.id}): ${recovery.action} — ${recovery.reason}`)

      this.results.set(node.id, {
        ...this.results.get(node.id)!,
        recoveryAction: recovery.action,
      })

      switch (recovery.action) {
        case 'retry':
          await sleep(recovery.retryDelay || 2000)
          continue
        case 'backup':
          // 切换到 backup teammate
          if (recovery.backupTeammate) {
            console.log(`[BACKUP] ${node.teammateId} → ${recovery.backupTeammate}`)
            // 用 backup teammate 重新执行
            const backupInput: TeammateInput = {
              task: `[BACKUP from ${node.teammateId}] ${input.task}`,
              roleContext: input.roleContext,
              expectedOutput: input.expectedOutput,
            }
            const backupResult = await callTeammate(recovery.backupTeammate, backupInput, ctx.apiKey, ctx.provider, ctx.model, ctx.baseUrl)
            this.results.set(node.id, {
              nodeId: node.id, teammateId: recovery.backupTeammate, status: backupResult.status,
              result: backupResult.result, error: backupResult.error,
              latencyMs: Date.now() - start, retries: attempt,
              qualityGate: backupResult.status === 'success' && previousOutput
                ? validateInformationFlow(backupResult.result, previousOutput, recovery.backupTeammate, backupResult.reasoning)
                : undefined,
            })
            if (backupResult.status === 'success') return
          }
          // backup 也失败，继续重试
          await sleep(2000)
          continue
        case 'backup_output':
          // 降级模式：输出部分结果
          this._backupMode = true
          this.results.set(node.id, {
            nodeId: node.id, teammateId: node.teammateId, status: 'backup_output',
            result: r.result || '[降级模式：部分输出]', error: recovery.reason,
            latencyMs: Date.now() - start, retries: attempt,
          })
          return  // 降级后不再重试
        case 'stop':
          this._killed = true
          return
      }
    }
  }

  private _buildGraph() {
    const adj = new Map<string, string[]>()
    const inDeg = new Map<string, number>()
    for (const id of this.nodes.keys()) { inDeg.set(id, 0); adj.set(id, []) }
    for (const [from, to] of this.edges) {
      if (this.nodes.has(from) && this.nodes.has(to)) {
        adj.get(from)!.push(to)
        inDeg.set(to, (inDeg.get(to) || 0) + 1)
      }
    }
    return { adj, inDeg }
  }

  private _topoLayers(adj: Map<string, string[]>, inDeg: Map<string, number>): string[][] {
    const deg = new Map(inDeg)
    let queue = [...deg.entries()].filter(([, d]) => d === 0).map(([n]) => n)
    const layers: string[][] = []
    while (queue.length > 0) {
      layers.push([...queue])
      const next: string[] = []
      for (const id of queue) {
        for (const nb of adj.get(id) || []) {
          deg.set(nb, deg.get(nb)! - 1)
          if (deg.get(nb) === 0) next.push(nb)
        }
      }
      queue = next
    }
    return layers
  }
}

// ═══════════════════════════════════════════
// ③ v5 Adaptive Complexity Classifier (zero-LLM-call)
// ═══════════════════════════════════════════

type EffortLevel = 'SIMPLE' | 'STANDARD' | 'COMPLEX'

interface Classification {
  level: EffortLevel
  confidence: number
  reasons: string[]
}

function classifyEffortLevel(task: string): Classification {
  const text = task.toLowerCase().trim()
  const reasons: string[] = []
  let simpleScore = 0, standardScore = 0, complexScore = 0

  // Short query → SIMPLE
  const words = text.split(/\s+/)
  if (words.length <= 5 && task.length <= 30) {
    reasons.push(`Short query (${words.length} words)`)
    return { level: 'SIMPLE', confidence: 0.9, reasons }
  }

  // Simple keywords
  const simpleKws = ['什么','定义','解释','意思','时间','日期','天气','翻译','拼写','读音','多少','哪个','是谁','what is','define','explain','meaning','time','date','translate','spell','how many','who is','trivial','simple','quick']
  for (const kw of simpleKws) { if (text.includes(kw)) { simpleScore += 2; reasons.push(`Simple kw: ${kw}`) } }

  // Standard keywords
  const stdKws = ['写','创建','实现','分析','优化','重构','调试','计算','排序','搜索','过滤','解析','验证','write','create','implement','analyze','optimize','refactor','debug','calculate','sort','search','filter','parse','validate','test','review','function','class','module','script']
  for (const kw of stdKws) { if (text.includes(kw)) { standardScore += 1; reasons.push(`Standard kw: ${kw}`) } }

  // Complex keywords
  const complexKws = ['设计','架构','系统','平台','框架','完整','全栈','部署','集成','迁移','构建','搭建','多步骤','工作流','pipeline','workflow','multi-step','microservice','orchestration','end-to-end','full-stack']
  for (const kw of complexKws) { if (text.includes(kw)) { complexScore += 2; reasons.push(`Complex kw: ${kw}`) } }

  // Complex patterns
  const complexPatterns = [/首先.*然后|第一步.*第二步|先.*再.*最后/, /(and\s+then|then\s+\w+|step\s+\d+|first.*then.*finally)/i, /(multiple|several|various)\s+(steps?|components?|services?)/i]
  for (const p of complexPatterns) { if (p.test(text)) { complexScore += 3; reasons.push(`Complex pattern: ${p.source.slice(0,40)}`) } }

  // Structural
  const sentences = text.split(/[.!?。！？]+/).filter(Boolean)
  if (sentences.length >= 3) { standardScore += 1; reasons.push(`Multiple sentences (${sentences.length})`) }
  if (words.length > 50) { complexScore += 1; reasons.push(`Long task (${words.length} words)`) }
  if (/```|def |class |import |from |function |const |let |var /.test(text)) { standardScore += 2; reasons.push('Contains code refs') }

  if (Math.max(simpleScore, standardScore, complexScore) === 0) {
    reasons.push('No signals → default STANDARD')
    return { level: 'STANDARD', confidence: 0.5, reasons }
  }

  const scores = { SIMPLE: simpleScore, STANDARD: standardScore, COMPLEX: complexScore }
  const best = (Object.entries(scores).sort((a, b) => b[1] - a[1])[0][0]) as EffortLevel
  const total = simpleScore + standardScore + complexScore
  let confidence = scores[best] / total
  const sorted = Object.values(scores).sort((a, b) => b - a)
  if (sorted[0] > 2 * (sorted[1] || 0)) confidence = Math.min(confidence + 0.15, 1.0)
  reasons.push(`Scores: S=${simpleScore} ST=${standardScore} C=${complexScore}`)

  return { level: best, confidence: Math.round(confidence * 100) / 100, reasons }
}

// ═══════════════════════════════════════════
// ③ v5 Adaptive TeamEngine
// ═══════════════════════════════════════════

type AdaptiveMode = 'SIMPLE' | 'STANDARD' | 'COMPLEX'

interface AdaptiveOrchContext {
  taskId: string
  userInput: string
  mode: AdaptiveMode
  effort_level: Classification
  state: string
  plan: any
  executionResult: any
  reviewResult: any
  finalResult: string
  llmCalls: number
  skippedStages: string[]
  error: string
}

async function runAdaptiveTeamEngine(
  task: string,
  apiKey: string,
  provider: string,
  model: string,
  baseUrl: string | null,
  forceMode?: string | null,
): Promise<{ context: AdaptiveOrchContext; trace: TraceEvent[] }> {
  const traceId = crypto.randomUUID().slice(0, 12)
  const trace: TraceEvent[] = []
  const record = (step: string, teammate: string, inputData: any, outputData: any, latencyMs: number, tokens = 0) => {
    trace.push({ traceId, taskId: ctx.taskId, step, teammate, inputData, outputData, latencyMs, tokens, ts: Date.now() })
  }

  // ── Classify ──
  const classification = classifyComplexity(task)
  const mode: AdaptiveMode = forceMode || classification.level

  const ctx: AdaptiveOrchContext = {
    taskId: crypto.randomUUID().slice(0, 12),
    userInput: task,
    mode,
    effort_level: classification,
    state: 'CLASSIFY',
    plan: {},
    executionResult: {},
    reviewResult: {},
    finalResult: '',
    llmCalls: 0,
    skippedStages: [],
    error: '',
  }

  record('CLASSIFY', 'classifier', { task }, { mode, effort_level: classification, reasons: classification.reasons }, 0)
  ctx.state = mode === 'SIMPLE' ? 'SIMPLE_EXEC' : mode === 'STANDARD' ? 'STD_EXEC' : 'PLAN'

  // ── SIMPLE: engineer only ──
  if (mode === 'SIMPLE') {
    ctx.skippedStages = ['strategy', 'quality', 'validation_gate']
    const start = Date.now()
    const input: TeammateInput = { task, roleContext: `任务：${task}`, expectedOutput: 'JSON 输出' }
    const r = await callTeammate('engineer', input, apiKey, provider, model, baseUrl)
    ctx.llmCalls++
    record('SIMPLE_EXEC', 'engineer', { task }, { result: r.result.slice(0, 300) }, Date.now() - start, r.tokensUsed)

    if (r.status === 'success') {
      ctx.executionResult = { result: r.result, reasoning: r.reasoning }
      ctx.finalResult = r.result
      ctx.state = 'DONE'
    } else {
      ctx.error = r.error || 'Executor failed'
      ctx.state = 'FAILED'
    }
    record('COMPLETE', '', {}, { mode: 'SIMPLE', llmCalls: ctx.llmCalls, skipped: ctx.skippedStages }, 0)
    return { context: ctx, trace }
  }

  // ── STANDARD: engineer + validation ──
  if (mode === 'STANDARD') {
    ctx.skippedStages = ['strategy', 'quality']
    const start = Date.now()
    const input: TeammateInput = { task, roleContext: `任务：${task}`, expectedOutput: 'JSON 输出' }
    const r = await callTeammate('engineer', input, apiKey, provider, model, baseUrl)
    ctx.llmCalls++
    record('STD_EXEC', 'engineer', { task }, { result: r.result.slice(0, 300) }, Date.now() - start, r.tokensUsed)

    if (r.status === 'success') {
      ctx.executionResult = { result: r.result, reasoning: r.reasoning }
      ctx.finalResult = r.result

      ctx.state = 'DONE'

    } else {

      ctx.error = r.error || 'Executor failed'
      ctx.state = 'FAILED'
    }
    record('COMPLETE', '', {}, { mode: 'STANDARD', llmCalls: ctx.llmCalls, skipped: ctx.skippedStages }, 0)
    return { context: ctx, trace }
  }

  // ── COMPLEX: strategy → engineer → quality ──
  // PLAN
  const planStart = Date.now()
  const planInput: TeammateInput = { task: `制定执行计划：${task}`, roleContext: `原始任务：${task}`, expectedOutput: '任务拆解方案（JSON）' }
  const planResult = await callTeammate('strategy', planInput, apiKey, provider, model, baseUrl)
  ctx.llmCalls++
  ctx.plan = { strategy: planResult.result, reasoning: planResult.reasoning }
  record('PLAN', 'strategy', { task }, ctx.plan, Date.now() - planStart, planResult.tokensUsed)
  ctx.state = 'EXECUTE'

  // EXECUTE (use plan result as context)
  const execStart = Date.now()
  const execInput: TeammateInput = {
    task: `根据计划执行：${task}`,
    roleContext: `上游 Planner 的拆解方案：${planResult.result}`,
    expectedOutput: '可运行代码（JSON）',
  }
  const execResult = await callTeammate('engineer', execInput, apiKey, provider, model, baseUrl)
  ctx.llmCalls++
  ctx.executionResult = { result: execResult.result, reasoning: execResult.reasoning }
  ctx.finalResult = execResult.result
  record('EXECUTE', 'engineer', { plan: ctx.plan }, { result: execResult.result.slice(0, 300) }, Date.now() - execStart, execResult.tokensUsed)
  ctx.state = 'REVIEW'

  // REVIEW
  const reviewStart = Date.now()
  const reviewInput: TeammateInput = {
    task: `评审以下执行结果：\n\n任务：${task}\n\n结果：${execResult.result.slice(0, 800)}`,
    roleContext: `待评审的代码：${execResult.result.slice(0, 500)}`,
    expectedOutput: '评审结果（JSON）：pass/fail + issues + coverage',
  }
  const reviewResult = await callTeammate('quality', reviewInput, apiKey, provider, model, baseUrl)
  ctx.llmCalls++
  ctx.reviewResult = parseReviewEnhanced(reviewResult.result)
  record('REVIEW', 'quality', { resultPreview: execResult.result.slice(0, 200) }, ctx.reviewResult, Date.now() - reviewStart, reviewResult.tokensUsed)

  ctx.state = 'DONE'
  record('COMPLETE', '', {}, { mode: 'COMPLEX', llmCalls: ctx.llmCalls }, 0)
  return { context: ctx, trace }
}



interface TraceEvent {
  traceId: string
  taskId: string
  step: string
  teammate: string
  inputData: any
  outputData: any
  latencyMs: number
  tokens: number
  ts: number
}






// ── v2.1: Enhanced review parser with failure categorization ──
function parseReviewEnhanced(raw: string): {
  pass: boolean
  reason: string
  suggestions: string
  failureCategory: string
  rootCause: string
  severity: string
} {
  const backup = {
    pass: false,
    reason: raw.slice(0, 200),
    suggestions: '',
    failureCategory: 'format_error' as string,
    rootCause: 'Failed to parse review JSON',
    severity: 'major',
  }
  if (!raw || !raw.trim()) return backup

  try {
    let t = raw.trim()
    if (t.startsWith('```')) t = t.split('\n').filter(l => !l.trim().startsWith('```')).join('\n').trim()
    const s = t.indexOf('{'), e = t.lastIndexOf('}')
    if (s >= 0 && e > s) {
      const obj = JSON.parse(t.slice(s, e + 1))
      return {
        pass: obj.pass === true,
        reason: obj.reason || '',
        suggestions: obj.suggestions || '',
        failureCategory: obj.failure_category || 'none',
        rootCause: obj.root_cause || '',
        severity: obj.severity || 'none',
      }
    }
  } catch {}

  // Fallback: check for pass keywords
  const isPass = /通过|pass|true|合格|good/i.test(raw) && !/fail|失败|不通过/i.test(raw)
  return { ...backup, pass: isPass, failureCategory: isPass ? 'none' : 'format_error' }
}

// ═══════════════════════════════════════════
// ④ Memory System (4-Layer, D1-backed)
// ═══════════════════════════════════════════

async function loadContext(db: D1Database, taskId: string): Promise<string> {
  return `## Long-Term Memory\nNo prior context yet.\n\n## Recent Context\nNo prior discussion yet.\n\n## Relevant Memories\nNone yet.`
}

async function loadHistory(db: D1Database, taskId: string): Promise<string> {
  try {
    const { results } = await db.prepare(
      'SELECT role, content FROM messages WHERE channel_id = ? ORDER BY created_at LIMIT 6'
    ).bind(taskId).all()
    if (!results || results.length === 0) return '[RECENT CONTEXT]\nNo recent messages.'
    const lines = results.map((m: any) => `${m.role === 'user' ? 'User' : 'Assistant'}: ${m.content.slice(0, 200)}`)
    return '[RECENT CONTEXT]\n' + lines.join('\n')
  } catch {
    return '[RECENT CONTEXT]\nNo recent messages.'
  }
}




// ═══════════════════════════════════════════
// Helpers
// ═══════════════════════════════════════════

function genUUID(): string { return crypto.randomUUID() }
function utcNow(): string { return new Date().toISOString() }
function json(data: any, status = 200, headers?: Record<string, string>): Response {
  const h: Record<string, string> = { 'Content-Type': 'application/json', ...headers }
  return new Response(JSON.stringify(data), { status, headers: h })
}
function error(message: string, status = 400): Response {
  return new Response(JSON.stringify({ detail: message }), { status, headers: { 'Content-Type': 'application/json' } })
}
function setCors(response: Response): Response {
  response.headers.set('Access-Control-Allow-Origin', '*')
  response.headers.set('Access-Control-Allow-Methods', 'GET, POST, PUT, PATCH, DELETE, OPTIONS')
  response.headers.set('Access-Control-Allow-Headers', 'Content-Type')
  return response
}
function corsResponse(): Response {
  return new Response(null, { status: 204, headers: { 'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Methods': 'GET, POST, PUT, PATCH, DELETE, OPTIONS', 'Access-Control-Allow-Headers': 'Content-Type', 'Access-Control-Max-Age': '86400' } })
}
function sleep(ms: number): Promise<void> { return new Promise(r => setTimeout(r, ms)) }

const PROVIDER_ENDPOINTS: Record<string, string> = {
  openai: 'https://api.openai.com/v1/chat/completions',
  anthropic: 'https://api.anthropic.com/v1/messages',
  google: 'https://generativelanguage.googleapis.com/v1beta/openai/chat/completions',
  mistral: 'https://api.mistral.ai/v1/chat/completions',
  groq: 'https://api.groq.com/openai/v1/chat/completions',
  together: 'https://api.together.xyz/v1/chat/completions',
  openrouter: 'https://openrouter.ai/api/v1/chat/completions',
  deepseek: 'https://api.deepseek.com/v1/chat/completions',
  zhipu: 'https://open.bigmodel.cn/api/paas/v4/chat/completions',
  moonshot: 'https://api.moonshot.cn/v1/chat/completions',
  baidu: 'https://aip.baidubce.com/rpc/2.0/ai_custom/v1/wenxinworkshop/chat/completions',
  alibaba: 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions',
  doubao: 'https://ark.cn-beijing.volces.com/api/v3/chat/completions',
  hunyuan: 'https://api.hunyuan.cloud.tencent.com/v1/chat/completions',
  baichuan: 'https://api.baichuan-ai.com/v1/chat/completions',
  yi: 'https://api.01.ai/v1/chat/completions',
  minimax: 'https://api.minimax.chat/v1/text/chatcompletion_v2',
  stepfun: 'https://api.stepfun.com/v1/chat/completions',
  spark: 'https://spark-api-open.xf-yun.com/v1/chat/completions',
  siliconflow: 'https://api.siliconflow.cn/v1/chat/completions',
}

function getEndpoint(provider: string, baseUrl: string | null): string {
  if (!baseUrl) return PROVIDER_ENDPOINTS[provider] || `https://api.${provider}.com/v1/chat/completions`
  if (baseUrl.includes('/responses')) return baseUrl.replace(/\/$/, '')
  return `${baseUrl.replace(/\/$/, '')}/v1/chat/completions`
}

function buildFixedPrompt(systemPrompt: string, recentTurns: { role: string; content: string }[], currentContent: string) {
  const summaryBlock = 'The following is a conversation between a user and AI assistant(s) in a team channel.'
  const messages: { role: string; content: string }[] = [
    { role: 'system', content: systemPrompt },
    { role: 'user', content: summaryBlock },
    { role: 'assistant', content: 'I understand. How can I help you today?' },
    { role: 'user', content: 'Tell me about yourself.' },
    { role: 'assistant', content: 'I am an AI assistant in this team channel, ready to help with tasks, coding, analysis, and discussion.' },
    ...recentTurns.map(m => ({ ...m, role: m.role === 'ai' ? 'assistant' : m.role })),
    { role: 'user', content: currentContent },
  ]
  return messages
}

function formatChannel(row: any) {
  return { id: row.id, name: row.name, description: row.description || '', teammate_ids: JSON.parse(row.teammate_ids || '[]'), created_at: row.created_at, updated_at: row.updated_at }
}
function formatTeammate(row: any) {
  return { id: row.id, name: row.name, role: row.role || 'assistant', avatar_emoji: row.avatar_emoji || '🤖', system_prompt: row.system_prompt || '', model_provider: row.model_provider, model_name: row.model_name, api_key_ref: row.api_key_ref || undefined }
}
function formatMessage(row: any) {
  return { id: row.id, channel_id: row.channel_id, role: row.role, author_name: row.author_name, author_id: row.author_id || undefined, content: row.content || '', attachments: row.attachments ? JSON.parse(row.attachments) : [], created_at: row.created_at }
}

// ═══════════════════════════════════════════
// Router
// ═══════════════════════════════════════════

interface Route { method: string; pattern: RegExp; handler: (request: Request, match: RegExpMatchArray, env: Env) => Promise<Response> | Response }
const routes: Route[] = []
function route(method: string, pattern: string, handler: Route['handler']) {
  const regex = new RegExp('^' + pattern.replace(/:[^/]+/g, '([^/]+)') + '$')
  routes.push({ method, pattern: regex, handler })
}
function matchRoute(method: string, pathname: string): { handler: Route['handler']; match: RegExpMatchArray } | null {
  for (const r of routes) {
    if (r.method !== method && r.method !== 'ANY') continue
    const match = pathname.match(r.pattern)
    if (match) return { handler: r.handler, match }
  }
  return null
}

// Channels
route('GET', '/api/channels', async (_req, _match, env) => {
  const { results } = await env.DB.prepare('SELECT * FROM channels ORDER BY created_at').all()
  return json(results.map(formatChannel))
})
route('POST', '/api/channels', async (req, _match, env) => {
  const data = await req.json(); const id = genUUID(); const now = utcNow()
  await env.DB.prepare('INSERT INTO channels (id, name, description, created_at, updated_at, teammate_ids) VALUES (?, ?, ?, ?, ?, ?)').bind(id, data.name || '', data.description || '', now, now, '[]').run()
  return json({ id, name: data.name, description: data.description || '' }, 201)
})
route('GET', '/api/channels/:id', async (_req, match, env) => {
  const id = match[1]; const row = await env.DB.prepare('SELECT * FROM channels WHERE id = ?').bind(id).first()
  if (!row) return error('Channel not found', 404)
  return json(formatChannel(row))
})
route('PATCH', '/api/channels/:id', async (req, match, env) => {

  const id = match[1]; const data = await req.json(); const existing = await env.DB.prepare('SELECT * FROM channels WHERE id = ?').bind(id).first()
  if (!existing) return error('Channel not found', 404)

  const name = data.name ?? existing.name; const description = data.description ?? existing.description
  await env.DB.prepare('UPDATE channels SET name = ?, description = ?, updated_at = ? WHERE id = ?').bind(name, description, utcNow(), id).run()

  return json({ ok: true })
})
route('DELETE', '/api/channels/:id', async (_req, match, env) => {
  const id = match[1]; const existing = await env.DB.prepare('SELECT id FROM channels WHERE id = ?').bind(id).first()
  if (!existing) return error('Channel not found', 404)
  await env.DB.prepare('DELETE FROM messages WHERE channel_id = ?').bind(id).run()
  await env.DB.prepare('DELETE FROM channels WHERE id = ?').bind(id).run()
  return json({ ok: true })
})
route('POST', '/api/channels/:id/teammates/:teammate_id', async (_req, match, env) => {
  const channelId = match[1]; const teammateId = match[2]
  const ch = await env.DB.prepare('SELECT * FROM channels WHERE id = ?').bind(channelId).first()
  if (!ch) return error('Channel not found', 404)
  const tm = await env.DB.prepare('SELECT id FROM teammates WHERE id = ?').bind(teammateId).first()
  if (!tm) return error('Teammate not found', 404)
  const ids: string[] = JSON.parse(ch.teammate_ids || '[]')
  if (!ids.includes(teammateId)) ids.push(teammateId)
  await env.DB.prepare('UPDATE channels SET teammate_ids = ?, updated_at = ? WHERE id = ?').bind(JSON.stringify(ids), utcNow(), channelId).run()
  return json({ ok: true, teammate_ids: ids })
})
route('DELETE', '/api/channels/:id/teammates/:teammate_id', async (_req, match, env) => {
  const channelId = match[1]; const teammateId = match[2]
  const ch = await env.DB.prepare('SELECT * FROM channels WHERE id = ?').bind(channelId).first()
  if (!ch) return error('Channel not found', 404)
  const ids: string[] = JSON.parse(ch.teammate_ids || '[]')
  const idx = ids.indexOf(teammateId)
  if (idx >= 0) ids.splice(idx, 1)
  await env.DB.prepare('UPDATE channels SET teammate_ids = ?, updated_at = ? WHERE id = ?').bind(JSON.stringify(ids), utcNow(), channelId).run()
  return json({ ok: true, teammate_ids: ids })
})

// Teammates
route('GET', '/api/teammates', async (_req, _match, env) => {
  const { results } = await env.DB.prepare('SELECT * FROM teammates ORDER BY created_at').all()
  return json(results.map(formatTeammate))
})
route('POST', '/api/teammates', async (req, _match, env) => {
  const data = await req.json(); const id = genUUID(); const now = utcNow()
  await env.DB.prepare('INSERT INTO teammates (id, name, role, avatar_emoji, system_prompt, model_provider, model_name, api_key_ref, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)').bind(id, data.name || '', data.role || 'assistant', data.avatar_emoji || '🤖', data.system_prompt || 'You are a helpful AI assistant.', data.model_provider || '', data.model_name || '', data.api_key_ref || null, now, now).run()
  return json({ id, name: data.name }, 201)
})
route('GET', '/api/teammates/:id', async (_req, match, env) => {
  const id = match[1]; const row = await env.DB.prepare('SELECT * FROM teammates WHERE id = ?').bind(id).first()
  if (!row) return error('Teammate not found', 404)
  return json(formatTeammate(row))
})
route('PATCH', '/api/teammates/:id', async (req, match, env) => {
  const id = match[1]; const data = await req.json()
  const existing = await env.DB.prepare('SELECT * FROM teammates WHERE id = ?').bind(id).first()
  if (!existing) return error('Teammate not found', 404)
  const fields = ['name', 'role', 'avatar_emoji', 'system_prompt', 'model_provider', 'model_name', 'api_key_ref']
  const updates: string[] = []; const values: any[] = []
  for (const f of fields) { if (f in data) { updates.push(`${f} = ?`); values.push(data[f]) } }
  if (updates.length > 0) { updates.push('updated_at = ?'); values.push(utcNow()); values.push(id); await env.DB.prepare(`UPDATE teammates SET ${updates.join(', ')} WHERE id = ?`).bind(...values).run() }
  return json({ ok: true })
})
route('DELETE', '/api/teammates/:id', async (_req, match, env) => {
  const id = match[1]; const existing = await env.DB.prepare('SELECT id FROM teammates WHERE id = ?').bind(id).first()
  if (!existing) return error('Teammate not found', 404)
  await env.DB.prepare('DELETE FROM teammates WHERE id = ?').bind(id).run()
  return json({ ok: true })
})

// API Keys
route('GET', '/api/apikeys', async (_req, _match, env) => {
  const { results } = await env.DB.prepare('SELECT * FROM apikeys ORDER BY created_at').all()
  return json(results.map((k: any) => ({ id: k.id, provider: k.provider, label: k.label, api_key: k.api_key ? k.api_key.slice(0, 8) + '***' : '', base_url: k.base_url, has_key: !!k.api_key })))
})
route('POST', '/api/apikeys', async (req, _match, env) => {
  const data = await req.json(); const id = genUUID(); const now = utcNow()
  await env.DB.prepare('INSERT INTO apikeys (id, provider, label, api_key, base_url, created_at) VALUES (?, ?, ?, ?, ?, ?)').bind(id, data.provider || '', data.label || '', data.api_key || '', data.base_url || null, now).run()
  return json({ id, provider: data.provider, label: data.label, has_key: !!data.api_key }, 201)
})
route('DELETE', '/api/apikeys/:id', async (_req, match, env) => {
  const id = match[1]; const existing = await env.DB.prepare('SELECT id FROM apikeys WHERE id = ?').bind(id).first()
  if (!existing) return error('API Key not found', 404)
  await env.DB.prepare('DELETE FROM apikeys WHERE id = ?').bind(id).run()
  return json({ ok: true })
})

// Messages
route('GET', '/api/messages/:channel_id', async (_req, match, env) => {
  const channelId = match[1]; const limitStr = new URL(_req.url).searchParams.get('limit'); const limit = Number(limitStr || 200)
  const { results } = await env.DB.prepare('SELECT * FROM messages WHERE channel_id = ? ORDER BY created_at LIMIT ?').bind(channelId, limit).all()
  return json(results.map(formatMessage))
})
route('DELETE', '/api/messages/:channel_id', async (_req, match, env) => {
  const channelId = match[1]; const ch = await env.DB.prepare('SELECT id FROM channels WHERE id = ?').bind(channelId).first()
  if (!ch) return error('Channel not found', 404)
  const { results } = await env.DB.prepare('DELETE FROM messages WHERE channel_id = ? RETURNING id').bind(channelId).all()
  return json({ ok: true, deleted: results.length })
})
route('POST', '/api/messages/:channel_id/system', async (req, match, env) => {
  const channelId = match[1]; const data = await req.json()
  const ch = await env.DB.prepare('SELECT id FROM channels WHERE id = ?').bind(channelId).first()
  if (!ch) return error('Channel not found', 404)
  const id = genUUID()
  await env.DB.prepare('INSERT INTO messages (id, channel_id, role, author_name, content, created_at) VALUES (?, ?, ?, ?, ?, ?)').bind(id, channelId, 'system', data.author_name || 'System', data.content || '', utcNow()).run()
  return json({ id, role: 'system' }, 201)
})

// AI Chat
route('POST', '/api/messages/:channel_id', async (req, match, env) => {
  const channelId = match[1]; const data = await req.json()
  const channel = await env.DB.prepare('SELECT id FROM channels WHERE id = ?').bind(channelId).first()
  if (!channel) return error('Channel not found', 404)
  const content = data.content || ''; const teammateId = data.teammate_id || null
  const skipUserSave = data.skip_user_save || false; const authorName = data.author_name || 'You'
  let userMsgId: string | null = null
  if (!skipUserSave) {
    userMsgId = genUUID()
    await env.DB.prepare('INSERT INTO messages (id, channel_id, role, author_name, content, attachments, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)').bind(userMsgId, channelId, 'user', authorName, content, data.attachments ? JSON.stringify(data.attachments) : null, utcNow()).run()
  }
  if (!teammateId) return json({ user_message_id: userMsgId })
  const tm = await env.DB.prepare('SELECT * FROM teammates WHERE id = ?').bind(teammateId).first()
  if (!tm) return error('Teammate not found', 404)
  if (!tm.api_key_ref) return error('Teammate has no API key configured', 400)
  const apiKeyRow = await env.DB.prepare('SELECT * FROM apikeys WHERE id = ?').bind(tm.api_key_ref).first()
  if (!apiKeyRow || !apiKeyRow.api_key) return error('API key not found', 400)
  const { results: msgResults } = await env.DB.prepare('SELECT role, content FROM messages WHERE channel_id = ? ORDER BY created_at LIMIT 200').bind(channelId).all()
  const allMessages = msgResults.map((m: any) => ({ role: m.role === 'ai' ? 'assistant' : m.role, content: m.content }))
  const recentTurns = allMessages.slice(-6)
  const fixedMessages = buildFixedPrompt(tm.system_prompt, recentTurns, content)
  const provider = tm.model_provider as string; const isAnthropic = provider === 'anthropic'
  const endpoint = getEndpoint(provider, apiKeyRow.base_url as string | null)
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  let payload: any
  if (isAnthropic) {
    headers['x-api-key'] = apiKeyRow.api_key; headers['anthropic-version'] = '2023-06-01'
    payload = { model: tm.model_name, system: tm.system_prompt, messages: fixedMessages.filter((m: any) => m.role !== 'system'), max_tokens: 4096, stream: true }
  } else {
    headers['Authorization'] = `Bearer ${apiKeyRow.api_key}`
    payload = { model: tm.model_name, messages: fixedMessages, stream: false, temperature: 0.7, max_tokens: 2000 }
  }
  let response
  try { response = await fetch(endpoint, { method: 'POST', headers, body: JSON.stringify(payload), redirect: 'follow' }) }
  catch (fetchErr: any) { return json({ detail: `AI Fetch Error: ${fetchErr.message}` }, 502) }
  if (!response.ok) { const text = await response.text(); return json({ detail: `AI Error: ${response.status} ${text.slice(0, 200)}` }, 502) }
  const r = await response.json(); let full = ''
  if (r.choices?.[0]?.message?.content) full = r.choices[0].message.content
  else if (r.output?.[0]?.content?.[0]?.text) full = r.output[0].content[0].text
  if (full.trim()) { const aiMsgId = genUUID(); try { await env.DB.prepare('INSERT INTO messages (id, channel_id, role, author_name, author_id, content, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)').bind(aiMsgId, channelId, 'ai', tm.name, teammateId, full, utcNow()).run() } catch (e) { console.error('Failed to save AI response:', e) } }
  const encoder = new TextEncoder(); const stream = new ReadableStream({ start(controller) { controller.enqueue(encoder.encode(full)); controller.close() } })
  return new Response(stream, { headers: { 'Content-Type': 'text/plain; charset=utf-8' } })
})

// Models
route('GET', '/api/models/:provider', async (_req, match, env) => {
  const provider = match[1]
  if (provider === 'openrouter') {
    const res = await fetch('https://openrouter.ai/api/v1/models')
    const data = await res.json()
    return json((data.data || []).map((m: any) => ({ id: m.id, name: m.name || m.id, context_length: m.context_length || 0, is_free: (m.pricing?.prompt === '0'), pricing: m.pricing || {} })))
  }
  return json([{ id: provider + '-default', name: provider + ' Default', context_length: 32000 }])
})

// Health
route('GET', '/api/health', () => {
  return json({ status: 'ok', service: 'AI Team Hub', version: '2.1.0', engine: 'state_machine_dag', platform: 'cloudflare_workers' })
})

// Debug: check API key and D1
route('GET', '/api/debug', async (_req, _match, env) => {
  try {
    const row = await env.DB.prepare('SELECT id, provider, label, length(api_key) as key_len FROM apikeys LIMIT 1').first()
    return json({ db: 'ok', key_len: row?.key_len || 0, provider: row?.provider || 'none' })
  } catch (e: any) {
    return json({ db: 'error', detail: e.message }, 500)
  }
})

// v5 Adaptive TeamEngine (default)
route('POST', '/api/team/chat', async (req, _match, env) => {
  try {
    const data = await req.json()
    const task = data.task || ''
    const provider = data.provider || 'openrouter'; const model = data.model || 'openrouter/auto'
    const forceMode = data.force_mode || null  // SIMPLE | STANDARD | COMPLEX

    const apiKeyRow = await env.DB.prepare('SELECT * FROM apikeys WHERE provider = ? LIMIT 1').bind(provider).first()
    if (!apiKeyRow || !apiKeyRow.api_key) return error(`No API key for provider: ${provider}`, 400)

    // v5: Adaptive orchestration — classifier decides mode
    const result = await runAdaptiveTeamEngine(task, apiKeyRow.api_key, provider, model, apiKeyRow.base_url, forceMode)
    return json({
      request_id: result.context.taskId,
      log_id: result.trace[0]?.traceId || '',
      state: result.context.state,
      mode: result.context.mode,
      effort_level: result.context.effort_level,
      plan: result.context.plan,
      output: result.context.executionResult,
      quality_check: result.context.reviewResult,
      response: result.context.finalResult,
      model_calls: result.context.llmCalls,
      skipped_steps: result.context.skippedStages,
      log_length: result.trace.length,
    })
  } catch (e: any) {
    console.error('TeamEngine error:', e.message, e.stack)
    return json({ error: 'TeamEngine failed', detail: e.message }, 500)
  }
})


// ═══════════════════════════════════════════
// Main Handler
// ═══════════════════════════════════════════

// Cloudflare Workers service worker format
addEventListener('fetch', (event: any) => {
  event.respondWith(handleRequest(event.request, event.env))
})

async function handleRequest(request: any, env: any): Promise<Response> {
  const url = new URL(request.url); const pathname = url.pathname; const method = request.method
  if (method === 'OPTIONS') return corsResponse()
  const matched = matchRoute(method, pathname)
  if (matched) { const response = await matched.handler(request, matched.match, env); return setCors(response) }
  return error('Not found', 404)
}
