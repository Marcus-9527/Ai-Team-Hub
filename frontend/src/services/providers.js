/**
 * 大模型提供商配置
 * 优先从 API 动态加载模型列表，失败时 fallback 到静态列表
 */

// ── 静态 fallback 列表（当 API 不可用时使用）──
const STATIC_MODELS = {
  deepseek: [
    'deepseek-chat', 'deepseek-reasoner', 'deepseek-v3.1', 'deepseek-v3',
    'deepseek-r1-0528', 'deepseek-r1', 'deepseek-coder-v2',
  ],
  zhipu: [
    'glm-4-plus', 'glm-4-air', 'glm-4-airx', 'glm-4-flash', 'glm-4-long',
    'glm-4-flashx', 'glm-4v', 'glm-4v-plus', 'glm-4', 'glm-3-turbo', 'codegeex-4',
  ],
  moonshot: [
    'kimi-k2.5', 'kimi-k2-0711-preview', 'kimi-k2-instruct',
    'moonshot-v1-8k', 'moonshot-v1-32k', 'moonshot-v1-128k',
  ],
  baidu: [
    'ernie-4.5-8k-preview', 'ernie-4.5', 'ernie-4.0-8k', 'ernie-4.0-8k-preview',
    'ernie-4.0-turbo-8k', 'ernie-4.0-turbo-128k', 'ernie-3.5-8k', 'ernie-3.5-128k',
    'ernie-speed-8k', 'ernie-speed-128k', 'ernie-lite-8k', 'ernie-char-8k', 'ernie-novel-8k',
  ],
  alibaba: [
    'qwen-max-latest', 'qwen-plus-latest', 'qwen-turbo-latest', 'qwen-long',
    'qwen3-coder-plus', 'qwen3-235b-a22b-instruct', 'qwen3-30b-a3b', 'qwen3-32b',
    'qwen3-14b', 'qwen3-8b', 'qwen3-4b', 'qwen3-1.7b', 'qwen3-0.6b',
    'qwen2.5-72b-instruct', 'qwen2.5-32b-instruct', 'qwen2.5-14b-instruct', 'qwen2.5-7b-instruct',
    'qwen2.5-coder-32b-instruct', 'qwen2.5-coder-7b-instruct',
    'qwq-32b',
    'qwen-vl-max', 'qwen-vl-plus', 'qwen-omni-turbo',
  ],
  doubao: [
    'doubao-seed-1-6-250615', 'doubao-seed-1-6', 'doubao-pro-32k-0528',
    'doubao-pro-128k', 'doubao-pro-32k', 'doubao-pro-4k',
    'doubao-lite-128k', 'doubao-lite-32k', 'doubao-lite-4k',
    'doubao-embedding-large',
  ],
  hunyuan: [
    'hunyuan-turbo', 'hunyuan-turbo-latest', 'hunyuan-pro',
    'hunyuan-standard', 'hunyuan-standard-256k', 'hunyuan-lite', 'hunyuan-lite-256k',
    'hunyuan-code', 'hunyuan-vision', 'hunyuan-embedding',
  ],
  baichuan: [
    'Baichuan4', 'Baichuan3-Turbo', 'Baichuan3-Turbo-128k', 'Baichuan3',
    'Baichuan2-Turbo', 'Baichuan2-Turbo-192k', 'Baichuan2-13B-Chat', 'Baichuan2-7B-Chat',
    'Baichuan-13B-Chat', 'Baichuan-7B-Chat',
  ],
  yi: [
    'yi-lightning', 'yi-large', 'yi-large-rag', 'yi-large-turbo',
    'yi-medium', 'yi-medium-200k', 'yi-vision', 'yi-spark',
    'yi-coder', 'yi-coder-9b', 'yi-coder-1.5b',
    'yi-34b-chat', 'yi-34b-chat-200k', 'yi-6b-chat',
    'yi-1.5-34b-chat', 'yi-1.5-9b-chat', 'yi-1.5-6b-chat',
  ],
  minimax: [
    'MiniMax-M1', 'minimax-text-01', 'MiniMax-Text-01',
    'abab7-chat', 'abab6.5s-chat', 'abab6.5-chat',
  ],
  stepfun: [
    'step-1-256k', 'step-1-128k', 'step-1-32k', 'step-1-8k',
    'step-2-16k', 'step-2', 'step-2-mini',
    'step-1v-32k', 'step-1v-8k', 'step-1x-medium',
    'step-1o-vision-32k', 'step-1o-mini', 'step-1-flash', 'step-3',
  ],
  spark: [
    'spark-4.0-ultra', 'spark-4.0', 'spark-3.5', 'spark-3.5-128k',
    'spark-3.0', 'spark-2.0', 'spark-lite',
    'spark-generalv3.5', 'spark-generalv3', 'spark-generalv2',
    'spark-pro', 'spark-pro-128k',
  ],
  siliconflow: [
    'Qwen/Qwen3-235B-A22B', 'Qwen/Qwen3-30B-A3B', 'Qwen/Qwen3-32B', 'Qwen/Qwen3-14B', 'Qwen/Qwen3-8B',
    'Qwen/Qwen2.5-72B-Instruct', 'Qwen/Qwen2.5-32B-Instruct', 'Qwen/Qwen2.5-7B-Instruct',
    'Qwen/Qwen2.5-Coder-32B-Instruct', 'Qwen/Qwen2.5-Coder-7B-Instruct',
    'deepseek-ai/DeepSeek-V3.1', 'deepseek-ai/DeepSeek-R1-0528', 'deepseek-ai/DeepSeek-R1',
    'deepseek-ai/DeepSeek-V3',
    'THUDM/GLM-4-9B-Chat-1M',
    'meta-llama/Llama-3.3-70B-Instruct', 'meta-llama/Llama-3.1-8B-Instruct',
    'meta-llama/Llama-3.2-3B-Instruct',
    'google/gemma-2-27b-it', 'google/gemma-2-9b-it',
  ],
  openai: [
    'gpt-5', 'gpt-5-mini', 'gpt-5-nano',
    'gpt-4.1', 'gpt-4.1-mini', 'gpt-4.1-nano',
    'gpt-4o', 'gpt-4o-mini', 'gpt-4o-2024-11-20', 'gpt-4o-2024-08-06',
    'o1', 'o1-preview', 'o1-mini', 'o3', 'o3-mini', 'o3-pro', 'o4-mini',
    'gpt-4-turbo', 'gpt-4',
  ],
  anthropic: [
    'claude-opus-4-5', 'claude-opus-4-20250514', 'claude-opus-4-20250514-thinking',
    'claude-sonnet-4-20250514', 'claude-sonnet-4-20250514-thinking',
    'claude-3.7-sonnet-20250219',
    'claude-haiku-4-20250514',
    'claude-3-5-sonnet-20241022', 'claude-3-5-haiku-20241022',
  ],
  google: [
    'gemini-2.5-pro', 'gemini-2.5-flash', 'gemini-2.5-flash-lite', 'gemini-2.5-flash-image-preview',
    'gemini-2.0-flash', 'gemini-2.0-flash-lite',
    'gemini-1.5-pro', 'gemini-1.5-flash', 'gemini-1.5-flash-8b',
  ],
  mistral: [
    'mistral-large-latest', 'mistral-small-latest',
    'pixtral-large-latest', 'pixtral-12b',
    'codestral-latest',
    'ministral-8b-latest', 'ministral-3b-latest',
    'open-mistral-nemo', 'mistral-embed',
  ],
  groq: [
    'llama-3.3-70b-versatile', 'llama-3.1-8b-instant',
    'llama-3.2-3b-preview', 'llama-3.2-11b-vision-preview',
    'qwen-2.5-32b', 'deepseek-r1-distill-llama-70b',
    'gemma2-9b-it',
  ],
  together: [
    'meta-llama/Meta-Llama-3.1-70B-Instruct', 'meta-llama/Meta-Llama-3.1-8B-Instruct',
    'meta-llama/Meta-Llama-3.1-405B-Instruct', 'meta-llama/Llama-3.3-70B-Instruct',
    'meta-llama/Llama-3-70b-chat-hf', 'meta-llama/Llama-3-8b-chat-hf',
    'Qwen/Qwen2.5-72B-Instruct', 'Qwen/Qwen2.5-32B-Instruct', 'Qwen/Qwen2.5-7B-Instruct',
    'Qwen/Qwen2.5-Coder-32B-Instruct', 'Qwen/QwQ-32B-Preview', 'Qwen/Qwen2-72B-Instruct',
    'deepseek-ai/DeepSeek-V3', 'deepseek-ai/DeepSeek-R1', 'deepseek-ai/DeepSeek-R1-0528',
    'deepseek-ai/DeepSeek-Coder-V2-Instruct',
    'NousResearch/Nous-Hermes-2-Mixtral-8x7B-DPO',
    '01-ai/Yi-34B-Chat', 'Gryphe/MythoMax-L2-13B',
    'databricks/dbrx-instruct',
    'google/gemma-2-27b-it', 'google/gemma-2-9b-it', 'google/gemma-7b-it',
  ],
  openrouter: [],  // OpenRouter 总是动态加载
  opencode: [
    'claude-fable-5', 'claude-opus-4-8', 'claude-opus-4-7', 'claude-opus-4-6', 'claude-opus-4-5',
    'claude-opus-4-1', 'claude-sonnet-5', 'claude-sonnet-4-6', 'claude-sonnet-4-5', 'claude-sonnet-4',
    'claude-haiku-4-5', 'gemini-3.5-flash', 'gemini-3.1-pro', 'gemini-3-flash',
    'gpt-5.5', 'gpt-5.5-pro', 'gpt-5.4', 'gpt-5.4-pro', 'gpt-5.4-mini', 'gpt-5.4-nano',
    'gpt-5.3-codex-spark', 'gpt-5.3-codex', 'gpt-5.2', 'gpt-5.2-codex', 'gpt-5.1',
    'gpt-5.1-codex-max', 'gpt-5.1-codex', 'gpt-5.1-codex-mini', 'gpt-5', 'gpt-5-codex', 'gpt-5-nano',
    'grok-build-0.1', 'deepseek-v4-pro', 'deepseek-v4-flash',
    'glm-5.2', 'glm-5.1', 'glm-5', 'minimax-m3', 'minimax-m2.7', 'minimax-m2.5',
    'kimi-k2.7-code', 'kimi-k2.6', 'kimi-k2.5', 'qwen3.6-plus', 'qwen3.5-plus',
    'big-pickle', 'deepseek-v4-flash-free', 'mimo-v2.5-free', 'nemotron-3-ultra-free', 'north-mini-code-free',
  ],
  custom: ['输入任意 OpenAI 兼容模型名'],
};

// ── 免费模型标记 ──
// 某些 provider 的 API 不返回 is_free 字段，手动标记
const FREE_MODELS = new Set([
  'deepseek-v4-flash-free',
  'mimo-v2.5-free',
  'nemotron-3-ultra-free',
  'north-mini-code-free',
]);

// ── Provider 元数据 ──
// desc: 面向普通用户的中文简介（不需要理解 API / Provider 概念）
const PROVIDER_META = [
  // 中国
  { id: 'deepseek',    name: 'DeepSeek (深度求索)',  region: 'cn', desc: '国内最强推理模型，性价比高，适合复杂任务' },
  { id: 'zhipu',       name: '智谱AI (GLM系列)',     region: 'cn', desc: '清华系大模型，中文理解强，长文本友好' },
  { id: 'moonshot',    name: '月之暗面 (Kimi)',      region: 'cn', desc: '超长上下文，适合读长文档、做总结' },
  { id: 'baidu',       name: '百度千帆 (文心一言)',  region: 'cn', desc: '百度出品，中文场景覆盖广' },
  { id: 'alibaba',     name: '阿里通义 (Qwen)',      region: 'cn', desc: '通义千问，编码与多语言能力强' },
  { id: 'doubao',      name: '字节豆包 (Doubao)',     region: 'cn', desc: '字节出品，响应快、成本低' },
  { id: 'hunyuan',     name: '腾讯混元',             region: 'cn', desc: '腾讯大模型，生态集成好' },
  { id: 'baichuan',    name: '百川智能',             region: 'cn', desc: '国产开源模型，部署灵活' },
  { id: 'yi',          name: '零一万物 (Yi)',        region: 'cn', desc: '李开复团队，中英文均衡' },
  { id: 'minimax',     name: 'MiniMax',              region: 'cn', desc: '对话与语音场景表现好' },
  { id: 'stepfun',     name: '阶跃星辰 (Step)',      region: 'cn', desc: '多模态与长文本推理' },
  { id: 'spark',       name: '科大讯飞 (星火)',      region: 'cn', desc: '讯飞语音生态，中文识别强' },
  { id: 'siliconflow', name: '硅基流动',             region: 'cn', desc: '聚合多家开源模型，注册即送额度' },
  // 海外
  { id: 'openai',      name: 'OpenAI',               region: 'overseas', desc: 'GPT 系列，通用能力业界标杆' },
  { id: 'anthropic',   name: 'Anthropic (Claude)',   region: 'overseas', desc: 'Claude 系列，长文与代码强' },
  { id: 'google',      name: 'Google Gemini',        region: 'overseas', desc: '多模态与超长上下文' },
  { id: 'mistral',     name: 'Mistral AI',           region: 'overseas', desc: '欧洲开源模型，轻量高效' },
  { id: 'groq',        name: 'Groq',                 region: 'overseas', desc: '极速推理，延迟极低' },
  { id: 'together',    name: 'Together AI',          region: 'overseas', desc: '聚合开源模型，训练推理一体' },
  { id: 'openrouter',  name: 'OpenRouter',           region: 'overseas', desc: '一个接口接入上百种模型' },
  { id: 'opencode',    name: 'OpenCode Zen',         region: 'overseas', desc: '统一网关，路由多家顶尖模型' },
  { id: 'custom',      name: '自定义 (Custom)',      region: 'overseas', desc: '任意 OpenAI 兼容模型' },
];

// ── 动态模型缓存 ──
const _modelCache = {};
const _allModelsCache = { models: null, ts: 0 };
const CACHE_TTL = 5 * 60 * 1000; // 5 分钟
const ALL_CACHE_TTL = 10 * 60 * 1000; // 10 分钟

// ── 从后端获取所有模型（自动更新）──
async function _ensureAllModels() {
  if (_allModelsCache.models && Date.now() - _allModelsCache.ts < ALL_CACHE_TTL) {
    return _allModelsCache.models;
  }
  try {
    const { fetchAllModels } = await import('./api');
    const data = await fetchAllModels();
    if (data?.models) {
      _allModelsCache.models = data.models;
      _allModelsCache.ts = Date.now();
      return data.models;
    }
  } catch {
    // fall through
  }
  return null;
}

// ── 导出：Provider 列表 ──
export const CHINESE_PROVIDERS = PROVIDER_META.filter(p => p.region === 'cn');
export const OVERSEAS_PROVIDERS = PROVIDER_META.filter(p => p.region === 'overseas');
export const ALL_PROVIDERS = [
  ...CHINESE_PROVIDERS,
  { id: '---', name: '─── 海外 ───', region: 'overseas' },
  ...OVERSEAS_PROVIDERS,
];

// ── 导出：获取模型列表（优先后端动态，fallback 到静态）──
export async function getProviderModels(providerId, apiKeyId) {
  // 检查单 provider 缓存
  const cached = _modelCache[providerId];
  if (cached && Date.now() - cached.ts < CACHE_TTL) {
    return cached.models;
  }

  let models = [];

  // OpenRouter: 合并所有供应商的模型（OpenRouter 可路由到所有模型）
          if (providerId === 'openrouter') {
    try {
      const allModels = await _ensureAllModels();
      if (allModels) {
        const seen = new Set();
        for (const [, mList] of Object.entries(allModels)) {
          if (!Array.isArray(mList)) continue;
          for (const m of mList) {
            if (seen.has(m.id)) continue;
            seen.add(m.id);
            models.push({
              id: m.id,
              name: m.name || m.id,
              is_free: !!(m.is_free || FREE_MODELS.has(m.id)),
              context_length: m.context_length || 0,
            });
          }
        }
      }
    } catch {
      // fall through
    }
  }

  // 普通 provider: 只取自身的模型
  if (!models.length) {
    try {
      const allModels = await _ensureAllModels();
      if (allModels && allModels[providerId]?.length) {
        models = allModels[providerId].map(m => ({
          id: m.id,
          name: m.name || m.id,
          is_free: !!(m.is_free || FREE_MODELS.has(m.id)),
          context_length: m.context_length || 0,
        }));
      }
    } catch {
      // fall through
    }
  }

  // Fallback: 直接 fetch（兼容旧 worker / 无后端场景）
  if (!models.length) {
    try {
      if (providerId !== 'custom' && providerId !== 'openrouter') {
        const { fetchModels } = await import('./api');
        const result = await fetchModels(providerId, apiKeyId || '');
        if (result?.models?.length) {
          models = result.models;
        }
      }
    } catch {
      // fall through
    }
  }

  // 最终 fallback：静态列表
  if (!models.length && STATIC_MODELS[providerId]) {
    if (providerId === 'custom') {
      models = STATIC_MODELS['custom']?.map(id => ({ id, name: id, is_free: false })) || [];
    } else {
      models = STATIC_MODELS[providerId].map(id => ({ id, name: id, is_free: FREE_MODELS.has(id) }));
    }
  }

  // 写入缓存
  _modelCache[providerId] = { models, ts: Date.now() };
  return models;
}

/** 同步获取（仅返回缓存或静态，不触发网络请求） */
export function getProviderModelsSync(providerId) {
  const cached = _modelCache[providerId];
  if (cached) return cached.models;
  return STATIC_MODELS[providerId] || [];
}

/** 获取 provider 显示名称 */
export function getProviderName(providerId) {
  const p = PROVIDER_META.find(x => x.id === providerId);
  return p?.name || providerId;
}

/** 清除缓存（切换 key 后调用） */
export function clearModelCache(providerId) {
  if (providerId) {
    delete _modelCache[providerId];
  } else {
    for (const k of Object.keys(_modelCache)) delete _modelCache[k];
  }
}
