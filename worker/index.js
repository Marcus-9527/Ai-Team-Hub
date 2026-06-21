/**
 * AI Team Hub v2.3 — Cloudflare Workers (全托管 Serverless)
 *
 * v2.3 修复:
 * 1. Information Flow Validation Layer — 每跳验证 input_used / decision_influenced / diff_from_previous
 * 2. Recovery System — error → classify → retry / fallback / degrade mode
 * 3. Cognitive Diversity Amplifier — reasoning constraint + perspective forcing + entropy injection
 */

// ═══════════════════════════════════════════
// ① Information Flow Validation Layer
// ═══════════════════════════════════════════

function validateInformationFlow(currentOutput, previousOutput, agentRole, currentReasoning) {
  const prevKeywords = extractKeywords(previousOutput);
  const currKeywords = extractKeywords(currentOutput);
  const inputUsed = prevKeywords.some(kw => currentOutput.includes(kw));
  const diff = computeDiff(previousOutput, currentOutput);
  const decisionInfluenced = diff > 0.1;
  const threshold = agentRole === 'executor' ? 0.15 : 0.37;
  const validationPassed = inputUsed && decisionInfluenced && diff > threshold;
  let failureReason = '';
  if (!inputUsed) failureReason = `input_not_used: ${agentRole} 未引用上游输出`;
  else if (!decisionInfluenced) failureReason = 'decision_not_influenced';
  else if (diff <= threshold) failureReason = `diff_too_low: ${diff.toFixed(2)} < ${threshold}`;
  return { inputUsed, decisionInfluenced, diffFromPrevious: diff, validationPassed, failureReason };
}

function extractKeywords(text) {
  const stopWords = ['的', '是', '在', '了', '和', '与', '或', 'the', 'a', 'an', 'is', 'are', 'to', 'of', 'in', 'for', 'on'];
  const words = text.toLowerCase().split(/\s+/).filter(w => w.length > 2 && !stopWords.includes(w));
  return [...new Set(words)].slice(0, 20);
}

function computeDiff(a, b) {
  const setA = new Set(a.toLowerCase().split(/\s+/));
  const setB = new Set(b.toLowerCase().split(/\s+/));
  const intersection = new Set([...setA].filter(x => setB.has(x)));
  const union = new Set([...setA, ...setB]);
  return union.size === 0 ? 0 : 1 - (intersection.size / union.size);
}

function extractPlanItemNames(planOutput) {
  try {
    const jsonMatch = planOutput.match(/\[.*\]/s);
    if (jsonMatch) {
      const items = JSON.parse(jsonMatch[0]);
      return items.map(item => item.name || item.description || '').filter(Boolean);
    }
  } catch {}
  return [];
}

function extractCodeSymbols(codeOutput) {
  const symbols = [];
  const classMatches = codeOutput.matchAll(/class\s+(\w+)/g);
  for (const m of classMatches) symbols.push(m[1]);
  const defMatches = codeOutput.matchAll(/def\s+(\w+)/g);
  for (const m of defMatches) symbols.push(m[1]);
  const importMatches = codeOutput.matchAll(/import\s+(\w+)/g);
  for (const m of importMatches) symbols.push(m[1]);
  return [...new Set(symbols)].slice(0, 15);
}

// ═══════════════════════════════════════════
// ② Recovery System
// ═══════════════════════════════════════════

function decideRecovery(errorCategory, attempt, maxRetries, agentId, previousResults) {
  if (errorCategory === 'auth' || errorCategory === 'format') {
    const fallbackMap = { planner: 'executor', executor: 'planner', reviewer: 'executor', researcher: 'planner' };
    const fallback = fallbackMap[agentId];
    if (fallback && !previousResults[fallback]) {
      return { action: 'fallback', reason: `${agentId} failed, fallback to ${fallback}`, fallbackAgent: fallback };
    }
    return { action: 'degrade', reason: `${agentId} failed, no fallback`, degradeMode: 'partial_output' };
  }
  if (errorCategory === 'rate_limit' || errorCategory === 'timeout') {
    if (attempt < maxRetries - 1) {
      return { action: 'retry', reason: `${errorCategory}, retrying`, retryDelay: (errorCategory === 'rate_limit' ? 5000 : 2000) * Math.pow(2, attempt) };
    }
    return { action: 'degrade', reason: `${errorCategory} retries exhausted`, degradeMode: 'best_effort' };
  }
  if (errorCategory === 'network') {
    if (attempt < 1) return { action: 'retry', reason: 'network error', retryDelay: 3000 };
    return { action: 'degrade', reason: 'network retries exhausted', degradeMode: 'cached_response' };
  }
  if (attempt < 1) return { action: 'retry', reason: 'unknown error', retryDelay: 2000 };
  return { action: 'stop', reason: 'unknown error retries exhausted' };
}

// ═══════════════════════════════════════════
// ③ Cognitive Diversity Amplifier
// ═══════════════════════════════════════════

function generateCognitiveConstraint(agentId, taskDescription) {
  const hash = hashString(taskDescription).slice(0, 8);
  const constraints = {
    planner: {
      reasoningConstraint: '推理约束：使用"逆向工程法"——从最终目标倒推，不允许正向规划。',
      perspectiveForcing: '视角强制：你是"完美主义者"PM，对每个子任务问"如果这个环节失败了怎么办"。',
      entropyInjection: `熵注入：拆解时必须包含一个"反直觉子任务"。任务哈希: ${hash}`,
    },
    executor: {
      reasoningConstraint: '推理约束：使用"测试驱动法"——先写测试用例，再写实现代码。',
      perspectiveForcing: '视角强制：你是"安全偏执狂"工程师，对每行代码问"这里会被怎么攻击"。',
      entropyInjection: `熵注入：实现时必须使用一种"非主流"方式。任务哈希: ${hash}`,
    },
    reviewer: {
      reasoningConstraint: '推理约束：使用"红队思维"——假设代码中有 3 个隐藏 bug，你的任务是找到它们。',
      perspectiveForcing: '视角强制：你是"用户体验极端主义者"，从最差用户的角度评审。',
      entropyInjection: `熵注入：评审时必须提出一个"违反直觉的改进建议"。任务哈希: ${hash}`,
    },
    researcher: {
      reasoningConstraint: '推理约束：使用"第一性原理"——不接受"业界标准"作为理由。',
      perspectiveForcing: '视角强制：你是"技术怀疑论者"，对每个方案问"如果这个技术明天就过时了怎么办"。',
      entropyInjection: `熵注入：调研中必须包含一个"冷门方案"。任务哈希: ${hash}`,
    },
  };
  return constraints[agentId] || { reasoningConstraint: '使用批判性思维', perspectiveForcing: '从反对者角度审视', entropyInjection: `包含反直觉观点。哈希: ${hash}` };
}

function hashString(str) {
  let hash = 0;
  for (let i = 0; i < str.length; i++) { hash = ((hash << 5) - hash) + str.charCodeAt(i); hash = hash & hash; }
  return Math.abs(hash).toString(16);
}

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

// ═══════════════════════════════════════════
// Helpers
// ═══════════════════════════════════════════

function genUUID() { return crypto.randomUUID(); }
function utcNow() { return new Date().toISOString(); }
function json(data, status = 200) { return new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } }); }
function error(message, status = 400) { return json({ detail: message }, status); }
function setCors(r) { r.headers.set('Access-Control-Allow-Origin', '*'); r.headers.set('Access-Control-Allow-Methods', 'GET,POST,PUT,PATCH,DELETE,OPTIONS'); r.headers.set('Access-Control-Allow-Headers', 'Content-Type'); return r; }
function corsResponse() { return new Response(null, { status: 204, headers: { 'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Methods': 'GET,POST,PUT,PATCH,DELETE,OPTIONS', 'Access-Control-Allow-Headers': 'Content-Type', 'Access-Control-Max-Age': '86400' } }); }

const PROVIDER_ENDPOINTS = {
  openai: 'https://api.openai.com/v1/chat/completions',
  anthropic: 'https://api.anthropic.com/v1/messages',
  google: 'https://generativelanguage.googleapis.com/v1beta/openai/chat/completions',
  deepseek: 'https://api.deepseek.com/v1/chat/completions',
  openrouter: 'https://openrouter.ai/api/v1/chat/completions',
};

function getEndpoint(provider, baseUrl) {
  if (baseUrl) return baseUrl.includes('/responses') ? baseUrl : `${baseUrl.replace(/\/$/, '')}/v1/chat/completions`;
  return PROVIDER_ENDPOINTS[provider] || `https://api.${provider}.com/v1/chat/completions`;
}

function classifyError(httpCode, message) {
  const msg = message.toLowerCase();
  if (httpCode === 429 || msg.includes('rate limit')) return { category: 'rate_limit', httpCode, message, retryable: true, retryDelay: 5000 };
  if (httpCode === 401 || httpCode === 403 || msg.includes('auth') || msg.includes('unauthorized')) return { category: 'auth', httpCode, message, retryable: false, retryDelay: 0 };
  if (httpCode === 408 || httpCode === 504 || msg.includes('timeout')) return { category: 'timeout', httpCode, message, retryable: true, retryDelay: 3000 };
  if (httpCode >= 500) return { category: 'network', httpCode, message, retryable: true, retryDelay: 2000 };
  if (httpCode >= 400) return { category: 'network', httpCode, message, retryable: false, retryDelay: 0 };
  return { category: 'unknown', httpCode, message, retryable: true, retryDelay: 2000 };
}

// ═══════════════════════════════════════════
// Agent Definitions v2.3
// ═══════════════════════════════════════════

const AGENT_DEFINITIONS = {
  planner: {
    role: 'planner',
    systemPrompt: `[ROLE LOCK — PLANNER ONLY]
你是任务拆解专家。唯一职责：将复杂任务分解为可执行子任务。
严格规则：只输出任务拆解方案（JSON），不写代码、不做分析、不做决策。
[COGNITIVE CONSTRAINT — 逆向工程法] 从最终目标倒推，不允许正向规划。
[PERSPECTIVE FORCING — 完美主义者PM] 对每个子任务问"如果失败了怎么办"。
[ENTROPY INJECTION] 必须包含一个"反直觉子任务"。
输出: {"status":"success","result":"[子任务列表]","reasoning":"[为什么这样拆解]","next_action":"[下一步]"}`,
    tools: ['decompose'],
  },
  executor: {
    role: 'executor',
    systemPrompt: `[ROLE LOCK — EXECUTOR ONLY]
你是代码执行专家。唯一职责：根据 Planner 的拆解方案编写可运行代码。
严格规则：只输出代码（JSON，result字段=完整代码），不做分析、不写调研。
[CRITICAL] 代码 MUST 包含 Planner 拆解方案中的所有子任务。reasoning 中列出引用的子任务。
[COGNITIVE CONSTRAINT — 测试驱动法] 先写测试用例，再写实现代码。
[PERSPECTIVE FORCING — 安全偏执狂] 对每行代码问"这里会被怎么攻击"。
[ENTROPY INJECTION] 必须使用一种"非主流"实现方式。
输出: {"status":"success","result":"[完整代码]","reasoning":"[引用了哪些子任务]","next_action":"[等待审查]"}`,
    tools: ['code_exec', 'test'],
  },
  reviewer: {
    role: 'reviewer',
    systemPrompt: `[ROLE LOCK — REVIEWER ONLY]
你是代码评审专家。唯一职责：评审代码质量、安全性、完整性。
严格规则：只输出评审结果（JSON），不写代码、不改代码。
[CRITICAL] 评审 MUST 检查代码是否实现了所有子任务。reasoning 中列出检查了哪些子任务。
[COGNITIVE CONSTRAINT — 红队思维] 假设代码中有 3 个隐藏 bug。
[PERSPECTIVE FORCING — 用户体验极端主义者] 从最差用户角度评审。
[ENTROPY INJECTION] 必须提出一个"违反直觉的改进建议"。
输出: {"status":"success","result":"[pass/fail, 问题列表]","reasoning":"[评审依据]","next_action":"[通过则完成，不通过则修改]"}`,
    tools: ['code_review', 'evaluate'],
  },
  researcher: {
    role: 'researcher',
    systemPrompt: `[ROLE LOCK — RESEARCHER ONLY]
你是技术调研专家。唯一职责：调研现有方案、技术选型、最佳实践。
严格规则：只输出调研报告（JSON），不写代码、不做决策。
[CRITICAL] 调研 MUST 直接针对原始任务需求。reasoning 中说明如何服务于原始任务。
[COGNITIVE CONSTRAINT — 第一性原理] 不接受"业界标准"作为理由。
[PERSPECTIVE FORCING — 技术怀疑论者] 对每个方案问"如果明天就过时了怎么办"。
[ENTROPY INJECTION] 必须包含一个"冷门方案"。
输出: {"status":"success","result":"[方案对比、优缺点]","reasoning":"[调研方法论]","next_action":"[调研完成]"}`,
    tools: ['web_search', 'analyze'],
  },
};

// ═══════════════════════════════════════════
// Agent Runtime v2.3
// ═══════════════════════════════════════════

async function callAgent(agentId, input, apiKey, provider, model, baseUrl) {
  const start = Date.now();
  const def = AGENT_DEFINITIONS[agentId];
  if (!def) return { agentId, status: 'error', result: '', reasoning: '', nextAction: '', tokensUsed: 0, latencyMs: 0, error: `Unknown agent: ${agentId}` };

  // v2.3: Inject cognitive constraints
  const cognitive = generateCognitiveConstraint(agentId, input.task);
  const enhancedTask = input.task + '\n' + cognitive.reasoningConstraint + '\n' + cognitive.perspectiveForcing + '\n' + cognitive.entropyInjection;

  const prompt = [
    def.systemPrompt, '',
    '[YOUR TASK]', enhancedTask, '',
    '[EXPECTED OUTPUT]', input.expectedOutput, '',
    '[ROLE CONTEXT]', input.roleContext, '',
    '[OUTPUT FORMAT]', '{"status":"success","result":"[output]","reasoning":"[reasoning]","next_action":"[next]"}', '',
    '[KILL SWITCH] 无法完成 → {"status":"error","result":"","reasoning":"[原因]","next_action":"stop"}',
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
  } else if (isResponsesApi) {
    headers['Authorization'] = `Bearer ${apiKey}`;
    payload = { model, input: prompt, stream: false, temperature: 0.7, max_tokens: 4096 };
  } else {
    headers['Authorization'] = `Bearer ${apiKey}`;
    payload = { model, messages: [{ role: 'system', content: def.systemPrompt }, { role: 'user', content: prompt }], stream: false, temperature: 0.7, max_tokens: 4096 };
  }

  const maxRetries = 3;
  for (let attempt = 0; attempt < maxRetries; attempt++) {
    try {
      const res = await fetch(endpoint, { method: 'POST', headers, body: JSON.stringify(payload) });
      if (!res.ok) {
        const text = await res.text();
        const classified = classifyError(res.status, text);
        if (!classified.retryable || attempt >= maxRetries - 1) {
          return { agentId, status: 'error', result: '', reasoning: '', nextAction: '', tokensUsed: 0, latencyMs: Date.now() - start, error: `${classified.category}(${classified.httpCode}): ${text.slice(0, 200)}`, errorCategory: classified.category, retryCount: attempt };
        }
        await sleep(classified.retryDelay * Math.pow(2, attempt));
        continue;
      }
      const r = await res.json();
      let full = '';
      if (r.choices?.[0]?.message?.content) full = r.choices[0].message.content;
      else if (r.output?.[0]?.content?.[0]?.text) full = r.output[0].content[0].text;
      const parsed = parseAgentJson(full);
      return { agentId, status: parsed.status, result: parsed.result, reasoning: parsed.reasoning, nextAction: parsed.nextAction, tokensUsed: (prompt.length + full.length) / 4, latencyMs: Date.now() - start, error: parsed.status === 'error' ? 'Agent error' : '', retryCount: attempt };
    } catch (e) {
      const classified = classifyError(0, e.message);
      if (!classified.retryable || attempt >= maxRetries - 1) {
        return { agentId, status: 'error', result: '', reasoning: '', nextAction: '', tokensUsed: 0, latencyMs: Date.now() - start, error: `${classified.category}: ${e.message}`, errorCategory: classified.category, retryCount: attempt };
      }
      await sleep(classified.retryDelay * Math.pow(2, attempt));
    }
  }
  return { agentId, status: 'error', result: '', reasoning: '', nextAction: '', tokensUsed: 0, latencyMs: Date.now() - start, error: 'Max retries exceeded', retryCount: maxRetries };
}

function parseAgentJson(text) {
  if (!text || !text.trim()) return { status: 'error', result: '', reasoning: 'Empty response', nextAction: 'retry' };
  try { const obj = JSON.parse(text); if (obj.status && obj.result !== undefined) return normalizeResult(obj); } catch {}
  let cleaned = text.trim();
  if (cleaned.startsWith('```')) { cleaned = cleaned.split('\n').filter(l => !l.trim().startsWith('```')).join('\n').trim(); }
  try { const obj = JSON.parse(cleaned); if (obj.status) return normalizeResult(obj); } catch {}
  const s = cleaned.indexOf('{'), e = cleaned.lastIndexOf('}');
  if (s >= 0 && e > s) { try { const obj = JSON.parse(cleaned.slice(s, e + 1)); if (obj.status) return normalizeResult(obj); } catch {} }
  return { status: 'success', result: text, reasoning: '', nextAction: 'continue' };
}

function normalizeResult(obj) {
  return { status: obj.status || 'success', result: obj.result || obj.output || obj.text || obj.content || '', reasoning: obj.reasoning || obj.thought || obj.explanation || '', nextAction: obj.next_action || obj.nextAction || obj.next || 'continue' };
}

// ═══════════════════════════════════════════
// DAG Engine v2.3
// ═══════════════════════════════════════════

class DAGEngine {
  nodes = new Map();
  edges = [];
  results = new Map();
  _killed = false;
  _degradeMode = false;

  addNode(node) { this.nodes.set(node.id, node); }
  addEdge(from, to) { this.edges.push([from, to]); }

  _buildAgentInput(node, ctx, previousOutput) {
    const roleMap = { planner: `原始任务：${ctx.originalTask}`, executor: `上游 Planner 方案：${previousOutput}`, researcher: `原始任务：${ctx.originalTask}`, reviewer: `待评审代码：${previousOutput.slice(0, 2000)}` };
    const outputMap = { planner: '任务拆解方案（JSON）', executor: '可运行代码（JSON）', researcher: '调研报告（JSON）', reviewer: '评审结果（JSON）' };
    return { task: node.taskDescription, roleContext: roleMap[node.agentId] || `任务：${node.taskDescription}`, expectedOutput: outputMap[node.agentId] || 'JSON' };
  }

  async execute(ctx) {
    this.results = new Map(); this._killed = false; this._degradeMode = false;
    const { adj, inDeg } = this._buildGraph();
    const layers = this._topoLayers(adj, inDeg);
    for (const layer of layers) {
      if (this._killed) { for (const n of layer) this.results.set(n, { nodeId: n, agentId: this.nodes.get(n).agentId, status: 'killed', result: '', error: 'DAG killed', latencyMs: 0, retries: 0 }); continue; }
      const tasks = layer.map(nodeId => {
        const node = this.nodes.get(nodeId);
        const depsOk = node.dependencies.every(d => this.results.get(d)?.status === 'success');
        if (!depsOk) { this.results.set(nodeId, { nodeId, agentId: node.agentId, status: 'skipped', result: '', error: 'Dependencies not met', latencyMs: 0, retries: 0 }); return Promise.resolve(); }
        const prevOutput = node.dependencies.length > 0 ? (this.results.get(node.dependencies[node.dependencies.length - 1])?.result || '') : '';
        return this._execNode(node, this._buildAgentInput(node, ctx, prevOutput), ctx, prevOutput);
      });
      await Promise.all(tasks);
    }
    return this.results;
  }

  async _execNode(node, input, ctx, previousOutput) {
    const start = Date.now();
    for (let attempt = 0; attempt < node.retryCount; attempt++) {
      const r = await callAgent(node.agentId, input, ctx.apiKey, ctx.provider, ctx.model, ctx.baseUrl);
      let flowValidation;
      if (r.status === 'success' && previousOutput) {
        flowValidation = validateInformationFlow(r.result, previousOutput, node.agentId, r.reasoning);
        if (!flowValidation.validationPassed) {
          this.results.set(node.id, { nodeId: node.id, agentId: node.agentId, status: 'flow_validation_failed', result: r.result, error: flowValidation.failureReason, latencyMs: Date.now() - start, retries: attempt, flowValidation });
          this._killed = true; return;
        }
      }
      this.results.set(node.id, { nodeId: node.id, agentId: node.agentId, status: r.status, result: r.result, error: r.error, errorCategory: r.errorCategory, latencyMs: r.latencyMs, retries: attempt, flowValidation });
      if (r.status === 'success') return;
      // v2.3: Recovery System
      const recovery = decideRecovery(r.errorCategory || 'unknown', attempt, node.retryCount, node.agentId, Object.fromEntries(this.results.entries()));
      if (recovery.action === 'retry') { await sleep(recovery.retryDelay || 2000); continue; }
      if (recovery.action === 'fallback' && recovery.fallbackAgent) {
        const fallbackResult = await callAgent(recovery.fallbackAgent, { task: `[FALLBACK] ${input.task}`, roleContext: input.roleContext, expectedOutput: input.expectedOutput }, ctx.apiKey, ctx.provider, ctx.model, ctx.baseUrl);
        this.results.set(node.id, { nodeId: node.id, agentId: recovery.fallbackAgent, status: fallbackResult.status, result: fallbackResult.result, error: fallbackResult.error, latencyMs: Date.now() - start, retries: attempt, recoveryAction: 'fallback' });
        if (fallbackResult.status === 'success') return;
      }
      if (recovery.action === 'degrade') { this._degradeMode = true; this.results.set(node.id, { ...this.results.get(node.id), status: 'degraded', error: recovery.reason, recoveryAction: 'degrade' }); return; }
      if (recovery.action === 'stop') { this._killed = true; return; }
    }
  }

  _buildGraph() {
    const adj = new Map(), inDeg = new Map();
    for (const id of this.nodes.keys()) { inDeg.set(id, 0); adj.set(id, []); }
    for (const [from, to] of this.edges) { if (this.nodes.has(from) && this.nodes.has(to)) { adj.get(from).push(to); inDeg.set(to, (inDeg.get(to) || 0) + 1); } }
    return { adj, inDeg };
  }

  _topoLayers(adj, inDeg) {
    const deg = new Map(inDeg);
    let queue = [...deg.entries()].filter(([, d]) => d === 0).map(([n]) => n);
    const layers = [];
    while (queue.length > 0) {
      layers.push([...queue]);
      const next = [];
      for (const id of queue) { for (const nb of adj.get(id) || []) { deg.set(nb, deg.get(nb) - 1); if (deg.get(nb) === 0) next.push(nb); } }
      queue = next;
    }
    return layers;
  }
}

// ═══════════════════════════════════════════
// Orchestrator v2.3
// ═══════════════════════════════════════════

function classifyIntent(task) {
  const t = task.toLowerCase();
  if (/代码|code|编程|函数|class|debug|修复/.test(t)) return 'code';
  if (/分析|analyze|数据|趋势|统计/.test(t)) return 'analysis';
  if (/推理|reasoning|为什么|原因|解释/.test(t)) return 'reasoning';
  return 'complex';
}

function getAgentsForIntent(intent) {
  const rules = { analysis: ['planner', 'researcher', 'reviewer'], code: ['planner', 'executor', 'reviewer'], reasoning: ['planner', 'researcher'], complex: ['planner', 'researcher', 'executor', 'reviewer'] };
  return rules[intent] || ['planner'];
}

function buildDag(intent, task) {
  const dag = new DAGEngine();
  if (intent === 'code') {
    dag.addNode({ id: 'plan', agentId: 'planner', taskDescription: `分析需求并制定执行计划：${task}`, dependencies: [], retryCount: 3, timeout: 120 });
    dag.addNode({ id: 'code', agentId: 'executor', taskDescription: `根据 plan 方案编写代码：${task}`, dependencies: ['plan'], retryCount: 3, timeout: 120 });
    dag.addNode({ id: 'review', agentId: 'reviewer', taskDescription: `评审 code 输出的代码：${task}`, dependencies: ['code'], retryCount: 3, timeout: 120 });
    dag.addEdge('plan', 'code'); dag.addEdge('code', 'review');
  } else if (intent === 'analysis') {
    dag.addNode({ id: 'plan', agentId: 'planner', taskDescription: `制定分析计划：${task}`, dependencies: [], retryCount: 3, timeout: 120 });
    dag.addNode({ id: 'research', agentId: 'researcher', taskDescription: `深度调研：${task}`, dependencies: ['plan'], retryCount: 3, timeout: 120 });
    dag.addNode({ id: 'analyze', agentId: 'executor', taskDescription: `数据分析：${task}`, dependencies: ['plan'], retryCount: 3, timeout: 120 });
    dag.addNode({ id: 'merge', agentId: 'reviewer', taskDescription: `合并结果：${task}`, dependencies: ['research', 'analyze'], retryCount: 3, timeout: 120 });
    dag.addEdge('plan', 'research'); dag.addEdge('plan', 'analyze'); dag.addEdge('research', 'merge'); dag.addEdge('analyze', 'merge');
  } else {
    dag.addNode({ id: 'plan', agentId: 'planner', taskDescription: `任务分解：${task}`, dependencies: [], retryCount: 3, timeout: 120 });
    dag.addNode({ id: 'research', agentId: 'researcher', taskDescription: `调研阶段：${task}`, dependencies: ['plan'], retryCount: 3, timeout: 120 });
    dag.addNode({ id: 'code', agentId: 'executor', taskDescription: `执行阶段：${task}`, dependencies: ['research'], retryCount: 3, timeout: 120 });
    dag.addNode({ id: 'review', agentId: 'reviewer', taskDescription: `质量审查：${task}`, dependencies: ['code'], retryCount: 3, timeout: 120 });
    dag.addEdge('plan', 'research'); dag.addEdge('research', 'code'); dag.addEdge('code', 'review');
  }
  return dag;
}

async function runOrchestrator(task, intent, apiKey, provider, model, baseUrl, db) {
  const traceId = genUUID().slice(0, 12);
  const ctx = { taskId: genUUID().slice(0, 12), userInput: task, intent: intent || classifyIntent(task), state: 'INIT', plan: {}, dagResults: {}, reviewResult: {}, finalResult: '', turnCount: 0 };
  const memCtx = ''; const histBlk = '';
  const record = (step, agent, inputData, outputData, latencyMs, tokens = 0) => {};

  record('INIT', '', { task, intent: ctx.intent }, { agents: getAgentsForIntent(ctx.intent) }, 0);
  ctx.state = 'PLAN';

  // EXECUTE (DAG)
  const execStart = Date.now();
  const dag = buildDag(ctx.intent, task);
  const dagResults = await dag.execute({ apiKey, provider, model, baseUrl, originalTask: task, previousResults: {} });
  ctx.dagResults = Object.fromEntries([...dagResults.entries()].map(([k, v]) => [k, v]));
  const successResults = [...dagResults.values()].filter(r => r.status === 'success');
  if (successResults.length > 0) ctx.finalResult = successResults.map(r => `[${r.agentId}]: ${r.result}`).join('\n\n');
  record('EXECUTE', '', {}, { results: ctx.dagResults, successCount: successResults.length }, Date.now() - execStart);
  ctx.state = 'DONE';
  record('COMPLETE', '', {}, { finalState: 'DONE', resultLength: ctx.finalResult.length, turnCount: ctx.turnCount }, 0);
  return { context: ctx, trace: [] };
}

// ═══════════════════════════════════════════
// Router
// ═══════════════════════════════════════════

const routes = [];
function route(method, pattern, handler) {
  const regex = new RegExp('^' + pattern.replace(/:[^/]+/g, '([^/]+)') + '$');
  routes.push({ method, pattern: regex, handler });
}
function matchRoute(method, pathname) {
  for (const r of routes) { if (r.method !== method && r.method !== 'ANY') continue; const match = pathname.match(r.pattern); if (match) return { handler: r.handler, match }; }
  return null;
}

// Health
route('GET', '/api/health', () => json({ status: 'ok', service: 'AI Team Hub', version: '2.3.0', engine: 'state_machine_dag', platform: 'cloudflare_workers' }));

// Orchestrator
route('POST', '/api/orchestrator/run', async (req, _match, env) => {
  const data = await req.json();
  const task = data.task || ''; const intent = data.intent || '';
  const provider = data.provider || 'deepseek'; const model = data.model || 'deepseek-chat';
  const apiKeyRow = await env.DB.prepare('SELECT * FROM apikeys WHERE provider = ? LIMIT 1').bind(provider).first();
  if (!apiKeyRow || !apiKeyRow.api_key) return error(`No API key for provider: ${provider}`, 400);
  const result = await runOrchestrator(task, intent, apiKeyRow.api_key, provider, model, apiKeyRow.base_url, env.DB);
  return json({
    task_id: result.context.taskId, trace_id: result.trace[0]?.traceId || '', state: result.context.state,
    intent: result.context.intent, dag_results: result.context.dagResults, final_result: result.context.finalResult,
    turn_count: result.context.turnCount, trace_length: result.trace.length,
  });
});

route('GET', '/api/orchestrator/state', () => json({ state: 'idle' }));

// Traces
route('GET', '/api/traces/', async (_req, _match, env) => {
  try { const { results } = await env.DB.prepare('SELECT DISTINCT trace_id, task_id FROM trace_events GROUP BY trace_id ORDER BY MIN(ts) DESC LIMIT 20').all(); return json(results || []); } catch { return json([]); }
});
route('GET', '/api/traces/:id', async (_req, match, env) => {
  try { const row = await env.DB.prepare('SELECT context_json FROM task_states WHERE trace_id = ?').bind(match[1]).first(); if (!row) return error('Trace not found', 404); return json(JSON.parse(row.context_json)); } catch { return error('Trace not found', 404); }
});

// Channels
route('GET', '/api/channels', async (_req, _match, env) => { const { results } = await env.DB.prepare('SELECT * FROM channels ORDER BY created_at').all(); return json(results.map(r => ({ id: r.id, name: r.name, description: r.description || '', teammate_ids: JSON.parse(r.teammate_ids || '[]'), created_at: r.created_at, updated_at: r.updated_at }))); });
route('POST', '/api/channels', async (req, _match, env) => { const data = await req.json(); const id = genUUID(), now = utcNow(); await env.DB.prepare('INSERT INTO channels (id, name, description, created_at, updated_at, teammate_ids) VALUES (?, ?, ?, ?, ?, ?)').bind(id, data.name || '', data.description || '', now, now, '[]').run(); return json({ id, name: data.name }, 201); });
route('GET', '/api/channels/:id', async (_req, match, env) => { const row = await env.DB.prepare('SELECT * FROM channels WHERE id = ?').bind(match[1]).first(); if (!row) return error('Not found', 404); return json({ id: row.id, name: row.name, description: row.description || '', teammate_ids: JSON.parse(row.teammate_ids || '[]'), created_at: row.created_at, updated_at: row.updated_at }); });
route('DELETE', '/api/channels/:id', async (_req, match, env) => { await env.DB.prepare('DELETE FROM messages WHERE channel_id = ?').bind(match[1]).run(); await env.DB.prepare('DELETE FROM channels WHERE id = ?').bind(match[1]).run(); return json({ ok: true }); });

// Teammates
route('GET', '/api/teammates', async (_req, _match, env) => { const { results } = await env.DB.prepare('SELECT * FROM teammates ORDER BY created_at').all(); return json(results.map(r => ({ id: r.id, name: r.name, role: r.role || 'assistant', avatar_emoji: r.avatar_emoji || '🤖', system_prompt: r.system_prompt || '', model_provider: r.model_provider, model_name: r.model_name, api_key_ref: r.api_key_ref || undefined }))); });
route('POST', '/api/teammates', async (req, _match, env) => { const d = await req.json(); const id = genUUID(), now = utcNow(); await env.DB.prepare('INSERT INTO teammates (id, name, role, avatar_emoji, system_prompt, model_provider, model_name, api_key_ref, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)').bind(id, d.name || '', d.role || 'assistant', d.avatar_emoji || '🤖', d.system_prompt || '', d.model_provider || '', d.model_name || '', d.api_key_ref || null, now, now).run(); return json({ id, name: d.name }, 201); });
route('DELETE', '/api/teammates/:id', async (_req, match, env) => { await env.DB.prepare('DELETE FROM teammates WHERE id = ?').bind(match[1]).run(); return json({ ok: true }); });

// API Keys
route('GET', '/api/apikeys', async (_req, _match, env) => { const { results } = await env.DB.prepare('SELECT * FROM apikeys ORDER BY created_at').all(); return json(results.map(k => ({ id: k.id, provider: k.provider, label: k.label, api_key: k.api_key ? k.api_key.slice(0, 8) + '***' : '', base_url: k.base_url, has_key: !!k.api_key }))); });
route('POST', '/api/apikeys', async (req, _match, env) => { const d = await req.json(); const id = genUUID(), now = utcNow(); await env.DB.prepare('INSERT INTO apikeys (id, provider, label, api_key, base_url, created_at) VALUES (?, ?, ?, ?, ?, ?)').bind(id, d.provider || '', d.label || '', d.api_key || '', d.base_url || null, now).run(); return json({ id, provider: d.provider, label: d.label, has_key: !!d.api_key }, 201); });
route('DELETE', '/api/apikeys/:id', async (_req, match, env) => { await env.DB.prepare('DELETE FROM apikeys WHERE id = ?').bind(match[1]).run(); return json({ ok: true }); });

// Messages
route('GET', '/api/messages/:channel_id', async (_req, match, env) => { const limit = Number(new URL(_req.url).searchParams.get('limit') || 200); const { results } = await env.DB.prepare('SELECT * FROM messages WHERE channel_id = ? ORDER BY created_at LIMIT ?').bind(match[1], limit).all(); return json(results.map(m => ({ id: m.id, channel_id: m.channel_id, role: m.role, author_name: m.author_name, author_id: m.author_id || undefined, content: m.content || '', attachments: m.attachments ? JSON.parse(m.attachments) : [], created_at: m.created_at }))); });
route('DELETE', '/api/messages/:channel_id', async (_req, match, env) => { const { results } = await env.DB.prepare('DELETE FROM messages WHERE channel_id = ? RETURNING id').bind(match[1]).all(); return json({ ok: true, deleted: results.length }); });

// AI Chat
route('POST', '/api/messages/:channel_id', async (req, match, env) => {
  const channelId = match[1]; const data = await req.json();
  const channel = await env.DB.prepare('SELECT id FROM channels WHERE id = ?').bind(channelId).first();
  if (!channel) return error('Channel not found', 404);
  const content = data.content || ''; const teammateId = data.teammate_id || null;
  let userMsgId = null;
  if (!data.skip_user_save) { userMsgId = genUUID(); await env.DB.prepare('INSERT INTO messages (id, channel_id, role, author_name, content, attachments, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)').bind(userMsgId, channelId, 'user', data.author_name || 'You', content, data.attachments ? JSON.stringify(data.attachments) : null, utcNow()).run(); }
  if (!teammateId) return json({ user_message_id: userMsgId });
  const tm = await env.DB.prepare('SELECT * FROM teammates WHERE id = ?').bind(teammateId).first();
  if (!tm) return error('Teammate not found', 404);
  if (!tm.api_key_ref) return error('Teammate has no API key', 400);
  const apiKeyRow = await env.DB.prepare('SELECT * FROM apikeys WHERE id = ?').bind(tm.api_key_ref).first();
  if (!apiKeyRow || !apiKeyRow.api_key) return error('API key not found', 400);
  const { results: msgResults } = await env.DB.prepare('SELECT role, content FROM messages WHERE channel_id = ? ORDER BY created_at LIMIT 200').bind(channelId).all();
  const recentTurns = msgResults.slice(-6);
  const fixedMessages = buildFixedPrompt(tm.system_prompt, recentTurns, content);
  const provider = tm.model_provider; const isAnthropic = provider === 'anthropic';
  const endpoint = getEndpoint(provider, apiKeyRow.base_url);
  const headers = { 'Content-Type': 'application/json' }; let payload;
  if (isAnthropic) { headers['x-api-key'] = apiKeyRow.api_key; headers['anthropic-version'] = '2023-06-01'; payload = { model: tm.model_name, system: tm.system_prompt, messages: fixedMessages, max_tokens: 4096, stream: false }; }
  else { headers['Authorization'] = `Bearer ${apiKeyRow.api_key}`; payload = { model: tm.model_name, messages: fixedMessages, stream: false, temperature: 0.7, max_tokens: 2000 }; }
  let response; try { response = await fetch(endpoint, { method: 'POST', headers, body: JSON.stringify(payload), redirect: 'follow' }); } catch (e) { return json({ detail: `AI Fetch Error: ${e.message}` }, 502); }
  if (!response.ok) { const text = await response.text(); return json({ detail: `AI Error: ${response.status} ${text.slice(0, 200)}` }, 502); }
  const r = await response.json(); let full = '';
  if (r.choices?.[0]?.message?.content) full = r.choices[0].message.content;
  else if (r.output?.[0]?.content?.[0]?.text) full = r.output[0].content[0].text;
  if (full.trim()) { const aiMsgId = genUUID(); try { await env.DB.prepare('INSERT INTO messages (id, channel_id, role, author_name, author_id, content, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)').bind(aiMsgId, channelId, 'ai', tm.name, teammateId, full, utcNow()).run(); } catch (e) { console.error('Failed to save AI response:', e); } }
  const encoder = new TextEncoder(); const stream = new ReadableStream({ start(controller) { controller.enqueue(encoder.encode(full)); controller.close(); } });
  return new Response(stream, { headers: { 'Content-Type': 'text/plain; charset=utf-8' } });
});

function buildFixedPrompt(systemPrompt, recentTurns, currentContent) {
  const summaryBlock = 'The following is a conversation between a user and AI assistant(s) in a team channel.';
  const messages = [{ role: 'system', content: systemPrompt }, { role: 'user', content: summaryBlock }, { role: 'assistant', content: 'I understand. How can I help you today?' }, { role: 'user', content: 'Tell me about yourself.' }, { role: 'assistant', content: 'I am an AI assistant in this team channel, ready to help with tasks, coding, analysis, and discussion.' }, ...recentTurns.map(m => ({ ...m, role: m.role === 'ai' ? 'assistant' : m.role })), { role: 'user', content: currentContent }];
  return messages;
}

// ═══════════════════════════════════════════
// Main Handler
// ═══════════════════════════════════════════

addEventListener('fetch', (event) => {
  event.respondWith(handleRequest(event.request, event.env));
});

async function handleRequest(request, env) {
  const url = new URL(request.url); const pathname = url.pathname; const method = request.method;
  if (method === 'OPTIONS') return corsResponse();
  const matched = matchRoute(method, pathname);
  if (matched) { const response = await matched.handler(request, matched.match, env); return setCors(response); }
  return error('Not found', 404);
}
