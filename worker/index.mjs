/**
 * AI Team Hub v2.3 — Cloudflare Workers (全托管 Serverless)
 *
 * v2.3 修复:
 * 1. Information Flow Validation Layer — 每跳验证 input_used / decision_influenced / diff_from_previous
 *   防止"假协作"（agent 走流程但没真正使用上游输出）
 * 2. Recovery System — error → classify → retry / fallback / degrade mode
 *   不再简单 stop，而是智能恢复
 * 3. Cognitive Diversity Amplifier — reasoning constraint + perspective forcing + entropy injection
 *   防止 agent 思维太像
 */
// ── v2.3: 验证信息流转 —— 防止"假协作" ──
function validateInformationFlow(currentOutput, previousOutput, agentRole, currentReasoning) {
    // 1. 检查 input 是否被使用
    // 对于 executor：检查 reasoning 中是否引用了 plan 的子任务名称
    // 对于 reviewer：检查 reasoning 中是否引用了代码中的函数/类名
    // 对于 researcher：检查 reasoning 中是否引用了原始任务的关键词
    let inputUsed = false;
    if (agentRole === 'executor' && currentReasoning) {
        // executor 的 reasoning 应该引用 plan 的子任务名称
        const planItems = extractPlanItemNames(previousOutput);
        inputUsed = planItems.some(name => currentReasoning.includes(name));
    }
    else if (agentRole === 'reviewer' && currentReasoning) {
        // reviewer 的 reasoning 应该引用代码中的函数/类名
        const codeSymbols = extractCodeSymbols(previousOutput);
        inputUsed = codeSymbols.some(sym => currentReasoning.includes(sym));
    }
    else if (agentRole === 'researcher' && currentReasoning) {
        // researcher 的 reasoning 应该引用原始任务关键词
        const taskKeywords = extractKeywords(previousOutput);
        inputUsed = taskKeywords.some(kw => currentReasoning.includes(kw));
    }
    else {
        // 默认：关键词匹配
        const prevKeywords = extractKeywords(previousOutput);
        inputUsed = prevKeywords.some(kw => currentOutput.includes(kw));
    }
    // 2. 检查决策是否受上一步影响
    const diff = computeDiff(previousOutput, currentOutput);
    const decisionInfluenced = diff > 0.1;
    // 3. 综合验证（阈值根据角色调整）
    const threshold = agentRole === 'executor' ? 0.15 : 0.37;
    const validationPassed = inputUsed && decisionInfluenced && diff > threshold;
    let failureReason = '';
    if (!inputUsed)
        failureReason = `input_not_used: ${agentRole} 未在 reasoning 中引用上游输出`;
    else if (!decisionInfluenced)
        failureReason = 'decision_not_influenced: 决策未受上一步影响';
    else if (diff <= threshold)
        failureReason = `diff_too_low: ${diff.toFixed(2)} < ${threshold}，疑似假协作`;
    return { inputUsed, decisionInfluenced, diffFromPrevious: diff, validationPassed, failureReason };
}
// ── 从 plan JSON 中提取子任务名称 ──
function extractPlanItemNames(planOutput) {
    try {
        // 尝试解析 JSON
        const jsonMatch = planOutput.match(/\[.*\]/s);
        if (jsonMatch) {
            const items = JSON.parse(jsonMatch[0]);
            return items.map((item) => item.name || item.description || '').filter(Boolean);
        }
    }
    catch { }
    // fallback：提取引号中的内容
    const matches = planOutput.match(/"name"\s*:\s*"([^"]+)"/g);
    return matches ? matches.map(m => m.replace(/"name"\s*:\s*"([^"]+)"/, '$1')) : [];
}
// ── 从代码中提取函数/类名 ──
function extractCodeSymbols(codeOutput) {
    const symbols = [];
    // 匹配 class 定义
    const classMatches = codeOutput.matchAll(/class\s+(\w+)/g);
    for (const m of classMatches)
        symbols.push(m[1]);
    // 匹配 def 定义
    const defMatches = codeOutput.matchAll(/def\s+(\w+)/g);
    for (const m of defMatches)
        symbols.push(m[1]);
    // 匹配 import
    const importMatches = codeOutput.matchAll(/import\s+(\w+)/g);
    for (const m of importMatches)
        symbols.push(m[1]);
    return [...new Set(symbols)].slice(0, 15);
}

function extractKeywords(text) {
        // 提取有意义的关键词（去除停用词）
        const stopWords = ['的', '是', '在', '了', '和', '与', '或', 'the', 'a', 'an', 'is', 'are', 'was', 'were', 'to', 'of', 'in', 'for', 'on', 'with', 'at', 'by', 'from', 'as', 'into', 'through', 'during', 'before', 'after', 'above', 'below', 'between', 'out', 'off', 'over', 'under', 'again', 'further', 'then', 'once'];
        const words = text.toLowerCase().split(/\s+/).filter(w => w.length > 2 && !stopWords.includes(w));
        return [...new Set(words)].slice(0, 20); // 去重，取前20个
    }
    function computeDiff(a, b) {
        // 简单的 Jaccard 距离作为差异度
        const setA = new Set(a.toLowerCase().split(/\s+/));
        const setB = new Set(b.toLowerCase().split(/\s+/));
        const intersection = new Set([...setA].filter(x => setB.has(x)));
        const union = new Set([...setA, ...setB]);
        if (union.size === 0)
            return 0;
        return 1 - (intersection.size / union.size); // Jaccard 距离 = 1 - Jaccard 相似度
    }
    // ── v2.3: 智能恢复决策 —— 不再简单 stop ──
    function decideRecovery(errorCategory, attempt, maxRetries, agentId, previousResults) {
        // auth/format 错误：不可重试，尝试 fallback 或 degrade
        if (errorCategory === 'auth' || errorCategory === 'format') {
            // 如果有 fallback agent，切换
            const fallbackMap = {
                'planner': 'executor', // planner 失败，executor 尝试直接执行
                'executor': 'planner', // executor 失败，planner 尝试给出伪代码
                'reviewer': 'executor', // reviewer 失败，executor 自审
                'researcher': 'planner', // researcher 失败，planner 基于已有知识规划
            };
            const fallback = fallbackMap[agentId];
            if (fallback && !previousResults[fallback]) {
                return { action: 'fallback', reason: `${agentId} failed with ${errorCategory}, fallback to ${fallback}`, fallbackAgent: fallback };
            }
            // 无 fallback，降级模式
            return { action: 'degrade', reason: `${agentId} failed, no fallback available, entering degrade mode`, degradeMode: 'partial_output' };
        }
        // rate_limit/timeout 错误：可重试
        if (errorCategory === 'rate_limit' || errorCategory === 'timeout') {
            if (attempt < maxRetries - 1) {
                const delay = errorCategory === 'rate_limit' ? 5000 * Math.pow(2, attempt) : 2000 * Math.pow(2, attempt);
                return { action: 'retry', reason: `${errorCategory}, retrying in ${delay}ms`, retryDelay: delay };
            }
            // 重试耗尽，降级
            return { action: 'degrade', reason: `${errorCategory} retries exhausted, entering degrade mode`, degradeMode: 'best_effort' };
        }
        // 网络错误：重试一次，然后 fallback
        if (errorCategory === 'network') {
            if (attempt < 1) {
                return { action: 'retry', reason: 'network error, retrying', retryDelay: 3000 };
            }
            return { action: 'degrade', reason: 'network error retries exhausted', degradeMode: 'cached_response' };
        }
        // 未知错误：重试一次，然后 stop
        if (attempt < 1) {
            return { action: 'retry', reason: 'unknown error, retrying', retryDelay: 2000 };
        }
        return { action: 'stop', reason: 'unknown error retries exhausted' };
    }
    function generateCognitiveConstraint(agentId, taskDescription) {
        // 每个 agent 的约束不同，确保思维多样性
        const constraints = {
            planner: () => ({
                reasoningConstraint: `推理约束：你必须使用"逆向工程法"——从最终目标倒推，而不是从现状正向规划。先问"最终交付物是什么"，再问"需要什么前置条件"。`,
                perspectiveForcing: `视角强制：你是一个"完美主义者"PM，对每个子任务都要问"如果这个环节失败了怎么办"。不允许输出"看起来合理"的方案，必须输出"经过压力测试"的方案。`,
                entropyInjection: `熵注入：在拆解任务时，必须包含一个"反直觉子任务"——一个看起来与目标无关但实际上关键的步骤。当前任务哈希: ${hashString(taskDescription).slice(0, 8)}`,
            }),
            executor: () => ({
                reasoningConstraint: `推理约束：你必须使用"测试驱动法"——先写测试用例，再写实现代码。不允许"先写代码再补测试"。`,
                perspectiveForcing: `视角强制：你是一个"安全偏执狂"工程师，对每一行代码都要问"这里会被怎么攻击"。不允许输出"能用就行"的代码，必须输出"经过安全审查"的代码。`,
                entropyInjection: `熵注入：在实现时，必须使用一种"非主流"的实现方式——如果任务通常用 for 循环，你必须用递归或函数式。当前任务哈希: ${hashString(taskDescription).slice(0, 8)}`,
            }),
            reviewer: () => ({
                reasoningConstraint: `推理约束：你必须使用"红队思维"——假设代码中有 3 个隐藏 bug，你的任务是找到它们。不允许"看起来没问题"的评审。`,
                perspectiveForcing: `视角强制：你是一个"用户体验极端主义者"，从最差用户的角度评审代码。不允许输出"功能正确"的评审，必须输出"用户不会误用"的评审。`,
                entropyInjection: `熵注入：在评审时，必须提出一个"违反直觉的改进建议"——一个看起来会让代码变差但实际上会变好的建议。当前任务哈希: ${hashString(taskDescription).slice(0, 8)}`,
            }),
            researcher: () => ({
                reasoningConstraint: `推理约束：你必须使用"第一性原理"——不接受"业界标准"作为理由，必须从基本原理出发论证。`,
                perspectiveForcing: `视角强制：你是一个"技术怀疑论者"，对每个方案都要问"如果这个技术明天就过时了怎么办"。不允许输出"主流方案最好"的调研。`,
                entropyInjection: `熵注入：在调研中，必须包含一个"冷门方案"——一个不主流但在特定场景下更优的方案。当前任务哈希: ${hashString(taskDescription).slice(0, 8)}`,
            }),
        };
        const generator = constraints[agentId] || (() => ({
            reasoningConstraint: '推理约束：使用批判性思维，不接受表面答案。',
            perspectiveForcing: '视角强制：从反对者的角度审视你的输出。',
            entropyInjection: `熵注入：在输出中，必须包含一个"反直觉观点"。当前任务哈希: ${hashString(taskDescription).slice(0, 8)}`,
        }));
        return generator();
    }
    function hashString(str) {
        let hash = 0;
        for (let i = 0; i < str.length; i++) {
            const char = str.charCodeAt(i);
            hash = ((hash << 5) - hash) + char;
            hash = hash & hash;
        }
        return Math.abs(hash).toString(16);
    }
    // ═══════════════════════════════════════════
    // ① Agent Runtime
    // ═══════════════════════════════════════════
    // ── v2.3: Role Cognitive Lock + Cognitive Diversity ──
    // 每个 agent 严格的单一职责 + 认知约束 + 视角强制 + 熵注入
    // 不允许跨角色、不允许泛分析、不允许"解释型输出"、不允许思维太像
    const AGENT_DEFINITIONS = {
        planner: {
            role: 'planner',
            systemPrompt: `[ROLE LOCK — PLANNER ONLY]
你是任务拆解专家。唯一职责：将复杂任务分解为可执行子任务。

严格规则：
- 只输出任务拆解方案（JSON），不写代码、不做分析、不做决策
- 不输出"解释性文字"或"建议"
- 如果输入不是拆解请求 → {"status":"error","result":"","reasoning":"非拆解请求","next_action":"reject"}

[COGNITIVE CONSTRAINT — 逆向工程法]
你必须从最终目标倒推，不允许正向规划。先问"最终交付物是什么"，再问"需要什么前置条件"。

[PERSPECTIVE FORCING — 完美主义者PM]
对每个子任务都要问"如果这个环节失败了怎么办"。不允许输出"看起来合理"的方案。

[ENTROPY INJECTION]
拆解时必须包含一个"反直觉子任务"——看起来与目标无关但实际上关键的步骤。

输出格式（严格遵守）：
{"status":"success","result":"[子任务列表：name/description/assigned_to/dependencies]","reasoning":"[为什么这样拆解]","next_action":"[下一步]"}`,
            tools: ['decompose'],
            allowedOutput: 'task_decomposition_json',
        },
        executor: {
            role: 'executor',
            systemPrompt: `[ROLE LOCK — EXECUTOR ONLY]
你是代码执行专家。唯一职责：根据 Planner 的拆解方案编写可运行代码。

严格规则：
- 只输出代码（JSON，result字段=完整代码），不做分析、不写调研、不做决策
- 不输出"解释性文字"或"建议" — result字段只能是代码
- 如果输入不是代码请求 → {"status":"error","result":"","reasoning":"非代码请求","next_action":"reject"}

[CRITICAL — 必须引用上游输出]
你的代码 MUST 包含 Planner 拆解方案中的所有子任务。不允许忽略任何子任务。
在你的 reasoning 字段中，必须列出你引用了 Planner 的哪些子任务。

[COGNITIVE CONSTRAINT — 测试驱动法]
必须先写测试用例，再写实现代码。不允许"先写代码再补测试"。

[PERSPECTIVE FORCING — 安全偏执狂]
对每行代码都要问"这里会被怎么攻击"。不允许输出"能用就行"的代码。

[ENTROPY INJECTION]
实现时必须使用一种"非主流"方式——如果通常用 for 循环，你必须用递归或函数式。

输出格式（严格遵守）：
{"status":"success","result":"[完整可运行代码，带注释]","reasoning":"[引用了哪些子任务，实现思路不超过50字]","next_action":"[代码已完成，等待审查]"}`,
            tools: ['code_exec', 'test'],
            allowedOutput: 'executable_code_json',
        },
        reviewer: {
            role: 'reviewer',
            systemPrompt: `[ROLE LOCK — REVIEWER ONLY]
你是代码评审专家。唯一职责：评审代码质量、安全性、完整性。

严格规则：
- 只输出评审结果（JSON），不写代码、不改代码、不做分析
- 不输出"建议性代码" — 只能指出问题
- 如果输入不是评审请求 → {"status":"error","result":"","reasoning":"非评审请求","next_action":"reject"}

[CRITICAL — 必须验证代码是否覆盖了所有子任务]
你的评审 MUST 检查代码是否实现了 Planner 拆解方案中的所有子任务。
在你的 reasoning 字段中，必须列出你检查了哪些子任务，哪些被覆盖，哪些缺失。

[COGNITIVE CONSTRAINT — 红队思维]
假设代码中有 3 个隐藏 bug，你的任务是找到它们。不允许"看起来没问题"的评审。

[PERSPECTIVE FORCING — 用户体验极端主义者]
从最差用户的角度评审。不允许输出"功能正确"，必须输出"用户不会误用"。

[ENTROPY INJECTION]
评审时必须提出一个"违反直觉的改进建议"——看起来会让代码变差但实际上会变好的建议。

输出格式（严格遵守）：
{"status":"success","result":"[pass/fail, 问题列表，子任务覆盖情况]","reasoning":"[评审依据，检查了哪些子任务]","next_action":"[通过则标记完成，不通过则返回修改]"}`,
            tools: ['code_review', 'evaluate'],
            allowedOutput: 'review_result_json',
        },
        researcher: {
            role: 'researcher',
            systemPrompt: `[ROLE LOCK — RESEARCHER ONLY]
你是技术调研专家。唯一职责：调研现有方案、技术选型、最佳实践。

严格规则：
- 只输出调研报告（JSON），不写代码、不做决策、不评审
- 不输出"代码示例" — 只能描述方案
- 如果输入不是调研请求 → {"status":"error","result":"","reasoning":"非调研请求","next_action":"reject"}

[CRITICAL — 必须针对原始任务调研]
你的调研 MUST 直接针对原始任务的需求，不允许泛泛而谈。
在你的 reasoning 字段中，必须说明你的调研如何直接服务于原始任务。

[COGNITIVE CONSTRAINT — 第一性原理]
不接受"业界标准"作为理由，必须从基本原理出发论证。

[PERSPECTIVE FORCING — 技术怀疑论者]
对每个方案都要问"如果这个技术明天就过时了怎么办"。不允许输出"主流方案最好"。

[ENTROPY INJECTION]
调研中必须包含一个"冷门方案"——不主流但在特定场景下更优的方案。

输出格式（严格遵守）：
{"status":"success","result":"[现有方案对比、优缺点、推荐方案]","reasoning":"[调研方法论，如何服务于原始任务]","next_action":"[调研完成，等待执行]"}`,
            tools: ['web_search', 'analyze'],
            allowedOutput: 'research_report_json',
        },
    };
    // ── v2.1: Strict Output Schema ──
    const OUTPUT_SCHEMA = `{
  "status": "success" | "error" | "timeout",
  "result": "string (your main output — REQUIRED, non-empty)",
  "reasoning": "string (your thinking process)",
  "next_action": "string (suggested next step)"
}`;
    function classifyError(httpCode, message) {
        const msg = message.toLowerCase();
        if (httpCode === 429 || msg.includes('rate limit') || msg.includes('too many requests')) {
            return { category: 'rate_limit', httpCode, message, retryable: true, retryDelay: 5000 };
        }
        if (httpCode === 401 || httpCode === 403 || msg.includes('auth') || msg.includes('unauthorized') || msg.includes('forbidden') || msg.includes('insufficient credits')) {
            return { category: 'auth', httpCode, message, retryable: false, retryDelay: 0 };
        }
        if (httpCode === 408 || httpCode === 504 || msg.includes('timeout') || msg.includes('timed out')) {
            return { category: 'timeout', httpCode, message, retryable: true, retryDelay: 3000 };
        }
        if (httpCode >= 500 || msg.includes('internal') || msg.includes('server error') || msg.includes('bad gateway') || msg.includes('service unavailable')) {
            return { category: 'network', httpCode, message, retryable: true, retryDelay: 2000 };
        }
        if (httpCode === 400 && (msg.includes('no input') || msg.includes('invalid_prompt') || msg.includes('format'))) {
            return { category: 'format', httpCode, message, retryable: false, retryDelay: 0 };
        }
        if (httpCode >= 400) {
            return { category: 'network', httpCode, message, retryable: httpCode >= 500, retryDelay: 2000 };
        }
        return { category: 'unknown', httpCode, message, retryable: true, retryDelay: 2000 };
    }
    async function callAgent(agentId, input, // v2.2: 独立 JSON 输入，不再共享 context
    apiKey, provider, model, baseUrl) {
        const start = Date.now();
        const def = AGENT_DEFINITIONS[agentId];
        if (!def) {
            return { agentId, status: 'error', result: '', reasoning: '', nextAction: '', tokensUsed: 0, latencyMs: 0, error: `Unknown agent: ${agentId}` };
        }
        // ── v2.2: 每个 agent 的 prompt 完全独立，不共享任何 context ──
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
        ].join('\n');
        const endpoint = getEndpoint(provider, baseUrl);
        const isAnthropic = provider === 'anthropic';
        const isResponsesApi = (baseUrl || '').includes('/responses');
        const headers = { 'Content-Type': 'application/json' };
        let payload;
        if (isAnthropic) {
            headers['x-api-key'] = apiKey;
            headers['anthropic-version'] = '2023-06-01';
            payload = { model, system: def.systemPrompt, messages: [{ role: 'user', content: prompt }], max_tokens: 4096, stream: false };
        }
        else if (isResponsesApi) {
            headers['Authorization'] = `Bearer ${apiKey}`;
            payload = { model, input: prompt, stream: false, temperature: 0.7, max_tokens: 4096 };
        }
        else {
            headers['Authorization'] = `Bearer ${apiKey}`;
            payload = {
                model,
                messages: [
                    { role: 'system', content: def.systemPrompt },
                    { role: 'user', content: prompt },
                ],
                stream: false,
                temperature: 0.7,
                max_tokens: 4096,
            };
        }
        // ── v2.1: Smart retry with error classification ──
        const maxRetries = 3;
        let lastError = null;
        for (let attempt = 0; attempt < maxRetries; attempt++) {
            try {
                const res = await fetch(endpoint, { method: 'POST', headers, body: JSON.stringify(payload) });
                if (!res.ok) {
                    const text = await res.text();
                    const classified = classifyError(res.status, text);
                    lastError = classified;
                    console.log(`[${agentId}] attempt ${attempt + 1}/${maxRetries} — ${classified.category}(${classified.httpCode}): ${text.slice(0, 100)}`);
                    if (!classified.retryable || attempt >= maxRetries - 1) {
                        return { agentId, status: 'error', result: '', reasoning: '', nextAction: '', tokensUsed: 0, latencyMs: Date.now() - start, error: `${classified.category}(${classified.httpCode}): ${text.slice(0, 200)}`, errorCategory: classified.category, retryCount: attempt };
                    }
                    // Exponential backoff with category-aware delay
                    const delay = classified.retryDelay * Math.pow(2, attempt);
                    await sleep(delay);
                    continue;
                }
                const r = await res.json();
                let full = '';
                if (r.choices?.[0]?.message?.content) {
                    full = r.choices[0].message.content;
                }
                else if (r.output?.[0]?.content?.[0]?.text) {
                    full = r.output[0].content[0].text;
                }
                // ── v2.1: Strict JSON parsing with multi-strategy fallback ──
                const parsed = parseAgentJsonStrict(full);
                return {
                    agentId,
                    status: parsed.status,
                    result: parsed.result,
                    reasoning: parsed.reasoning,
                    nextAction: parsed.nextAction,
                    tokensUsed: (prompt.length + full.length) / 4,
                    latencyMs: Date.now() - start,
                    error: parsed.status === 'error' ? 'Agent reported error' : '',
                    retryCount: attempt,
                };
            }
            catch (e) {
                const classified = classifyError(0, e.message);
                lastError = classified;
                console.log(`[${agentId}] attempt ${attempt + 1}/${maxRetries} — ${classified.category}: ${e.message}`);
                if (!classified.retryable || attempt >= maxRetries - 1) {
                    return { agentId, status: 'error', result: '', reasoning: '', nextAction: '', tokensUsed: 0, latencyMs: Date.now() - start, error: `${classified.category}: ${e.message}`, errorCategory: classified.category, retryCount: attempt };
                }
                await sleep(classified.retryDelay * Math.pow(2, attempt));
            }
        }
        return { agentId, status: 'error', result: '', reasoning: '', nextAction: '', tokensUsed: 0, latencyMs: Date.now() - start, error: lastError ? `${lastError.category}: ${lastError.message}` : 'Max retries exceeded', errorCategory: lastError?.category, retryCount: maxRetries };
    }
    // ── v2.1: Strict JSON parser — 5 strategies ──
    function parseAgentJsonStrict(text) {
        if (!text || !text.trim()) {
            return { status: 'error', result: '', reasoning: 'Empty response from LLM', nextAction: 'retry' };
        }
        // Strategy 1: Direct parse
        try {
            const obj = JSON.parse(text);
            if (obj.status && obj.result)
                return normalizeResult(obj);
        }
        catch { }
        // Strategy 2: Strip markdown fences
        let cleaned = text.trim();
        if (cleaned.startsWith('```')) {
            cleaned = cleaned.split('\n').filter(l => !l.trim().startsWith('```')).join('\n').trim();
        }
        try {
            const obj = JSON.parse(cleaned);
            if (obj.status && obj.result)
                return normalizeResult(obj);
        }
        catch { }
        // Strategy 3: Extract first JSON object
        const start = cleaned.indexOf('{');
        const end = cleaned.lastIndexOf('}');
        if (start >= 0 && end > start) {
            try {
                const obj = JSON.parse(cleaned.slice(start, end + 1));
                if (obj.status)
                    return normalizeResult(obj);
            }
            catch { }
        }
        // Strategy 4: Try to find JSON with regex for nested braces
        const jsonMatch = cleaned.match(/\{[^{}]*"status"[^{}]*\}/);
        if (jsonMatch) {
            try {
                const obj = JSON.parse(jsonMatch[0]);
                return normalizeResult(obj);
            }
            catch { }
        }
        // Strategy 5: Fallback — treat entire text as result
        console.log('[parseAgentJson] All JSON parse strategies failed, using raw text as fallback');
        return { status: 'success', result: text, reasoning: '', nextAction: 'continue' };
    }
    function normalizeResult(obj) {
        return {
            status: obj.status || 'success',
            result: obj.result || obj.output || obj.text || obj.content || '',
            reasoning: obj.reasoning || obj.thought || obj.explanation || '',
            nextAction: obj.next_action || obj.nextAction || obj.next || 'continue',
        };
    }
    class DAGEngine {
        nodes = new Map();
        edges = [];
        results = new Map();
        _killed = false;
        _degradeMode = false; // v2.3: 降级模式
        addNode(node) { this.nodes.set(node.id, node); }
        addEdge(from, to) { this.edges.push([from, to]); }
        // ── v2.3: 构建每个 agent 的独立输入（含认知约束）──
        _buildAgentInput(node, ctx, previousOutput) {
            const def = AGENT_DEFINITIONS[node.agentId];
            let roleContext = '';
            let expectedOutput = '';
            switch (node.agentId) {
                case 'planner':
                    roleContext = `原始任务：${ctx.originalTask}`;
                    expectedOutput = '任务拆解方案（JSON）';
                    break;
                case 'executor':
                    roleContext = `上游 Planner 的拆解方案：${previousOutput}`;
                    expectedOutput = '可运行代码（JSON）';
                    break;
                case 'researcher':
                    roleContext = `原始任务：${ctx.originalTask}`;
                    expectedOutput = '调研报告（JSON）';
                    break;
                case 'reviewer':
                    roleContext = `待评审的代码：${previousOutput.slice(0, 2000)}`;
                    expectedOutput = '评审结果（JSON）';
                    break;
                default:
                    roleContext = `任务：${node.taskDescription}`;
                    expectedOutput = 'JSON 格式输出';
            }
            return {
                task: node.taskDescription,
                roleContext,
                expectedOutput,
            };
        }
        async execute(ctx) {
            this.results = new Map();
            this._killed = false;
            this._degradeMode = false;
            const { adj, inDeg } = this._buildGraph();
            const layers = this._topoLayers(adj, inDeg);
            for (const layer of layers) {
                if (this._killed) {
                    for (const nodeId of layer) {
                        this.results.set(nodeId, { nodeId, agentId: this.nodes.get(nodeId).agentId, status: 'killed', result: '', error: 'DAG killed by upstream failure', latencyMs: 0, retries: 0 });
                    }
                    continue;
                }
                const tasks = layer.map(nodeId => {
                    const node = this.nodes.get(nodeId);
                    const depsOk = node.dependencies.every(d => this.results.get(d)?.status === 'success');
                    if (!depsOk) {
                        this.results.set(nodeId, { nodeId, agentId: node.agentId, status: 'skipped', result: '', error: 'Dependencies not met', latencyMs: 0, retries: 0 });
                        return Promise.resolve();
                    }
                    // v2.3: 获取上游输出，构建独立输入
                    const previousOutput = node.dependencies.length > 0
                        ? (this.results.get(node.dependencies[node.dependencies.length - 1])?.result || '')
                        : '';
                    const agentInput = this._buildAgentInput(node, ctx, previousOutput);
                    return this._execNode(node, agentInput, ctx, previousOutput);
                });
                await Promise.all(tasks);
            }
            return this.results;
        }
        // ── v2.3: 执行节点 + 信息流验证 + 智能恢复 ──
        async _execNode(node, input, ctx, previousOutput) {
            const start = Date.now();
            let lastRecovery = null;
            for (let attempt = 0; attempt < node.retryCount; attempt++) {
                // v2.3: 注入认知约束
                const cognitive = generateCognitiveConstraint(node.agentId, input.task);
                const enhancedInput = {
                    ...input,
                    task: input.task + '\n\n' + cognitive.reasoningConstraint + '\n' + cognitive.perspectiveForcing + '\n' + cognitive.entropyInjection,
                };
                const r = await callAgent(node.agentId, enhancedInput, ctx.apiKey, ctx.provider, ctx.model, ctx.baseUrl);
                // ── v2.3: Information Flow Validation ──
                let flowValidation;
                if (r.status === 'success' && previousOutput) {
                    flowValidation = validateInformationFlow(r.result, previousOutput, node.agentId, r.reasoning);
                    if (!flowValidation.validationPassed) {
                        console.log(`[FLOW VALIDATION FAILED] ${node.agentId}(${node.id}): ${flowValidation.failureReason}`);
                        // 信息流验证失败 = 假协作，立即 kill
                        this.results.set(node.id, {
                            nodeId: node.id, agentId: node.agentId, status: 'flow_validation_failed',
                            result: r.result, error: flowValidation.failureReason,
                            latencyMs: Date.now() - start, retries: attempt, flowValidation,
                        });
                        this._killed = true;
                        return;
                    }
                }
                this.results.set(node.id, {
                    nodeId: node.id, agentId: node.agentId, status: r.status, result: r.result,
                    error: r.error, errorCategory: r.errorCategory, latencyMs: r.latencyMs,
                    retries: attempt, flowValidation,
                });
                if (r.status === 'success')
                    return;
                // ── v2.3: Recovery System — 智能恢复决策 ──
                const recovery = decideRecovery(r.errorCategory || 'unknown', attempt, node.retryCount, node.agentId, Object.fromEntries(this.results.entries()));
                lastRecovery = recovery;
                console.log(`[RECOVERY] ${node.agentId}(${node.id}): ${recovery.action} — ${recovery.reason}`);
                this.results.set(node.id, {
                    ...this.results.get(node.id),
                    recoveryAction: recovery.action,
                });
                switch (recovery.action) {
                    case 'retry':
                        await sleep(recovery.retryDelay || 2000);
                        continue;
                    case 'fallback':
                        // 切换到 fallback agent
                        if (recovery.fallbackAgent) {
                            console.log(`[FALLBACK] ${node.agentId} → ${recovery.fallbackAgent}`);
                            // 用 fallback agent 重新执行
                            const fallbackInput = {
                                task: `[FALLBACK from ${node.agentId}] ${input.task}`,
                                roleContext: input.roleContext,
                                expectedOutput: input.expectedOutput,
                            };
                            const fallbackResult = await callAgent(recovery.fallbackAgent, fallbackInput, ctx.apiKey, ctx.provider, ctx.model, ctx.baseUrl);
                            this.results.set(node.id, {
                                nodeId: node.id, agentId: recovery.fallbackAgent, status: fallbackResult.status,
                                result: fallbackResult.result, error: fallbackResult.error,
                                latencyMs: Date.now() - start, retries: attempt,
                                flowValidation: fallbackResult.status === 'success' && previousOutput
                                    ? validateInformationFlow(fallbackResult.result, previousOutput, recovery.fallbackAgent, fallbackResult.reasoning)
                                    : undefined,
                            });
                            if (fallbackResult.status === 'success')
                                return;
                        }
                        // fallback 也失败，继续重试
                        await sleep(2000);
                        continue;
                    case 'degrade':
                        // 降级模式：输出部分结果
                        this._degradeMode = true;
                        this.results.set(node.id, {
                            nodeId: node.id, agentId: node.agentId, status: 'degraded',
                            result: r.result || '[降级模式：部分输出]', error: recovery.reason,
                            latencyMs: Date.now() - start, retries: attempt,
                        });
                        return; // 降级后不再重试
                    case 'stop':
                        this._killed = true;
                        return;
                }
            }
        }
        _buildGraph() {
            const adj = new Map();
            const inDeg = new Map();
            for (const id of this.nodes.keys()) {
                inDeg.set(id, 0);
                adj.set(id, []);
            }
            for (const [from, to] of this.edges) {
                if (this.nodes.has(from) && this.nodes.has(to)) {
                    adj.get(from).push(to);
                    inDeg.set(to, (inDeg.get(to) || 0) + 1);
                }
            }
            return { adj, inDeg };
        }
        _topoLayers(adj, inDeg) {
            const deg = new Map(inDeg);
            let queue = [...deg.entries()].filter(([, d]) => d === 0).map(([n]) => n);
            const layers = [];
            while (queue.length > 0) {
                layers.push([...queue]);
                const next = [];
                for (const id of queue) {
                    for (const nb of adj.get(id) || []) {
                        deg.set(nb, deg.get(nb) - 1);
                        if (deg.get(nb) === 0)
                            next.push(nb);
                    }
                }
                queue = next;
            }
            return layers;
        }
    }
    function classifyComplexity(task) {
        const text = task.toLowerCase().trim();
        const reasons = [];
        let simpleScore = 0, standardScore = 0, complexScore = 0;
        // Short query → SIMPLE
        const words = text.split(/\s+/);
        if (words.length <= 5 && task.length <= 30) {
            reasons.push(`Short query (${words.length} words)`);
            return { level: 'SIMPLE', confidence: 0.9, reasons };
        }
        // Simple keywords
        const simpleKws = ['什么', '定义', '解释', '意思', '时间', '日期', '天气', '翻译', '拼写', '读音', '多少', '哪个', '是谁', 'what is', 'define', 'explain', 'meaning', 'time', 'date', 'translate', 'spell', 'how many', 'who is', 'trivial', 'simple', 'quick'];
        for (const kw of simpleKws) {
            if (text.includes(kw)) {
                simpleScore += 2;
                reasons.push(`Simple kw: ${kw}`);
            }
        }
        // Standard keywords
        const stdKws = ['写', '创建', '实现', '分析', '优化', '重构', '调试', '计算', '排序', '搜索', '过滤', '解析', '验证', 'write', 'create', 'implement', 'analyze', 'optimize', 'refactor', 'debug', 'calculate', 'sort', 'search', 'filter', 'parse', 'validate', 'test', 'review', 'function', 'class', 'module', 'script'];
        for (const kw of stdKws) {
            if (text.includes(kw)) {
                standardScore += 1;
                reasons.push(`Standard kw: ${kw}`);
            }
        }
        // Complex keywords
        const complexKws = ['设计', '架构', '系统', '平台', '框架', '完整', '全栈', '部署', '集成', '迁移', '构建', '搭建', '多步骤', '工作流', 'pipeline', 'workflow', 'multi-step', 'microservice', 'orchestration', 'end-to-end', 'full-stack'];
        for (const kw of complexKws) {
            if (text.includes(kw)) {
                complexScore += 2;
                reasons.push(`Complex kw: ${kw}`);
            }
        }
        // Complex patterns
        const complexPatterns = [/首先.*然后|第一步.*第二步|先.*再.*最后/, /(and\s+then|then\s+\w+|step\s+\d+|first.*then.*finally)/i, /(multiple|several|various)\s+(steps?|components?|services?)/i];
        for (const p of complexPatterns) {
            if (p.test(text)) {
                complexScore += 3;
                reasons.push(`Complex pattern: ${p.source.slice(0, 40)}`);
            }
        }
        // Structural
        const sentences = text.split(/[.!?。！？]+/).filter(Boolean);
        if (sentences.length >= 3) {
            standardScore += 1;
            reasons.push(`Multiple sentences (${sentences.length})`);
        }
        if (words.length > 50) {
            complexScore += 1;
            reasons.push(`Long task (${words.length} words)`);
        }
        if (/```|def |class |import |from |function |const |let |var /.test(text)) {
            standardScore += 2;
            reasons.push('Contains code refs');
        }
        if (Math.max(simpleScore, standardScore, complexScore) === 0) {
            reasons.push('No signals → default STANDARD');
            return { level: 'STANDARD', confidence: 0.5, reasons };
        }
        const scores = { SIMPLE: simpleScore, STANDARD: standardScore, COMPLEX: complexScore };
        const best = (Object.entries(scores).sort((a, b) => b[1] - a[1])[0][0]);
        const total = simpleScore + standardScore + complexScore;
        let confidence = scores[best] / total;
        const sorted = Object.values(scores).sort((a, b) => b - a);
        if (sorted[0] > 2 * (sorted[1] || 0))
            confidence = Math.min(confidence + 0.15, 1.0);
        reasons.push(`Scores: S=${simpleScore} ST=${standardScore} C=${complexScore}`);
        return { level: best, confidence: Math.round(confidence * 100) / 100, reasons };
    }
    // ── v6: Diversity Check ──
    function checkDiversity(ctx) {
        const outputs = {};
        if (ctx.plan?.strategy) outputs.planner = ctx.plan.strategy;
        if (ctx.executionResult?.result) outputs.executor = ctx.executionResult.result;
        if (ctx.reviewResult?.raw || ctx.reviewResult?.reason) outputs.reviewer = ctx.reviewResult.raw || ctx.reviewResult.reason;
        const agentIds = Object.keys(outputs);
        if (agentIds.length < 2) {
            return { overallDiversityScore: 1, homogenizationDetected: false, pairwiseResults: [], consensusViolations: [] };
        }
        let maxSim = 0;
        const pairwise = [];
        const consensusViolations = [];
        for (let i = 0; i < agentIds.length; i++) {
            for (let j = i + 1; j < agentIds.length; j++) {
                const aId = agentIds[i];
                const bId = agentIds[j];
                const sim = computeSimilarity(outputs[aId], outputs[bId]);
                if (sim > maxSim) maxSim = sim;
                pairwise.push({ agentA: aId, agentB: bId, similarity: sim });
                // Check consensus patterns
                const consensusPatterns = ['同意', '正如', 'similarly', 'as mentioned', 'consistent with', 'rephrase'];
                const hasConsensus = consensusPatterns.some(p => outputs[aId].toLowerCase().includes(p) || outputs[bId].toLowerCase().includes(p));
                if (hasConsensus) consensusViolations.push(`${aId}/${bId}`);
            }
        }
        const homogenized = maxSim > 0.75 || consensusViolations.length > 0;
        return {
            overallDiversityScore: Math.round((1 - maxSim) * 100) / 100,
            homogenizationDetected: homogenized,
            pairwiseResults: pairwise,
            consensusViolations,
        };
    }
    function computeSimilarity(textA, textB) {
        if (!textA || !textB) return 0;
        const tokenize = (t) => new Set(t.toLowerCase().split(/[\s,;。，；、.]+/).filter(w => w.length > 2));
        const setA = tokenize(textA);
        const setB = tokenize(textB);
        if (setA.size === 0 && setB.size === 0) return 1;
        if (setA.size === 0 || setB.size === 0) return 0;
        const intersection = new Set([...setA].filter(x => setB.has(x)));
        const union = new Set([...setA, ...setB]);
        const jaccard = intersection.size / union.size;
        // Beginning overlap
        const startA = textA.slice(0, 80).toLowerCase().split(/\s+/).filter(Boolean);
        const startB = textB.slice(0, 80).toLowerCase().split(/\s+/).filter(Boolean);
        const beginSim = startA.filter(w => startB.includes(w)).length / Math.max(startA.length, 1);
        return 0.7 * jaccard + 0.3 * beginSim;
    }
    async function runAdaptiveOrchestrator(task, apiKey, provider, model, baseUrl, forceMode, db = null) {
        const traceId = crypto.randomUUID().slice(0, 12);
        const trace = [];
        const record = (step, agent, inputData, outputData, latencyMs, tokens = 0) => {
            trace.push({ traceId, taskId: ctx.taskId, step, agent, inputData, outputData, latencyMs, tokens, ts: Date.now() });
        };
        // ── Collaboration: emit event helper ──
        const emitEvent = async (eventType, source, data) => {
            if (!db) return;
            try {
                const id = crypto.randomUUID().slice(0, 16);
                await db.prepare(
                    'INSERT INTO collaboration_events (id, event_type, source, task_id, data, timestamp) VALUES (?, ?, ?, ?, ?, ?)'
                ).bind(id, eventType, source, ctx.taskId, JSON.stringify(data), Date.now() / 1000).run();
            } catch { /* table may not exist yet — silent */ }
        };
        const writeContext = async (key, value, agentId) => {
            if (!db) return;
            try {
                const id = crypto.randomUUID().slice(0, 16);
                await db.prepare(
                    'INSERT INTO collaboration_context (id, task_id, key, value, agent_id, timestamp) VALUES (?, ?, ?, ?, ?, ?)'
                ).bind(id, ctx.taskId, key, JSON.stringify(value ?? null), agentId || 'system', Date.now() / 1000).run();
            } catch { /* table may not exist yet — silent */ }
        };
        // ── Classify ──
        const classification = classifyComplexity(task);
        const mode = forceMode || classification.level;
        const ctx = {
            taskId: crypto.randomUUID().slice(0, 12),
            userInput: task,
            mode,
            complexity: classification,
            state: 'CLASSIFY',
            plan: {},
            executionResult: {},
            reviewResult: {},
            finalResult: '',
            llmCalls: 0,
            skippedStages: [],
            error: '',
            diversityReport: {},
        };
        // ── Collaboration: task created ──
        await emitEvent('task_created', 'user', { task, mode });
        await writeContext('task_input', task, 'system');
        await writeContext('mode', mode, 'system');
        record('CLASSIFY', 'classifier', { task }, { mode, complexity: classification, reasons: classification.reasons }, 0);
        ctx.state = mode === 'SIMPLE' ? 'SIMPLE_EXEC' : mode === 'STANDARD' ? 'STD_EXEC' : 'PLAN';
        // ── SIMPLE: executor only ──
        if (mode === 'SIMPLE') {
            ctx.skippedStages = ['planner', 'reviewer', 'validation_gate'];
            const start = Date.now();
            const input = { task, roleContext: `任务：${task}`, expectedOutput: 'JSON 输出' };
            const r = await callAgent('executor', input, apiKey, provider, model, baseUrl);
            ctx.llmCalls++;
            record('SIMPLE_EXEC', 'executor', { task }, { result: r.result.slice(0, 300) }, Date.now() - start, r.tokensUsed);
            if (r.status === 'success') {
                ctx.executionResult = { result: r.result, reasoning: r.reasoning };
                ctx.finalResult = r.result;
                ctx.state = 'DONE';
                await emitEvent('agent_completed', 'agent:executor', { result: r.result?.slice(0, 200) });
                await writeContext('execution_result', r.result, 'executor');
            }
            else {
                ctx.error = r.error || 'Executor failed';
                ctx.state = 'FAILED';
                await emitEvent('error', 'agent:executor', { error: ctx.error });
            }
            await emitEvent('task_updated', 'system:fsm', { state: ctx.state, mode: 'SIMPLE' });
            record('COMPLETE', '', {}, { mode: 'SIMPLE', llmCalls: ctx.llmCalls, skipped: ctx.skippedStages }, 0);
            return { context: ctx, trace };
        }
        // ── STANDARD: executor + validation ──
        if (mode === 'STANDARD') {
            ctx.skippedStages = ['planner', 'reviewer'];
            const start = Date.now();
            const input = { task, roleContext: `任务：${task}`, expectedOutput: 'JSON 输出' };
            const r = await callAgent('executor', input, apiKey, provider, model, baseUrl);
            ctx.llmCalls++;
            record('STD_EXEC', 'executor', { task }, { result: r.result.slice(0, 300) }, Date.now() - start, r.tokensUsed);
            if (r.status === 'success') {
                ctx.executionResult = { result: r.result, reasoning: r.reasoning };
                ctx.finalResult = r.result;
                ctx.state = 'DONE';
                await emitEvent('agent_completed', 'agent:executor', { result: r.result?.slice(0, 200) });
                await writeContext('execution_result', r.result, 'executor');
            }
            else {
                ctx.error = r.error || 'Executor failed';
                ctx.state = 'FAILED';
                await emitEvent('error', 'agent:executor', { error: ctx.error });
            }
            await emitEvent('task_updated', 'system:fsm', { state: ctx.state, mode: 'STANDARD' });
            record('COMPLETE', '', {}, { mode: 'STANDARD', llmCalls: ctx.llmCalls, skipped: ctx.skippedStages }, 0);
            return { context: ctx, trace };
        }
        // ── COMPLEX: planner → executor → reviewer ──
        // PLAN
        const planStart = Date.now();
        const planInput = { task: `制定执行计划：${task}`, roleContext: `原始任务：${task}`, expectedOutput: '任务拆解方案（JSON）' };
        const planResult = await callAgent('planner', planInput, apiKey, provider, model, baseUrl);
        ctx.llmCalls++;
        ctx.plan = { strategy: planResult.result, reasoning: planResult.reasoning };
        record('PLAN', 'planner', { task }, ctx.plan, Date.now() - planStart, planResult.tokensUsed);
        await emitEvent('agent_completed', 'agent:planner', { result: planResult.result?.slice(0, 200) });
        await writeContext('plan', planResult.result, 'planner');
        ctx.state = 'EXECUTE';
        await emitEvent('state_transition', 'system:fsm', { from: 'PLAN', to: 'EXECUTE' });
        // EXECUTE (use plan result as context)
        const execStart = Date.now();
        const execInput = {
            task: `根据计划执行：${task}`,
            roleContext: `上游 Planner 的拆解方案：${planResult.result}`,
            expectedOutput: '可运行代码（JSON）',
        };
        const execResult = await callAgent('executor', execInput, apiKey, provider, model, baseUrl);
        ctx.llmCalls++;
        ctx.executionResult = { result: execResult.result, reasoning: execResult.reasoning };
        ctx.finalResult = execResult.result;
        record('EXECUTE', 'executor', { plan: ctx.plan }, { result: execResult.result.slice(0, 300) }, Date.now() - execStart, execResult.tokensUsed);
        await emitEvent('agent_completed', 'agent:executor', { result: execResult.result?.slice(0, 200) });
        await writeContext('execution_result', execResult.result, 'executor');
        ctx.state = 'REVIEW';
        await emitEvent('state_transition', 'system:fsm', { from: 'EXECUTE', to: 'REVIEW' });
        // REVIEW
        const reviewStart = Date.now();
        const reviewInput = {
            task: `评审以下执行结果：\n\n任务：${task}\n\n结果：${execResult.result.slice(0, 800)}`,
            roleContext: `待评审的代码：${execResult.result.slice(0, 500)}`,
            expectedOutput: '评审结果（JSON）：pass/fail + issues + coverage',
        };
        const reviewResult = await callAgent('reviewer', reviewInput, apiKey, provider, model, baseUrl);
        ctx.llmCalls++;
        ctx.reviewResult = parseReviewEnhanced(reviewResult.result);
        record('REVIEW', 'reviewer', { resultPreview: execResult.result.slice(0, 200) }, ctx.reviewResult, Date.now() - reviewStart, reviewResult.tokensUsed);
        await emitEvent('agent_completed', 'agent:reviewer', { pass: ctx.reviewResult.pass });
        await writeContext('review_result', reviewResult.result, 'reviewer');
        // ── v6: Diversity Check ──
        const diversityReport = checkDiversity(ctx);
        ctx.diversityReport = diversityReport;
        ctx.state = 'DONE';
        await emitEvent('task_updated', 'system:fsm', { state: 'DONE', mode: 'COMPLEX' });
        await writeContext('final_result', ctx.finalResult, 'system');
        record('COMPLETE', '', {}, { mode: 'COMPLEX', llmCalls: ctx.llmCalls, diversityScore: diversityReport.overallDiversityScore, homogenized: diversityReport.homogenizationDetected }, 0);
        return { context: ctx, trace };
    }

    // ── v2.1: Enhanced review parser with failure categorization ──
    function parseReviewEnhanced(raw) {
        const fallback = { pass: false, reason: raw.slice(0, 200), suggestions: '', failureCategory: 'format_error', rootCause: 'Failed to parse review JSON', severity: 'major' };
        if (!raw || !raw.trim())
            return fallback;
        try {
            let t = raw.trim();
            if (t.startsWith('```'))
                t = t.split('\n').filter(l => !l.trim().startsWith('```')).join('\n').trim();
            const s = t.indexOf('{'), e = t.lastIndexOf('}');
            if (s >= 0 && e > s) {
                const obj = JSON.parse(t.slice(s, e + 1));
                return {
                    pass: obj.pass === true,
                    reason: obj.reason || '',
                    suggestions: obj.suggestions || '',
                    failureCategory: obj.failure_category || 'none',
                    rootCause: obj.root_cause || '',
                    severity: obj.severity || 'none',
                };
            }
        }
        catch { }
        // Fallback: check for pass keywords
        const isPass = /通过|pass|true|合格|good/i.test(raw) && !/fail|失败|不通过/i.test(raw);
        return { ...fallback, pass: isPass, failureCategory: isPass ? 'none' : 'format_error' };
    }
    // ═══════════════════════════════════════════
    // ④ Memory System (4-Layer, D1-backed)
    // ═══════════════════════════════════════════
    async function loadContext(db, taskId) {
        return `## Long-Term Memory\nNo prior context yet.\n\n## Recent Context\nNo prior discussion yet.\n\n## Relevant Memories\nNone yet.`;
    }
    async function loadHistory(db, taskId) {
        try {
            const { results } = await db.prepare('SELECT role, content FROM messages WHERE channel_id = ? ORDER BY created_at LIMIT 6').bind(taskId).all();
            if (!results || results.length === 0)
                return '[RECENT CONTEXT]\nNo recent messages.';
            const lines = results.map((m) => `${m.role === 'user' ? 'User' : 'Assistant'}: ${m.content.slice(0, 200)}`);
            return '[RECENT CONTEXT]\n' + lines.join('\n');
        }
        catch {
            return '[RECENT CONTEXT]\nNo recent messages.';
        }
    }

    // ═══════════════════════════════════════════
    // Helpers
    // ═══════════════════════════════════════════
    function genUUID() { return crypto.randomUUID(); }
    function utcNow() { return new Date().toISOString(); }
    function json(data, status = 200, headers) {
        const h = { 'Content-Type': 'application/json', ...headers };
        return new Response(JSON.stringify(data), { status, headers: h });
    }
    function error(message, status = 400) {
        return new Response(JSON.stringify({ detail: message }), { status, headers: { 'Content-Type': 'application/json' } });
    }
    function setCors(response) {
        response.headers.set('Access-Control-Allow-Origin', '*');
        response.headers.set('Access-Control-Allow-Methods', 'GET, POST, PUT, PATCH, DELETE, OPTIONS');
        response.headers.set('Access-Control-Allow-Headers', 'Content-Type');
        return response;
    }
    function corsResponse() {
        return new Response(null, { status: 204, headers: { 'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Methods': 'GET, POST, PUT, PATCH, DELETE, OPTIONS', 'Access-Control-Allow-Headers': 'Content-Type', 'Access-Control-Max-Age': '86400' } });
    }
    function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }
    const PROVIDER_ENDPOINTS = {
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
    };
    function getEndpoint(provider, baseUrl) {
        if (!baseUrl)
            return PROVIDER_ENDPOINTS[provider] || `https://api.${provider}.com/v1/chat/completions`;
        if (baseUrl.includes('/responses'))
            return baseUrl.replace(/\/$/, '');
        return `${baseUrl.replace(/\/$/, '')}/v1/chat/completions`;
    }
    function buildFixedPrompt(systemPrompt, recentTurns, currentContent) {
        const summaryBlock = 'The following is a conversation between a user and AI assistant(s) in a team channel.';
        const messages = [
            { role: 'system', content: systemPrompt },
            { role: 'user', content: summaryBlock },
            { role: 'assistant', content: 'I understand. How can I help you today?' },
            { role: 'user', content: 'Tell me about yourself.' },
            { role: 'assistant', content: 'I am an AI assistant in this team channel, ready to help with tasks, coding, analysis, and discussion.' },
            ...recentTurns.map(m => ({ ...m, role: m.role === 'ai' ? 'assistant' : m.role })),
            { role: 'user', content: currentContent },
        ];
        return messages;
    }
    function formatChannel(row) {
        return { id: row.id, name: row.name, description: row.description || '', teammate_ids: JSON.parse(row.teammate_ids || '[]'), created_at: row.created_at, updated_at: row.updated_at };
    }
    function formatTeammate(row) {
        return { id: row.id, name: row.name, role: row.role || 'assistant', avatar_emoji: row.avatar_emoji || '🤖', system_prompt: row.system_prompt || '', model_provider: row.model_provider, model_name: row.model_name, api_key_ref: row.api_key_ref || undefined };
    }
    function formatMessage(row) {
        return { id: row.id, channel_id: row.channel_id, role: row.role, author_name: row.author_name, author_id: row.author_id || undefined, content: row.content || '', attachments: row.attachments ? JSON.parse(row.attachments) : [], created_at: row.created_at };
    }
    const routes = [];
    function route(method, pattern, handler) {
        const regex = new RegExp('^' + pattern.replace(/:[^/]+/g, '([^/]+)') + '$');
        routes.push({ method, pattern: regex, handler });
    }
    function matchRoute(method, pathname) {
        for (const r of routes) {
            if (r.method !== method && r.method !== 'ANY')
                continue;
            const match = pathname.match(r.pattern);
            if (match)
                return { handler: r.handler, match };
        }
        return null;
    }
    // Channels
    route('GET', '/api/channels', async (_req, _match, env) => {
        const { results } = await env.DB.prepare('SELECT * FROM channels ORDER BY created_at').all();
        return json(results.map(formatChannel));
    });
    route('POST', '/api/channels', async (req, _match, env) => {
        const data = await req.json();
        const id = genUUID();
        const now = utcNow();
        await env.DB.prepare('INSERT INTO channels (id, name, description, created_at, updated_at, teammate_ids) VALUES (?, ?, ?, ?, ?, ?)').bind(id, data.name || '', data.description || '', now, now, '[]').run();
        return json({ id, name: data.name, description: data.description || '' }, 201);
    });
    route('GET', '/api/channels/:id', async (_req, match, env) => {
        const id = match[1];
        const row = await env.DB.prepare('SELECT * FROM channels WHERE id = ?').bind(id).first();
        if (!row)
            return error('Channel not found', 404);
        return json(formatChannel(row));
    });
    route('PATCH', '/api/channels/:id', async (req, match, env) => {
        const id = match[1];
        const data = await req.json();
        const existing = await env.DB.prepare('SELECT * FROM channels WHERE id = ?').bind(id).first();
        if (!existing)
            return error('Channel not found', 404);
        const name = data.name ?? existing.name;
        const description = data.description ?? existing.description;
        await env.DB.prepare('UPDATE channels SET name = ?, description = ?, updated_at = ? WHERE id = ?').bind(name, description, utcNow(), id).run();
        return json({ ok: true });
    });
    route('DELETE', '/api/channels/:id', async (_req, match, env) => {
        const id = match[1];
        const existing = await env.DB.prepare('SELECT id FROM channels WHERE id = ?').bind(id).first();
        if (!existing)
            return error('Channel not found', 404);
        await env.DB.prepare('DELETE FROM messages WHERE channel_id = ?').bind(id).run();
        await env.DB.prepare('DELETE FROM channels WHERE id = ?').bind(id).run();
        return json({ ok: true });
    });
    route('POST', '/api/channels/:id/teammates/:teammate_id', async (_req, match, env) => {
        const channelId = match[1];
        const teammateId = match[2];
        const ch = await env.DB.prepare('SELECT * FROM channels WHERE id = ?').bind(channelId).first();
        if (!ch)
            return error('Channel not found', 404);
        const tm = await env.DB.prepare('SELECT id FROM teammates WHERE id = ?').bind(teammateId).first();
        if (!tm)
            return error('Teammate not found', 404);
        const ids = JSON.parse(ch.teammate_ids || '[]');
        if (!ids.includes(teammateId))
            ids.push(teammateId);
        await env.DB.prepare('UPDATE channels SET teammate_ids = ?, updated_at = ? WHERE id = ?').bind(JSON.stringify(ids), utcNow(), channelId).run();
        return json({ ok: true, teammate_ids: ids });
    });
    route('DELETE', '/api/channels/:id/teammates/:teammate_id', async (_req, match, env) => {
        const channelId = match[1];
        const teammateId = match[2];
        const ch = await env.DB.prepare('SELECT * FROM channels WHERE id = ?').bind(channelId).first();
        if (!ch)
            return error('Channel not found', 404);
        const ids = JSON.parse(ch.teammate_ids || '[]');
        const idx = ids.indexOf(teammateId);
        if (idx >= 0)
            ids.splice(idx, 1);
        await env.DB.prepare('UPDATE channels SET teammate_ids = ?, updated_at = ? WHERE id = ?').bind(JSON.stringify(ids), utcNow(), channelId).run();
        return json({ ok: true, teammate_ids: ids });
    });
    // Teammates
    route('GET', '/api/teammates', async (_req, _match, env) => {
        const { results } = await env.DB.prepare('SELECT * FROM teammates ORDER BY created_at').all();
        return json(results.map(formatTeammate));
    });
    route('POST', '/api/teammates', async (req, _match, env) => {
        const data = await req.json();
        const id = genUUID();
        const now = utcNow();
        await env.DB.prepare('INSERT INTO teammates (id, name, role, avatar_emoji, system_prompt, model_provider, model_name, api_key_ref, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)').bind(id, data.name || '', data.role || 'assistant', data.avatar_emoji || '🤖', data.system_prompt || 'You are a helpful AI assistant.', data.model_provider || '', data.model_name || '', data.api_key_ref || null, now, now).run();
        return json({ id, name: data.name }, 201);
    });
    route('GET', '/api/teammates/:id', async (_req, match, env) => {
        const id = match[1];
        const row = await env.DB.prepare('SELECT * FROM teammates WHERE id = ?').bind(id).first();
        if (!row)
            return error('Teammate not found', 404);
        return json(formatTeammate(row));
    });
    route('PATCH', '/api/teammates/:id', async (req, match, env) => {
        const id = match[1];
        const data = await req.json();
        const existing = await env.DB.prepare('SELECT * FROM teammates WHERE id = ?').bind(id).first();
        if (!existing)
            return error('Teammate not found', 404);
        const fields = ['name', 'role', 'avatar_emoji', 'system_prompt', 'model_provider', 'model_name', 'api_key_ref'];
        const updates = [];
        const values = [];
        for (const f of fields) {
            if (f in data) {
                updates.push(`${f} = ?`);
                values.push(data[f]);
            }
        }
        if (updates.length > 0) {
            updates.push('updated_at = ?');
            values.push(utcNow());
            values.push(id);
            await env.DB.prepare(`UPDATE teammates SET ${updates.join(', ')} WHERE id = ?`).bind(...values).run();
        }
        return json({ ok: true });
    });
    route('DELETE', '/api/teammates/:id', async (_req, match, env) => {
        const id = match[1];
        const existing = await env.DB.prepare('SELECT id FROM teammates WHERE id = ?').bind(id).first();
        if (!existing)
            return error('Teammate not found', 404);
        await env.DB.prepare('DELETE FROM teammates WHERE id = ?').bind(id).run();
        return json({ ok: true });
    });
    // API Keys
    route('GET', '/api/apikeys', async (_req, _match, env) => {
        const { results } = await env.DB.prepare('SELECT * FROM apikeys ORDER BY created_at').all();
        return json(results.map((k) => ({ id: k.id, provider: k.provider, label: k.label, api_key: k.api_key ? k.api_key.slice(0, 8) + '***' : '', base_url: k.base_url, has_key: !!k.api_key })));
    });
    route('POST', '/api/apikeys', async (req, _match, env) => {
        const data = await req.json();
        const id = genUUID();
        const now = utcNow();
        await env.DB.prepare('INSERT INTO apikeys (id, provider, label, api_key, base_url, created_at) VALUES (?, ?, ?, ?, ?, ?)').bind(id, data.provider || '', data.label || '', data.api_key || '', data.base_url || null, now).run();
        return json({ id, provider: data.provider, label: data.label, has_key: !!data.api_key }, 201);
    });
    route('DELETE', '/api/apikeys/:id', async (_req, match, env) => {
        const id = match[1];
        const existing = await env.DB.prepare('SELECT id FROM apikeys WHERE id = ?').bind(id).first();
        if (!existing)
            return error('API Key not found', 404);
        await env.DB.prepare('DELETE FROM apikeys WHERE id = ?').bind(id).run();
        return json({ ok: true });
    });
    // Messages
    route('GET', '/api/messages/:channel_id', async (_req, match, env) => {
        const channelId = match[1];
        const limitStr = new URL(_req.url).searchParams.get('limit');
        const limit = Number(limitStr || 200);
        const { results } = await env.DB.prepare('SELECT * FROM messages WHERE channel_id = ? ORDER BY created_at LIMIT ?').bind(channelId, limit).all();
        return json(results.map(formatMessage));
    });
    route('DELETE', '/api/messages/:channel_id', async (_req, match, env) => {
        const channelId = match[1];
        const ch = await env.DB.prepare('SELECT id FROM channels WHERE id = ?').bind(channelId).first();
        if (!ch)
            return error('Channel not found', 404);
        const { results } = await env.DB.prepare('DELETE FROM messages WHERE channel_id = ? RETURNING id').bind(channelId).all();
        return json({ ok: true, deleted: results.length });
    });
    // ── ChatGPT-style File Attachment Upload ──
    route('POST', '/api/messages/:channel_id/file', async (req, match, env) => {
        try {
            const channelId = match[1];
            const ch = await env.DB.prepare('SELECT id FROM channels WHERE id = ?').bind(channelId).first();
            if (!ch) return error('Channel not found', 404);
            const ct = req.headers.get('content-type') || '';
            if (!ct.includes('multipart/form-data')) return error('Expected multipart/form-data', 400);
            const boundary = ct.split('boundary=')[1];
            if (!boundary) return error('Missing boundary', 400);
            const authorName = req.headers.get('X-Author-Name') || 'You';
            const raw = await req.arrayBuffer();
            const parts = parseMultipart(raw, boundary);
            if (!parts.file) return error('No file field', 400);
            const fileBytes = new Uint8Array(parts.file.data);
            const fileName = parts.file.filename || 'unknown';
            const mime = parts.file.mime || 'application/octet-stream';
            const ext = fileName.includes('.') ? fileName.split('.').pop().toLowerCase() : '';
            if (fileBytes.length > 5*1024*1024) return error('File too large (max 5MB)', 413);

            const fileId = genUUID();
            const now = utcNow();
            const isImage = mime.startsWith('image/');
            const isText = isImage || ['txt','md','csv','py','js','ts','json','html','css','xml','yaml','yml','toml','sh','java','go','rs','rb','php','sql','log','conf','ini','pdf','docx'].includes(ext) || mime.startsWith('text/');
            const previewText = isImage ? '[Image]' : new TextDecoder('utf-8').decode(fileBytes.slice(0, 200));

            // RAG indexing: chunk + embed text files
            let chunks = [];
            let rawText = '';
            if (!isImage) {
                rawText = new TextDecoder('utf-8').decode(fileBytes) || '';
                if (rawText.trim()) {
                    chunks = chunkText(rawText);
                }
            }

            // Store file metadata FIRST (file_chunks has FK -> file_uploads)
            await env.DB.prepare('INSERT INTO file_uploads (id,filename,file_type,size,user_id,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)')
                .bind(fileId, fileName, ext || mime, String(fileBytes.length), 'channel:' + channelId, 'ready', now, now).run();

            // Now insert chunks (FK satisfied)
            for (let i = 0; i < chunks.length; i++) {
                const emb = embedText(chunks[i].content);
                const chunkId = genUUID();
                await env.DB.prepare('INSERT INTO file_chunks (id,file_id,content,"index",embedding,created_at) VALUES (?,?,?,?,?,?)')
                    .bind(chunkId, fileId, chunks[i].content, String(i), JSON.stringify(emb), now).run();
            }

            // Create attachment object (ChatGPT-style structured card)
            const attachment = {
                file_id: fileId,
                filename: fileName,
                mime: mime,
                size: fileBytes.length,
                preview_text: previewText,
                status: 'ready',
                chunk_count: chunks.length,
                is_image: isImage,
                created_at: now,
            };

            // Save a user message with the file attachment (so it appears in chat)
            const msgId = genUUID();
            await env.DB.prepare('INSERT INTO messages (id,channel_id,role,author_name,content,attachments,created_at) VALUES (?,?,?,?,?,?,?)')
                .bind(msgId, channelId, 'user', authorName, `[上传文件: ${fileName}]`, JSON.stringify([attachment]), now).run();

            return json({
                file_id: fileId,
                filename: fileName,
                mime,
                size: fileBytes.length,
                status: 'ready',
                chunk_count: chunks.length,
                preview_text: previewText,
                message_id: msgId,
            }, 201);
        } catch (e) {
            return json({ error: e.message, stack: e.stack }, 500);
        }
    });

    // ── List channel files ──
    route('GET', '/api/channels/:id/files', async (req, match, env) => {
        const channelId = match[1];
        const { results } = await env.DB.prepare(
            'SELECT DISTINCT json_extract(value, \'$.file_id\') as file_id, json_extract(value, \'$.filename\') as filename, json_extract(value, \'$.mime\') as mime, json_extract(value, \'$.size\') as size, json_extract(value, \'$.status\') as status, json_extract(value, \'$.chunk_count\') as chunk_count, json_extract(value, \'$.preview_text\') as preview_text, json_extract(value, \'$.created_at\') as created_at FROM messages, json_each(messages.attachments) WHERE messages.channel_id = ? AND messages.attachments IS NOT NULL ORDER BY messages.created_at DESC'
        ).bind(channelId).all();
        return json({ files: results || [], total: (results || []).length });
    });

    route('POST', '/api/messages/:channel_id/system', async (req, match, env) => {
        const channelId = match[1];
        const data = await req.json();
        const ch = await env.DB.prepare('SELECT id FROM channels WHERE id = ?').bind(channelId).first();
        if (!ch)
            return error('Channel not found', 404);
        const id = genUUID();
        await env.DB.prepare('INSERT INTO messages (id, channel_id, role, author_name, content, created_at) VALUES (?, ?, ?, ?, ?, ?)').bind(id, channelId, 'system', data.author_name || 'System', data.content || '', utcNow()).run();
        return json({ id, role: 'system' }, 201);
    });
    // AI Chat
    route('POST', '/api/messages/:channel_id', async (req, match, env) => {
        const channelId = match[1];
        const data = await req.json();
        const channel = await env.DB.prepare('SELECT id FROM channels WHERE id = ?').bind(channelId).first();
        if (!channel)
            return error('Channel not found', 404);
        const content = data.content || '';
        const teammateId = data.teammate_id || null;
        const skipUserSave = data.skip_user_save || false;
        const authorName = data.author_name || 'You';
        let userMsgId = null;
        if (!skipUserSave) {
            userMsgId = genUUID();
            await env.DB.prepare('INSERT INTO messages (id, channel_id, role, author_name, content, attachments, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)').bind(userMsgId, channelId, 'user', authorName, content, data.attachments ? JSON.stringify(data.attachments) : null, utcNow()).run();
        }
        if (!teammateId)
            return json({ user_message_id: userMsgId });
        const tm = await env.DB.prepare('SELECT * FROM teammates WHERE id = ?').bind(teammateId).first();
        if (!tm)
            return error('Teammate not found', 404);
        if (!tm.api_key_ref)
            return error('Teammate has no API key configured', 400);
        const apiKeyRow = await env.DB.prepare('SELECT * FROM apikeys WHERE id = ?').bind(tm.api_key_ref).first();
        if (!apiKeyRow || !apiKeyRow.api_key)
            return error('API key not found', 400);
        const { results: msgResults } = await env.DB.prepare('SELECT role, content, attachments FROM messages WHERE channel_id = ? ORDER BY created_at LIMIT 200').bind(channelId).all();
        // Auto-inject RAG context from channel files
        let fileContext = '';
        try {
            const fileRows = await env.DB.prepare(
                'SELECT DISTINCT json_extract(value, \'$.file_id\') as file_id FROM messages, json_each(messages.attachments) WHERE messages.channel_id = ? AND messages.attachments IS NOT NULL'
            ).bind(channelId).all();
            const fileIds = (fileRows.results || []).map(r => r.file_id).filter(Boolean);
            if (fileIds.length > 0) {
                const qEmb = embedText(content);
                const allChunked = [];
                for (const fid of fileIds) {
                    const chunkRows = await env.DB.prepare('SELECT content, "index", embedding FROM file_chunks WHERE file_id = ?').bind(fid).all();
                    for (const cr of (chunkRows.results || [])) {
                        if (!cr.embedding) continue;
                        allChunked.push({ content: cr.content, file_id: fid, score: cosineSim(qEmb, JSON.parse(cr.embedding)) });
                    }
                }
                allChunked.sort((a, b) => b.score - a.score);
                const topChunks = allChunked.slice(0, 5);
                if (topChunks.length > 0) {
                    fileContext = topChunks.map((c, i) => `[文件引用 ${i + 1}] ${c.content}`).join('\n\n');
                }
            }
        } catch (e) { console.error('RAG context error:', e); }
        const allMessages = msgResults.map((m) => {
            let msgContent = m.content || '';
            if (m.attachments) {
                try {
                    const atts = JSON.parse(m.attachments);
                    if (atts[0]?.filename && msgContent.startsWith('[上传文件:')) {
                        msgContent = `[文件: ${atts[0].filename}]\n预览: ${(atts[0].preview_text || '').slice(0, 200)}`;
                    }
                } catch {}
            }
            return { role: m.role === 'ai' ? 'assistant' : m.role, content: msgContent };
        });
        const recentTurns = allMessages.slice(-6);
        let currentContent = content;
        if (fileContext) currentContent = '[参考文件内容]\n' + fileContext + '\n\n[用户问题]\n' + content;
        const fixedMessages = buildFixedPrompt(tm.system_prompt, recentTurns, currentContent);
        const provider = tm.model_provider;
        const isAnthropic = provider === 'anthropic';
        const endpoint = getEndpoint(provider, apiKeyRow.base_url);
        const headers = { 'Content-Type': 'application/json' };
        let payload;
        if (isAnthropic) {
            headers['x-api-key'] = apiKeyRow.api_key;
            headers['anthropic-version'] = '2023-06-01';
            payload = { model: tm.model_name, system: tm.system_prompt, messages: fixedMessages.filter((m) => m.role !== 'system'), max_tokens: 4096, stream: true };
        }
        else {
            headers['Authorization'] = `Bearer ${apiKeyRow.api_key}`;
            payload = { model: tm.model_name, messages: fixedMessages, stream: false, temperature: 0.7, max_tokens: 2000 };
        }
        let response;
        try {
            response = await fetch(endpoint, { method: 'POST', headers, body: JSON.stringify(payload), redirect: 'follow' });
        }
        catch (fetchErr) {
            return json({ detail: `AI Fetch Error: ${fetchErr.message}` }, 502);
        }
        if (!response.ok) {
            const text = await response.text();
            return json({ detail: `AI Error: ${response.status} ${text.slice(0, 200)}` }, 502);
        }
        const r = await response.json();
        let full = '';
        if (r.choices?.[0]?.message?.content)
            full = r.choices[0].message.content;
        else if (r.output?.[0]?.content?.[0]?.text)
            full = r.output[0].content[0].text;
        if (full.trim()) {
            const aiMsgId = genUUID();
            try {
                await env.DB.prepare('INSERT INTO messages (id, channel_id, role, author_name, author_id, content, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)').bind(aiMsgId, channelId, 'ai', tm.name, teammateId, full, utcNow()).run();
            }
            catch (e) {
                console.error('Failed to save AI response:', e);
            }
        }
        const encoder = new TextEncoder();
        const stream = new ReadableStream({ start(controller) { controller.enqueue(encoder.encode(full)); controller.close(); } });
        return new Response(stream, { headers: { 'Content-Type': 'text/plain; charset=utf-8' } });
    });
    // Models
    route('GET', '/api/models/:provider', async (_req, match, env) => {
        const provider = match[1];
        if (provider === 'openrouter') {
            const res = await fetch('https://openrouter.ai/api/v1/models');
            const data = await res.json();
            return json((data.data || []).map((m) => ({ id: m.id, name: m.name || m.id, context_length: m.context_length || 0, is_free: (m.pricing?.prompt === '0'), pricing: m.pricing || {} })));
        }
        return json([{ id: provider + '-default', name: provider + ' Default', context_length: 32000 }]);
    });
    // Health
    route('GET', '/api/health', () => {
        return json({ status: 'ok', service: 'AI Team Hub', version: '2.1.0', engine: 'state_machine_dag', platform: 'cloudflare_workers' });
    });
    // Debug: check API key and D1
    route('GET', '/api/debug', async (_req, _match, env) => {
        try {
            const row = await env.DB.prepare('SELECT id, provider, label, length(api_key) as key_len FROM apikeys LIMIT 1').first();
            return json({ db: 'ok', key_len: row?.key_len || 0, provider: row?.provider || 'none' });
        }
        catch (e) {
            return json({ db: 'error', detail: e.message }, 500);
        }
    });
    // v5 Adaptive Orchestrator (default)
    route('POST', '/api/orchestrator/run', async (req, _match, env) => {
        try {
            // ── v2.5: Ensure collaboration tables exist ──
            await env.DB.prepare("CREATE TABLE IF NOT EXISTS collaboration_events (id TEXT PRIMARY KEY, event_type TEXT NOT NULL, source TEXT DEFAULT 'system', task_id TEXT NOT NULL, data TEXT DEFAULT '{}', timestamp INTEGER DEFAULT 0)").run();
            await env.DB.prepare("CREATE TABLE IF NOT EXISTS collaboration_context (id TEXT PRIMARY KEY, task_id TEXT NOT NULL, key TEXT NOT NULL, value TEXT DEFAULT 'null', agent_id TEXT DEFAULT 'system', timestamp INTEGER DEFAULT 0)").run();
            const data = await req.json();
            const task = data.task || '';
            const provider = data.provider || 'openrouter';
            const model = data.model || 'openrouter/auto';
            const forceMode = data.force_mode || null; // SIMPLE | STANDARD | COMPLEX
            const apiKeyRow = await env.DB.prepare('SELECT * FROM apikeys WHERE provider = ? LIMIT 1').bind(provider).first();
            if (!apiKeyRow || !apiKeyRow.api_key)
                return error(`No API key for provider: ${provider}`, 400);
            let result;
            // v5: Adaptive orchestration — classifier decides mode
            result = await runAdaptiveOrchestrator(task, apiKeyRow.api_key, provider, model, apiKeyRow.base_url, forceMode, env.DB);
            return json({
                task_id: result.context.taskId,
                trace_id: result.trace[0]?.traceId || '',
                state: result.context.state,
                mode: result.context.mode,
                complexity: result.context.complexity,
                plan: result.context.plan,
                execution_result: result.context.executionResult,
                review_result: result.context.reviewResult,
                final_result: result.context.finalResult,
                llm_calls: result.context.llmCalls,
                skipped_stages: result.context.skippedStages,
                diversity_report: result.context.diversityReport || {},
                trace_length: result.trace.length,
            });
        }
        catch (e) {
            console.error('Orchestrator error:', e.message, e.stack);
            return json({ error: 'Orchestrator failed', detail: e.message }, 500);
        }
    });
    // ═══════════════════════════════════════════════════════════
    // MAEOS — Multi-Agent Execution Operating System Routes
    // ═══════════════════════════════════════════════════════════
    // MAEOS on Workers: synchronous execution with D1 persistence
    // Pipeline: Task → Scheduler → Worker → FSM → Agents → Validation → Memory(D1)
    const TASK_PRIORITIES = { CRITICAL: 0, HIGH: 1, NORMAL: 2, LOW: 3, BACKGROUND: 4 };
    const TASK_STATUSES = ['PENDING', 'SCHEDULED', 'RUNNING', 'COMPLETED', 'FAILED', 'RETRYING', 'ABORTED'];
    // Ensure maeos_tasks table exists
    async function ensureMAEOSTables(env) {
        await env.DB.prepare(`CREATE TABLE IF NOT EXISTS maeos_tasks (id TEXT PRIMARY KEY, description TEXT NOT NULL, priority INTEGER DEFAULT 2, status TEXT DEFAULT 'PENDING', intent TEXT DEFAULT '', worker_id TEXT DEFAULT '', provider TEXT DEFAULT 'openrouter', model TEXT DEFAULT 'openrouter/auto', result TEXT DEFAULT '', error TEXT DEFAULT '', trace_report TEXT DEFAULT '{}', diversity_report TEXT DEFAULT '{}', context_json TEXT DEFAULT '{}', retry_count INTEGER DEFAULT 0, max_retries INTEGER DEFAULT 3, created_at REAL DEFAULT 0, scheduled_at REAL DEFAULT 0, started_at REAL DEFAULT 0, completed_at REAL DEFAULT 0)`).run();
        // ── v2.5: Collaboration Layer Tables ──
        await env.DB.prepare("CREATE TABLE IF NOT EXISTS collaboration_events (id TEXT PRIMARY KEY, event_type TEXT NOT NULL, source TEXT DEFAULT 'system', task_id TEXT NOT NULL, data TEXT DEFAULT '{}', timestamp INTEGER DEFAULT 0)").run();
        await env.DB.prepare("CREATE TABLE IF NOT EXISTS collaboration_context (id TEXT PRIMARY KEY, task_id TEXT NOT NULL, key TEXT NOT NULL, value TEXT DEFAULT 'null', agent_id TEXT DEFAULT 'system', timestamp INTEGER DEFAULT 0)").run();
    }
    // ── POST /api/maeos/submit — Submit task, execute synchronously, persist to D1 ──
    route('POST', '/api/maeos/submit', async (req, _match, env) => {
        try {
            await ensureMAEOSTables(env);
            const data = await req.json();
            const taskId = `task_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
            const priority = data.priority ?? 2;
            const provider = data.provider || 'openrouter';
            const model = data.model || 'openrouter/auto';
            const intent = data.intent || '';
            const now = Date.now() / 1000;
            // Get API key
            const apiKeyRow = await env.DB.prepare('SELECT * FROM apikeys WHERE provider = ? LIMIT 1').bind(provider).first();
            if (!apiKeyRow || !apiKeyRow.api_key)
                return error(`No API key for provider: ${provider}`, 400);
            // Insert as PENDING
            await env.DB.prepare(`INSERT INTO maeos_tasks (id, description, priority, status, intent, provider, model, created_at)
                VALUES (?, ?, ?, 'PENDING', ?, ?, ?, ?)`).bind(taskId, data.task, priority, intent, provider, model, now).run();
            // Update to RUNNING
            await env.DB.prepare(`UPDATE maeos_tasks SET status = 'RUNNING', started_at = ? WHERE id = ?`).bind(now, taskId).run();
            // Execute FSM synchronously
            let result;
            try {
                result = await runAdaptiveOrchestrator(data.task, apiKeyRow.api_key, provider, model, apiKeyRow.base_url, null, env.DB);
            } catch (execErr) {
                await env.DB.prepare(`UPDATE maeos_tasks SET status = 'FAILED', error = ?, completed_at = ? WHERE id = ?`)
                    .bind(execErr.message?.slice(0, 500) || 'Execution error', Date.now() / 1000, taskId).run();
                return json({ task_id: taskId, status: 'FAILED', error: execErr.message }, 500);
            }
            const finalStatus = result.context.error ? 'FAILED' : 'COMPLETED';
            const completedAt = Date.now() / 1000;
            // Persist full state
            await env.DB.prepare(`UPDATE maeos_tasks SET
                status = ?, result = ?, error = ?, worker_id = 'worker_001',
                trace_report = ?, diversity_report = ?, context_json = ?,
                retry_count = ?, completed_at = ?
                WHERE id = ?`).bind(
                finalStatus,
                (result.context.finalResult || '').slice(0, 5000),
                (result.context.error || '').slice(0, 500),
                JSON.stringify(result.trace || []),
                JSON.stringify(result.context.diversityReport || {}),
                JSON.stringify(result.context),
                result.context.retryCount || 0,
                completedAt,
                taskId
            ).run();
            return json({ task_id: taskId, status: finalStatus });
        } catch (e) {
            console.error('MAEOS submit error:', e.message, e.stack);
            return json({ error: 'MAEOS submit failed', detail: e.message }, 500);
        }
    });
    // ── GET /api/maeos/status/:id ──
    route('GET', '/api/maeos/status/:id', async (_req, match, env) => {
        try {
            await ensureMAEOSTables(env);
            const id = match[1];
            const row = await env.DB.prepare('SELECT * FROM maeos_tasks WHERE id = ?').bind(id).first();
            if (!row) return error('Task not found', 404);
            return json({
                id: row.id,
                description: (row.description || '').slice(0, 200),
                priority: row.priority,
                status: row.status,
                worker_id: row.worker_id,
                result_length: (row.result || '').length,
                error: (row.error || '').slice(0, 200),
                retry_count: row.retry_count,
                created_at: row.created_at,
                completed_at: row.completed_at,
                total_latency: row.completed_at && row.created_at ? row.completed_at - row.created_at : 0,
                diversity_score: JSON.parse(row.diversity_report || '{}').overall_diversity_score ?? null,
            });
        } catch (e) {
            return json({ error: e.message }, 500);
        }
    });
    // ── GET /api/maeos/debug/:id ──
    route('GET', '/api/maeos/debug/:id', async (_req, match, env) => {
        try {
            await ensureMAEOSTables(env);
            const id = match[1];
            const row = await env.DB.prepare('SELECT * FROM maeos_tasks WHERE id = ?').bind(id).first();
            if (!row) return error('Task not found', 404);
            return json({
                task_id: row.id,
                description: row.description,
                priority: row.priority,
                status: row.status,
                intent: row.intent,
                worker_id: row.worker_id,
                result: row.result,
                error: row.error,
                context: JSON.parse(row.context_json || '{}'),
                trace_report: JSON.parse(row.trace_report || '[]'),
                diversity_report: JSON.parse(row.diversity_report || '{}'),
                timing: {
                    created_at: row.created_at,
                    scheduled_at: row.scheduled_at,
                    started_at: row.started_at,
                    completed_at: row.completed_at,
                    total_latency: row.completed_at && row.created_at ? row.completed_at - row.created_at : 0,
                },
                retry_count: row.retry_count,
                _replay: { replayed_at: Date.now() / 1000 },
            });
        } catch (e) {
            return json({ error: e.message }, 500);
        }
    });
    // ── GET /api/maeos/tasks ──
    route('GET', '/api/maeos/tasks', async (_req, _match, env) => {
        try {
            await ensureMAEOSTables(env);
            const { results } = await env.DB.prepare('SELECT id, description, priority, status, worker_id, created_at, completed_at, retry_count FROM maeos_tasks ORDER BY created_at DESC LIMIT 50').all();
            return json((results || []).map(r => ({
                id: r.id,
                description: (r.description || '').slice(0, 100),
                priority: r.priority,
                status: r.status,
                worker_id: r.worker_id,
                created_at: r.created_at,
                completed_at: r.completed_at,
                total_latency: r.completed_at && r.created_at ? r.completed_at - r.created_at : 0,
                retry_count: r.retry_count,
            })));
        } catch (e) {
            return json({ error: e.message }, 500);
        }
    });
    // ── GET /api/maeos/stats ──
    route('GET', '/api/maeos/stats', async (_req, _match, env) => {
        try {
            await ensureMAEOSTables(env);
            const total = await env.DB.prepare('SELECT COUNT(*) as count FROM maeos_tasks').first();
            const byStatus = await env.DB.prepare("SELECT status, COUNT(*) as count FROM maeos_tasks GROUP BY status").all();
            const avgLatency = await env.DB.prepare("SELECT AVG(completed_at - created_at) as avg FROM maeos_tasks WHERE status IN ('COMPLETED','FAILED') AND completed_at > 0").first();
            const statusMap = {};
            for (const r of (byStatus.results || []))
                statusMap[r.status] = r.count;
            return json({
                status: 'running',
                total_workers: 4,
                busy_workers: 0,
                queue_size: statusMap.PENDING || 0,
                queue_pending: statusMap.PENDING || 0,
                queue_running: statusMap.RUNNING || 0,
                memory: {
                    total_entries: total?.count || 0,
                    max_entries: 10000,
                    status_breakdown: statusMap,
                    total_retries: 0,
                    avg_latency: Math.round((avgLatency?.avg || 0) * 1000) / 1000,
                },
            });
        } catch (e) {
            return json({ status: 'running', error: e.message, total_workers: 4 }, 500);
        }
    });
    // ── GET /api/maeos/memory/stats ──
    route('GET', '/api/maeos/memory/stats', async (_req, _match, env) => {
        try {
            await ensureMAEOSTables(env);
            const total = await env.DB.prepare('SELECT COUNT(*) as count FROM maeos_tasks').first();
            const byStatus = await env.DB.prepare("SELECT status, COUNT(*) as count FROM maeos_tasks GROUP BY status").all();
            const statusMap = {};
            for (const r of (byStatus.results || []))
                statusMap[r.status] = r.count;
            const avgLatency = await env.DB.prepare("SELECT AVG(completed_at - created_at) as avg FROM maeos_tasks WHERE status IN ('COMPLETED','FAILED') AND completed_at > 0").first();
            return json({
                total_entries: total?.count || 0,
                max_entries: 10000,
                status_breakdown: statusMap,
                total_retries: 0,
                avg_latency: Math.round((avgLatency?.avg || 0) * 1000) / 1000,
            });
        } catch (e) {
            return json({ error: e.message }, 500);
        }
    });
    // v2 Traces
    route('GET', '/api/traces/', async (_req, _match, env) => {
        try {
            const { results } = await env.DB.prepare('SELECT DISTINCT trace_id, task_id, MIN(ts) as start_time FROM trace_events GROUP BY trace_id ORDER BY start_time DESC LIMIT 20').all();
            return json(results || []);
        }
        catch {
            return json([]);
        }
    });
    route('GET', '/api/traces/:id', async (_req, match, env) => {
        const id = match[1];
        try {
            const row = await env.DB.prepare('SELECT context_json FROM task_states WHERE trace_id = ?').bind(id).first();
            if (!row)
                return error('Trace not found', 404);
            return json(JSON.parse(row.context_json));
        }
        catch {
            return error('Trace not found', 404);
        }
    });
    route('GET', '/api/traces/:id/:action', async (_req, match, env) => {
        const id = match[1];
        const action = match[2];
        try {
            const row = await env.DB.prepare('SELECT context_json FROM task_states WHERE trace_id = ?').bind(id).first();
            if (!row)
                return error('Trace not found', 404);
            const data = JSON.parse(row.context_json);
            if (action === 'replay')
                return json(data);
            if (action === 'analysis') {
                const trace = data.trace || [];
                const failures = trace.filter((e) => e.output_data?.status === 'error');
                return json({ trace_id: id, total_steps: trace.length, failures: failures.length, failure_details: failures });
            }
            return error('Unknown action', 400);
        }
        catch {
            return error('Trace not found', 404);
        }
    });
    // ═══════════════════════════════════════════
    // Collaboration Layer API (v2.5)
    // ═══════════════════════════════════════════
    
    // ── Event History — query events by task ──
    route('GET', '/api/events', async (req, _match, env) => {
        const url = new URL(req.url);
        const taskId = url.searchParams.get('task_id');
        const limit = parseInt(url.searchParams.get('limit') || '100');
        if (!taskId) return error('task_id required', 400);
        const { results } = await env.DB.prepare(
            'SELECT * FROM collaboration_events WHERE task_id = ? ORDER BY timestamp DESC LIMIT ?'
        ).bind(taskId, limit).all();
        return json(results.map(e => ({
            id: e.id,
            event_type: e.event_type,
            source: e.source,
            task_id: e.task_id,
            data: JSON.parse(e.data || '{}'),
            timestamp: e.timestamp,
        })));
    });

    // ── Shared Context — get current state for a task ──
    route('GET', '/api/context/:task_id', async (_req, match, env) => {
        const taskId = match[1];
        const { results } = await env.DB.prepare(
            'SELECT * FROM collaboration_context WHERE task_id = ? ORDER BY timestamp DESC'
        ).bind(taskId).all();
        // Build current state (latest value per key, with history)
        const state = {};
        const history = {};
        // Process in ascending order for correct latest-value
        results.reverse();
        for (const row of results) {
            const key = row.key;
            const val = JSON.parse(row.value);
            state[key] = val;
            if (!history[key]) history[key] = [];
            history[key].push({
                value: val,
                agent_id: row.agent_id,
                timestamp: row.timestamp,
                entry_id: row.id,
            });
        }
        return json({ task_id: taskId, state, history, entry_count: results.length });
    });

    // ── Shared Context — write entry ──
    route('POST', '/api/context/:task_id', async (req, match, env) => {
        const taskId = match[1];
        const body = await req.json();
        const { key, value, agent_id } = body;
        if (!key) return error('key required', 400);
        const id = genUUID();
        const now = utcNow();
        await env.DB.prepare(
            'INSERT INTO collaboration_context (id, task_id, key, value, agent_id, timestamp) VALUES (?, ?, ?, ?, ?, ?)'
        ).bind(id, taskId, key, JSON.stringify(value ?? null), agent_id || 'system', now).run();
        return json({ ok: true, entry_id: id });
    });

    // ── Active Tasks — list tasks with recent activity ──
    route('GET', '/api/tasks/active', async (_req, _match, env) => {
        const cutoff = Math.floor(Date.now() / 1000) - 3600;
        const { results } = await env.DB.prepare(
            "SELECT task_id, COUNT(*) as event_count, MAX(timestamp) as last_active FROM collaboration_events WHERE timestamp > ? GROUP BY task_id ORDER BY last_active DESC LIMIT 50"
        ).bind(cutoff).all();
        return json(results);
    });

    // ═══════════════════════════════════════════
    // v9: Workspace API Routes
    // ═══════════════════════════════════════════

    // ── Create Workspace ──
    route('POST', '/api/workspaces', async (req, _match, env) => {
        const body = await req.json();
        const id = crypto.randomUUID().slice(0, 12);
        const now = new Date().toISOString();
        await env.DB.prepare(
            "INSERT INTO workspaces (id, title, description, status, metadata, created_at, updated_at) VALUES (?, ?, ?, 'active', '{}', ?, ?)"
        ).bind(id, body.title || 'Untitled', body.description || '', now, now).run();
        return json({ id, title: body.title, status: 'active', created_at: now });
    });

    // ── List Workspaces ──
    route('GET', '/api/workspaces', async (_req, _match, env) => {
        const { results } = await env.DB.prepare(
            "SELECT * FROM workspaces ORDER BY updated_at DESC LIMIT 100"
        ).all();
        return json(results);
    });

    // ── Get Workspace ──
    route('GET', '/api/workspaces/:id', async (_req, match, env) => {
        const ws = await env.DB.prepare("SELECT * FROM workspaces WHERE id = ?").bind(match[1]).first();
        if (!ws) return json({ error: 'not_found' }, 404);
        const { results: threads } = await env.DB.prepare(
            "SELECT * FROM threads WHERE workspace_id = ? ORDER BY updated_at DESC"
        ).bind(ws.id).all();
        return json({ ...ws, threads });
    });

    // ── Update Workspace ──
    route('PATCH', '/api/workspaces/:id', async (req, match, env) => {
        const body = await req.json();
        const now = new Date().toISOString();
        const sets = [];
        const vals = [];
        if (body.title) { sets.push("title = ?"); vals.push(body.title); }
        if (body.description) { sets.push("description = ?"); vals.push(body.description); }
        if (body.status) { sets.push("status = ?"); vals.push(body.status); }
        sets.push("updated_at = ?");
        vals.push(now);
        vals.push(match[1]);
        await env.DB.prepare(`UPDATE workspaces SET ${sets.join(', ')} WHERE id = ?`).bind(...vals).run();
        return json({ id: match[1], updated_at: now });
    });

    // ── Archive Workspace ──
    route('DELETE', '/api/workspaces/:id', async (_req, match, env) => {
        const now = new Date().toISOString();
        await env.DB.prepare("UPDATE workspaces SET status = 'archived', updated_at = ? WHERE id = ?").bind(now, match[1]).run();
        return json({ id: match[1], status: 'archived' });
    });

    // ── Create Thread ──
    route('POST', '/api/workspaces/:id/threads', async (req, match, env) => {
        const body = await req.json();
        const id = crypto.randomUUID().slice(0, 12);
        const now = new Date().toISOString();
        await env.DB.prepare(
            "INSERT INTO threads (id, workspace_id, title, status, participants, linked_tasks, metadata, created_at, updated_at) VALUES (?, ?, ?, 'open', '[]', '[]', '{}', ?, ?)"
        ).bind(id, match[1], body.title || 'New Thread', now, now).run();
        return json({ id, workspace_id: match[1], title: body.title, status: 'open' });
    });

    // ── List Threads ──
    route('GET', '/api/workspaces/:id/threads', async (_req, match, env) => {
        const { results } = await env.DB.prepare(
            "SELECT * FROM threads WHERE workspace_id = ? ORDER BY updated_at DESC"
        ).bind(match[1]).all();
        return json(results);
    });

    // ── Get Thread ──
    route('GET', '/api/workspaces/:id/threads/:tid', async (_req, match, env) => {
        const thread = await env.DB.prepare("SELECT * FROM threads WHERE id = ?").bind(match[2]).first();
        if (!thread) return json({ error: 'not_found' }, 404);
        const { results: messages } = await env.DB.prepare(
            "SELECT * FROM thread_messages WHERE thread_id = ? ORDER BY created_at ASC"
        ).bind(thread.id).all();
        return json({ ...thread, messages });
    });

    // ── Update Thread Status ──
    route('PATCH', '/api/workspaces/:id/threads/:tid', async (req, match, env) => {
        const body = await req.json();
        const now = new Date().toISOString();
        if (body.status) {
            await env.DB.prepare("UPDATE threads SET status = ?, updated_at = ? WHERE id = ?").bind(body.status, now, match[2]).run();
        }
        return json({ id: match[2], status: body.status, updated_at: now });
    });

    // ── Add Message ──
    route('POST', '/api/workspaces/:id/threads/:tid/messages', async (req, match, env) => {
        const body = await req.json();
        const id = crypto.randomUUID().slice(0, 12);
        const now = new Date().toISOString();
        await env.DB.prepare(
            "INSERT INTO thread_messages (id, thread_id, workspace_id, participant_id, participant_type, content, role, reply_to, metadata, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, '{}', ?)"
        ).bind(id, match[2], match[1], body.participant_id || 'anon', body.participant_type || 'human', body.content || '', body.role || 'message', body.reply_to || null, now).run();
        return json({ id, thread_id: match[2], content: body.content });
    });

    // ── Get Messages ──
    route('GET', '/api/workspaces/:id/threads/:tid/messages', async (_req, match, env) => {
        const { results } = await env.DB.prepare(
            "SELECT * FROM thread_messages WHERE thread_id = ? ORDER BY created_at ASC LIMIT 500"
        ).bind(match[2]).all();
        return json(results);
    });

    // ── Interrupt Thread ──
    route('POST', '/api/workspaces/:id/threads/:tid/interrupt', async (req, match, env) => {
        const body = await req.json();
        const now = new Date().toISOString();
        await env.DB.prepare("UPDATE threads SET status = 'paused', updated_at = ? WHERE id = ?").bind(now, match[2]).run();
        // Add interruption message
        const id = crypto.randomUUID().slice(0, 12);
        await env.DB.prepare(
            "INSERT INTO thread_messages (id, thread_id, workspace_id, participant_id, participant_type, content, role, metadata, created_at) VALUES (?, ?, ?, 'system', 'system', ?, 'interruption', '{}', ?)"
        ).bind(id, match[2], match[1], body.reason || 'Interrupted', now).run();
        return json({ id: match[2], status: 'paused' });
    });

    // ── Modify Task ──
    route('POST', '/api/workspaces/:id/threads/:tid/modify', async (req, match, env) => {
        const body = await req.json();
        const now = new Date().toISOString();
        const id = crypto.randomUUID().slice(0, 12);
        await env.DB.prepare(
            "INSERT INTO thread_messages (id, thread_id, workspace_id, participant_id, participant_type, content, role, metadata, created_at) VALUES (?, ?, ?, 'human', 'human', ?, 'revision', '{}', ?)"
        ).bind(id, match[2], match[1], body.modification || '', now).run();
        return json({ id: match[2], modification: body.modification });
    });

    // ── Human Respond ──
    route('POST', '/api/workspaces/:id/threads/:tid/respond', async (req, match, env) => {
        const body = await req.json();
        const now = new Date().toISOString();
        const id = crypto.randomUUID().slice(0, 12);
        await env.DB.prepare(
            "INSERT INTO thread_messages (id, thread_id, workspace_id, participant_id, participant_type, content, role, metadata, created_at) VALUES (?, ?, ?, 'human', 'human', ?, 'message', '{}', ?)"
        ).bind(id, match[2], match[1], body.response || '', now).run();
        // Update thread back to in_progress
        await env.DB.prepare("UPDATE threads SET status = 'in_progress', updated_at = ? WHERE id = ?").bind(now, match[2]).run();
        return json({ id: match[2], status: 'in_progress' });
    });

    // ── Workspace Timeline ──
    route('GET', '/api/workspaces/:id/timeline', async (_req, match, env) => {
        const { results: messages } = await env.DB.prepare(
            "SELECT * FROM thread_messages WHERE workspace_id = ? ORDER BY created_at ASC LIMIT 500"
        ).bind(match[1]).all();
        const { results: events } = await env.DB.prepare(
            "SELECT * FROM collaboration_events WHERE workspace_id = ? ORDER BY timestamp ASC LIMIT 500"
        ).bind(match[1]).all();
        return json({ messages, events });
    });

    // ── Workspace Memory ──
    route('GET', '/api/workspaces/:id/memory', async (_req, match, env) => {
        const { results } = await env.DB.prepare(
            "SELECT * FROM workspace_memory WHERE workspace_id = ? ORDER BY ts DESC LIMIT 200"
        ).bind(match[1]).all();
        return json(results);
    });

    // ── Add Memory Entry ──
    route('POST', '/api/workspaces/:id/memory', async (req, match, env) => {
        const body = await req.json();
        const id = crypto.randomUUID().slice(0, 12);
        const ts = Date.now() / 1000;
        await env.DB.prepare(
            "INSERT INTO workspace_memory (id, workspace_id, thread_id, memory_type, content, actor, metadata, ts) VALUES (?, ?, ?, ?, ?, ?, '{}', ?)"
        ).bind(id, match[1], body.thread_id || null, body.memory_type || 'context', body.content || '', body.actor || 'system', ts).run();
        return json({ id, memory_type: body.memory_type, ts });
    });

    // ═══════════════════════════════════════════
    // Main Handler
    // ═══════════════════════════════════════════

async function handleRequest(request, env) {
    const url = new URL(request.url);
    const pathname = url.pathname;
    const method = request.method;
    if (method === 'OPTIONS')
        return corsResponse();
    // ── Proxy Bypass: /p/* → /api/* ──
    // School proxies block /api/* paths. /p/* looks like a page.
    // Also wraps JSON responses in text/html to bypass DPI.
    let realPathname = pathname;
    let isProxyPath = false;
    if (pathname.startsWith('/p/')) {
        realPathname = '/api/' + pathname.slice(3);
        isProxyPath = true;
    }
    const matched = matchRoute(method, realPathname);
    if (matched) {
        const response = await matched.handler(request, matched.match, env);
        const corsResponse_ = setCors(response);
        if (isProxyPath) {
            // Wrap JSON response in HTML to bypass DPI Content-Type checks
            const contentType = corsResponse_.headers.get('Content-Type') || '';
            if (contentType.includes('application/json') || contentType.includes('text/json')) {
                const body = await corsResponse_.text();
                const html = `<!DOCTYPE html><script type="application/json" id="d">${body}</script>`;
                return new Response(html, {
                    status: corsResponse_.status,
                    headers: {
                        'Content-Type': 'text/html; charset=utf-8',
                        'X-Original-Content-Type': contentType,
                        'Access-Control-Allow-Origin': '*',
                        'Access-Control-Allow-Methods': '*',
                        'Access-Control-Allow-Headers': '*',
                    },
                });
            }
        }
        return corsResponse_;
    }
    // Return null to fall through to static assets
    return null;
}

function indexOf(bytes, pattern, start) {
    for (let i = start; i <= bytes.length - pattern.length; i++) {
        let found = true;
        for (let j = 0; j < pattern.length; j++) {
            if (bytes[i + j] !== pattern[j]) { found = false; break; }
        }
        if (found) return i;
    }
    return -1;
}

function parseMultipart(arrayBuffer, boundary) {
    const decoder = new TextDecoder('utf-8');
    const bytes = new Uint8Array(arrayBuffer);
    const boundaryBytes = new TextEncoder().encode('--' + boundary);
    const parts = {};
    let pos = 0;
    while (pos < bytes.length) {
        const idx = indexOf(bytes, boundaryBytes, pos);
        if (idx === -1) break;
        const partStart = idx + boundaryBytes.length;
        let headerStart = partStart;
        if (bytes[headerStart] === 0x0d) headerStart++;
        if (bytes[headerStart] === 0x0a) headerStart++;
        const headerEndIdx = indexOf(bytes, [0x0d, 0x0a, 0x0d, 0x0a], headerStart);
        if (headerEndIdx === -1) break;
        const headerStr = decoder.decode(bytes.slice(headerStart, headerEndIdx));
        const nameMatch = headerStr.match(/name="([^"]+)"/);
        const filenameMatch = headerStr.match(/filename="([^"]+)"/);
        const mimeMatch = headerStr.match(/Content-Type:\s*([^\r\n]+)/i);
        if (!nameMatch) break;
        const name = nameMatch[1];
        let dataStart = headerEndIdx + 4;
        const nextIdx = indexOf(bytes, boundaryBytes, dataStart);
        if (nextIdx === -1) break;
        let dataEnd = nextIdx;
        if (bytes[dataEnd - 1] === 0x0a) dataEnd--;
        if (bytes[dataEnd - 1] === 0x0d) dataEnd--;
        const data = bytes.slice(dataStart, dataEnd);
        if (filenameMatch) {
            parts[name] = { filename: filenameMatch[1], mime: mimeMatch ? mimeMatch[1].trim() : 'application/octet-stream', data: data.buffer.slice(data.byteOffset, data.byteOffset + data.byteLength) };
        } else {
            parts[name] = decoder.decode(data);
        }
        pos = nextIdx;
    }
    return parts;
}

// ═══════════════════════════════════════════════════════════
// RAG Embedding Engine (v2.1)
// ═══════════════════════════════════════════════════════════

const EMBED_DIM = 384;

function md5Hex(str) {
    let h1 = 0xdeadbeef, h2 = 0x41c6ce57;
    for (let i = 0; i < str.length; i++) {
        const ch = str.charCodeAt(i);
        h1 = Math.imul(h1 ^ ch, 2654435761);
        h2 = Math.imul(h2 ^ ch, 1597334677);
    }
    const hex1 = (h1 >>> 0).toString(16).padStart(8, '0');
    const hex2 = (h2 >>> 0).toString(16).padStart(8, '0');
    return (hex1 + hex2 + hex1 + hex2 + hex1 + hex2 + hex1 + hex2).substr(0, 32);
}

function _hashToken(token, dim) {
    const vec = new Array(dim).fill(0);
    for (let seed = 0; seed < 4; seed++) {
        const h = md5Hex(seed + ':' + token);
        for (let i = 0; i < h.length; i += 2) {
            const idx = parseInt(h.substr(i, 2), 16) % dim;
            const val = parseInt(h[i], 16) < 8 ? 1.0 : -1.0;
            vec[idx] += val;
        }
    }
    return vec;
}

function embedText(text, dim = EMBED_DIM) {
    if (!text || !text.trim()) return new Array(dim).fill(0);
    const tokens = text.toLowerCase().match(/[一-鿿]|[a-z0-9]+/g) || [];
    if (tokens.length === 0) return new Array(dim).fill(0);
    const vec = new Array(dim).fill(0);
    const counts = {};
    for (const t of tokens) counts[t] = (counts[t] || 0) + 1;
    for (const [token, count] of Object.entries(counts)) {
        const tv = _hashToken(token, dim);
        const w = 1.0 + Math.log(count + 1);
        for (let i = 0; i < dim; i++) vec[i] += tv[i] * w;
    }
    let norm = 0;
    for (const v of vec) norm += v * v;
    norm = Math.sqrt(norm);
    if (norm > 0) for (let i = 0; i < dim; i++) vec[i] /= norm;
    return vec;
}

function cosineSim(a, b) {
    if (a.length !== b.length) return 0;
    let dot = 0, na = 0, nb = 0;
    for (let i = 0; i < a.length; i++) { dot += a[i]*b[i]; na += a[i]*a[i]; nb += b[i]*b[i]; }
    return (na === 0 || nb === 0) ? 0 : dot / (Math.sqrt(na) * Math.sqrt(nb));
}

function chunkText(text, chunkSize = 500, overlapPct = 0.2) {
    if (!text.trim()) return [];
    const paras = text.includes('\n\n') ? text.split('\n\n').map(s=>s.trim()).filter(Boolean) : text.split(/(?<=[。！？.!?])\s*/g).filter(s=>s.trim());
    const chunks = []; let cur = ''; let idx = 0;
    for (const p of paras) {
        if (p.length > chunkSize) {
            if (cur) { chunks.push({content:cur.trim(),index:idx++}); cur = cur.slice(-Math.floor(cur.length*overlapPct)); }
            const sents = p.split(/(?<=[。！？.!?])\s*/g).filter(s=>s.trim());
            for (const s of sents) {
                if (cur.length+s.length+1>chunkSize&&cur) { chunks.push({content:cur.trim(),index:idx++}); cur = cur.slice(-Math.floor(cur.length*overlapPct)); }
                cur += (cur?' ':'')+s;
            }
            continue;
        }
        if (cur.length+p.length+2>chunkSize&&cur) { chunks.push({content:cur.trim(),index:idx++}); cur = cur.slice(-Math.floor(cur.length*overlapPct)); }
        cur += (cur?'\n\n':'')+p;
    }
    if (cur.trim()) chunks.push({content:cur.trim(),index:idx});
    return chunks;
}

function extractText(bytes, ext) {
    return new TextDecoder('utf-8').decode(bytes);
}

// ── RAG Routes ──

// POST /v1/files/upload
route('POST', '/v1/files/upload', async (req, _match, env) => {
    try {
        const ct = req.headers.get('content-type') || '';
        if (!ct.includes('multipart/form-data')) return error('Expected multipart/form-data', 400);
        const boundary = ct.split('boundary=')[1];
        if (!boundary) return error('Missing boundary', 400);
        const userId = req.headers.get('X-User-ID') || 'anonymous';
        const raw = await req.arrayBuffer();
        const parts = parseMultipart(raw, boundary);
        if (!parts.file) return error('No file field', 400);
        const fileBytes = new Uint8Array(parts.file.data);
        const fileName = parts.file.filename || 'unknown';
        const ext = fileName.includes('.') ? fileName.split('.').pop().toLowerCase() : '';
        if (!['pdf','docx','txt','md'].includes(ext)) return error('Unsupported type: '+ext, 400);
        if (fileBytes.length > 5*1024*1024) return error('File too large', 413);
        const fileId = genUUID();
        const now = utcNow();
        let rawText = extractText(fileBytes, ext) || '';
        if (!rawText.trim()) {
            await env.DB.prepare('INSERT INTO file_uploads (id,filename,file_type,size,user_id,status,error_message,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)')
                .bind(fileId,fileName,ext,String(fileBytes.length),userId,'error','No text extracted',now,now).run();
            return error('Could not extract text', 422);
        }
        const chunks = chunkText(rawText);
        await env.DB.prepare('INSERT INTO file_uploads (id,filename,file_type,size,user_id,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)')
            .bind(fileId,fileName,ext,String(fileBytes.length),userId,'ready',now,now).run();
        for (let i = 0; i < chunks.length; i++) {
            const emb = embedText(chunks[i].content);
            const chunkId = genUUID();
            await env.DB.prepare('INSERT INTO file_chunks (id,file_id,content,"index",embedding,created_at) VALUES (?,?,?,?,?,?)')
                .bind(chunkId,fileId,chunks[i].content,String(i),JSON.stringify(emb),now).run();
        }
        return json({file_id:fileId,filename:fileName,file_type:ext,size:fileBytes.length,user_id:userId,status:'ready',chunk_count:chunks.length,message:'File uploaded, '+chunks.length+' chunks created'}, 201);
    } catch(e) { return json({error:e.message}, 500); }
});

// POST /v1/files/query
route('POST', '/v1/files/query', async (req, _match, env) => {
    try {
        const data = await req.json();
        const query = data.query || '';
        const topK = Math.min(data.top_k || 5, 50);
        const fileId = data.file_id || null;
        const userId = req.headers.get('X-User-ID') || 'anonymous';
        if (!query.trim()) return error('Query required', 400);
        let rows;
        if (fileId) {
            rows = await env.DB.prepare('SELECT fc.id, fc.file_id, fc.content, fc."index", fu.user_id, fc.embedding FROM file_chunks fc JOIN file_uploads fu ON fc.file_id = fu.id WHERE fc.file_id = ? AND fu.user_id = ?').bind(fileId, userId).all();
        } else {
            rows = await env.DB.prepare('SELECT fc.id, fc.file_id, fc.content, fc."index", fu.user_id, fc.embedding FROM file_chunks fc JOIN file_uploads fu ON fc.file_id = fu.id WHERE fu.user_id = ?').bind(userId).all();
        }
        const qEmb = embedText(query);
        const results = [];
        for (const row of (rows.results||[])) {
            if (!row.embedding) continue;
            const chunkEmb = JSON.parse(row.embedding);
            const score = cosineSim(qEmb, chunkEmb);
            results.push({chunk_id:row.id,file_id:row.file_id,content:row.content,score:Math.round(score*10000)/10000,index:parseInt(row.index)||0});
        }
        results.sort((a,b)=>b.score-a.score);
        return json({results:results.slice(0,topK),query,total_found:results.length,latency_ms:Date.now()-0});
    } catch(e) { return json({error:e.message, stack:e.stack}, 500); }
});

// POST /v1/files/context
route('POST', '/v1/files/context', async (req, _match, env) => {
    try {
        const data = await req.json();
        const query = data.query || '';
        const topK = Math.min(data.top_k || 3, 10);
        const userId = req.headers.get('X-User-ID') || 'anonymous';
        if (!query.trim()) return error('Query required', 400);
        const rows = await env.DB.prepare('SELECT fc.id, fc.file_id, fc.content, fc."index", fu.user_id, fc.embedding FROM file_chunks fc JOIN file_uploads fu ON fc.file_id = fu.id WHERE fu.user_id = ?').bind(userId).all();
        const qEmb = embedText(query);
        const results = [];
        for (const row of (rows.results||[])) {
            if (!row.embedding) continue;
            results.push({chunk_id:row.id,file_id:row.file_id,content:row.content,score:Math.round(cosineSim(qEmb,JSON.parse(row.embedding))*10000)/10000});
        }
        results.sort((a,b)=>b.score-a.score);
        const top = results.slice(0,topK);
        const ctx = top.map((r,i)=>'[Source '+(i+1)+'] '+r.content).join('\n\n');
        return json({context:ctx,sources:top.map(r=>({file_id:r.file_id,chunk_id:r.chunk_id,score:r.score})),query,token_count:Math.ceil(ctx.length/3)});
    } catch(e) { return json({error:e.message}, 500); }
});

// GET /v1/files
route('GET', '/v1/files', async (req, _match, env) => {
    const userId = req.headers.get('X-User-ID') || 'anonymous';
    const rows = await env.DB.prepare('SELECT id,filename,file_type,size,status,created_at FROM file_uploads WHERE user_id=? ORDER BY created_at DESC').bind(userId).all();
    return json({files:rows.results||[],total:(rows.results||[]).length});
});

// GET /v1/files/:id
route('GET', '/v1/files/:id', async (req, match, env) => {
    const fileId = match[1];
    const userId = req.headers.get('X-User-ID') || 'anonymous';
    const f = await env.DB.prepare('SELECT * FROM file_uploads WHERE id=? AND user_id=?').bind(fileId,userId).first();
    if (!f) return error('File not found', 404);
    const chunks = await env.DB.prepare('SELECT id,"index",substr(content,1,100) as preview FROM file_chunks WHERE file_id=? ORDER BY "index"').bind(fileId).all();
    return json({file_id:f.id,filename:f.filename,file_type:f.file_type,size:parseInt(f.size),user_id:f.user_id,status:f.status,chunk_count:(chunks.results||[]).length,chunks:chunks.results||[],created_at:f.created_at});
});

// DELETE /v1/files/:id
route('DELETE', '/v1/files/:id', async (req, match, env) => {
    const fileId = match[1];
    const userId = req.headers.get('X-User-ID') || 'anonymous';
    const f = await env.DB.prepare('SELECT id FROM file_uploads WHERE id=? AND user_id=?').bind(fileId,userId).first();
    if (!f) return error('File not found', 404);
    await env.DB.prepare('DELETE FROM file_chunks WHERE file_id=?').bind(fileId).run();
    await env.DB.prepare('DELETE FROM file_uploads WHERE id=?').bind(fileId).run();
    return json({status:'ok',file_id:fileId});
});

// POST /v1/agent/chat-with-files
route('POST', '/v1/agent/chat-with-files', async (req, _match, env) => {
    try {
        const start = Date.now();
        const data = await req.json();
        const message = data.message || '';
        const topK = Math.min(data.top_k || 3, 10);
        const fileId = data.file_id || null;
        const userId = req.headers.get('X-User-ID') || 'anonymous';
        if (!message.trim()) return error('Message required', 400);
        let ctx = '', sources = [], used = false;
        let rows;
        if (fileId) {
            rows = await env.DB.prepare('SELECT fc.id,fc.file_id,fc.content,fc."index",fu.user_id,fc.embedding FROM file_chunks fc JOIN file_uploads fu ON fc.file_id=fu.id WHERE fc.file_id=? AND fu.user_id=?').bind(fileId,userId).all();
        } else {
            rows = await env.DB.prepare('SELECT fc.id,fc.file_id,fc.content,fc."index",fu.user_id,fc.embedding FROM file_chunks fc JOIN file_uploads fu ON fc.file_id=fu.id WHERE fu.user_id=?').bind(userId).all();
        }
        if (rows.results && rows.results.length > 0) {
            const qEmb = embedText(message);
            const scored = [];
            for (const row of rows.results) {
                if (!row.embedding) continue;
                scored.push({chunk_id:row.id,file_id:row.file_id,content:row.content,score:Math.round(cosineSim(qEmb,JSON.parse(row.embedding))*10000)/10000});
            }
            scored.sort((a,b)=>b.score-a.score);
            const top = scored.slice(0,topK);
            if (top.length > 0) {
                ctx = top.map((r,i)=>'[Source '+(i+1)+'] '+r.content).join('\n\n');
                sources = top.map(r=>({file_id:r.file_id,chunk_id:r.chunk_id,score:r.score}));
                used = true;
            }
        }
        let prompt = message;
        if (ctx) prompt = 'CONTEXT:\n'+ctx+'\n\nQUESTION:\n'+message+'\n\nBased on the context above, provide a helpful answer.';
        const provider = data.provider || 'openrouter';
        const model = data.model || 'openrouter/auto';
        const apiKeyRow = await env.DB.prepare('SELECT * FROM apikeys WHERE provider=? LIMIT 1').bind(provider).first();
        if (!apiKeyRow) return error('No API key for '+provider, 401);
        const r = await callAgent('executor',{task:prompt,roleContext:'User question with file context',expectedOutput:'Answer based on context'},apiKeyRow.api_key,provider,model,apiKeyRow.base_url);
        return json({session_id:crypto.randomUUID().slice(0,8),status:r.status==='success'?'ok':'error',response:r.result||r.error||'',context_used:used,sources,latency:Date.now()-start+'ms',message:used?'RAG context retrieved':'No file context found'});
    } catch(e) { return json({error:e.message}, 500); }
});

// ═══════════════════════════════════════════════════════════

// Cloudflare Workers — ES Module format
export default {
    async fetch(request, env) {
        const result = await handleRequest(request, env);
        // If Worker returned a route match, use it
        if (result) return result;
        // Otherwise, fall through to static assets (frontend)
        if (env.ASSETS) return env.ASSETS.fetch(request);
        return new Response('Not Found', { status: 404 });
    }
};
