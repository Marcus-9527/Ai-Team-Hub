/**
 * 大模型提供商配置
 * 优先从 API 动态加载模型列表，失败时 fallback 到静态列表
 */

// ── 静态 fallback 列表（当 API 不可用时使用）──
const STATIC_MODELS = {
  deepseek: [
    'deepseek-chat', 'deepseek-reasoner', 'deepseek-v3', 'deepseek-r1',
    'deepseek-v2.5', 'deepseek-coder-v2', 'deepseek-v2', 'deepseek-coder',
    'deepseek-math', 'deepseek-moe-16b',
  ],
  zhipu: [
    'glm-4-plus', 'glm-4-air', 'glm-4-airx', 'glm-4-flash', 'glm-4-long',
    'glm-4-flashx', 'glm-4v', 'glm-4v-plus', 'glm-4', 'glm-3-turbo', 'codegeex-4',
  ],
  moonshot: [
    'moonshot-v1-8k', 'moonshot-v1-32k', 'moonshot-v1-128k',
    'kimi-k2-0711-preview', 'kimi-k2-instruct',
  ],
  baidu: [
    'ernie-4.5-8k-preview', 'ernie-4.5', 'ernie-4.0-8k', 'ernie-4.0-8k-preview',
    'ernie-4.0-turbo-8k', 'ernie-4.0-turbo-128k', 'ernie-3.5-8k', 'ernie-3.5-128k',
    'ernie-speed-8k', 'ernie-speed-128k', 'ernie-lite-8k', 'ernie-char-8k', 'ernie-novel-8k',
  ],
  alibaba: [
    'qwen-max', 'qwen-max-latest', 'qwen-plus', 'qwen-plus-latest',
    'qwen-turbo', 'qwen-turbo-latest', 'qwen-long',
    'qwen-coder-plus', 'qwen-coder-turbo', 'qwen-vl-max', 'qwen-vl-plus', 'qwen-omni-turbo',
    'qwen2.5-72b-instruct', 'qwen2.5-32b-instruct', 'qwen2.5-14b-instruct', 'qwen2.5-7b-instruct',
    'qwen2.5-3b-instruct', 'qwen2.5-1.5b-instruct',
    'qwen2-72b-instruct', 'qwen2-7b-instruct', 'qwen2-57b-a14b-instruct',
    'qwen2-1.5b-instruct', 'qwen2-0.5b-instruct',
    'qwq-32b-preview', 'qwq-32b',
    'qwen3-235b-a22b', 'qwen3-30b-a3b', 'qwen3-32b', 'qwen3-14b', 'qwen3-8b',
    'qwen3-4b', 'qwen3-1.7b', 'qwen3-0.6b',
  ],
  doubao: [
    'doubao-pro-128k', 'doubao-pro-32k', 'doubao-pro-4k',
    'doubao-lite-128k', 'doubao-lite-32k', 'doubao-lite-4k',
    'doubao-embedding', 'doubao-embedding-large',
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
    'minimax-text-01', 'MiniMax-Text-01', 'abab7-chat',
    'abab6.5s-chat', 'abab6.5-chat', 'abab6.5t-chat', 'abab5.5s-chat', 'abab5.5-chat',
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
    'Qwen/Qwen2.5-72B-Instruct', 'Qwen/Qwen2.5-32B-Instruct', 'Qwen/Qwen2.5-14B-Instruct', 'Qwen/Qwen2.5-7B-Instruct',
    'Qwen/Qwen2.5-Coder-32B-Instruct', 'Qwen/Qwen2.5-Coder-7B-Instruct',
    'Qwen/QwQ-32B', 'Qwen/QwQ-32B-Preview',
    'Qwen/Qwen2-72B-Instruct', 'Qwen/Qwen2-7B-Instruct',
    'deepseek-ai/DeepSeek-V3', 'deepseek-ai/DeepSeek-R1', 'deepseek-ai/DeepSeek-R1-0528',
    'deepseek-ai/DeepSeek-V2.5', 'deepseek-ai/DeepSeek-Coder-V2-Instruct',
    'THUDM/glm-4-9b-chat', 'THUDM/GLM-4-9B-Chat-1M',
    'meta-llama/Meta-Llama-3.1-70B-Instruct', 'meta-llama/Meta-Llama-3.1-8B-Instruct',
    'meta-llama/Meta-Llama-3-70B-Instruct', 'meta-llama/Meta-Llama-3-8B-Instruct',
    'meta-llama/Llama-3.2-3B-Instruct', 'meta-llama/Llama-3.2-1B-Instruct',
    'meta-llama/Llama-3.3-70B-Instruct',
    'google/gemma-2-27b-it', 'google/gemma-2-9b-it', 'google/gemma-2-2b-it',
  ],
  openai: [
    'gpt-4o', 'gpt-4o-mini', 'gpt-4o-2024-11-20', 'gpt-4o-2024-08-06', 'gpt-4o-2024-05-13',
    'gpt-4o-realtime-preview', 'gpt-4o-mini-realtime-preview', 'gpt-4o-audio-preview',
    'gpt-4-turbo', 'gpt-4-turbo-2024-04-09', 'gpt-4-turbo-preview',
    'gpt-4', 'gpt-4-0613', 'gpt-4-32k',
    'gpt-3.5-turbo', 'gpt-3.5-turbo-0125', 'gpt-3.5-turbo-1106',
    'o1', 'o1-preview', 'o1-mini', 'o3', 'o3-mini', 'o3-pro', 'o4-mini',
    'gpt-4.1', 'gpt-4.1-mini', 'gpt-4.1-nano',
  ],
  anthropic: [
    'claude-opus-4-20250514', 'claude-opus-4-20250514-thinking',
    'claude-sonnet-4-20250514', 'claude-sonnet-4-20250514-thinking',
    'claude-haiku-4-20250514',
    'claude-3-5-sonnet-20241022', 'claude-3-5-sonnet-20240620',
    'claude-3-5-haiku-20241022',
    'claude-3-opus-20240229', 'claude-3-sonnet-20240229', 'claude-3-haiku-20240307',
    'claude-2.1', 'claude-2.0',
  ],
  google: [
    'gemini-2.5-pro', 'gemini-2.5-flash', 'gemini-2.5-flash-lite', 'gemini-2.5-flash-preview-05-20',
    'gemini-2.0-flash', 'gemini-2.0-flash-lite', 'gemini-2.0-flash-001',
    'gemini-2.0-flash-exp', 'gemini-2.0-flash-thinking-exp', 'gemini-2.0-flash-live-preview',
    'gemini-2.0-pro-exp',
    'gemini-1.5-pro', 'gemini-1.5-pro-002', 'gemini-1.5-pro-001',
    'gemini-1.5-flash', 'gemini-1.5-flash-002', 'gemini-1.5-flash-001', 'gemini-1.5-flash-8b',
    'gemini-1.0-pro',
  ],
  mistral: [
    'mistral-large-latest', 'mistral-large-2411', 'mistral-large-2407',
    'mistral-small-latest', 'mistral-small-2501', 'mistral-small-2409',
    'pixtral-large-latest', 'pixtral-large-2411', 'pixtral-12b', 'pixtral-12b-2409',
    'codestral-latest', 'codestral-2501', 'codestral-2411',
    'ministral-8b-latest', 'ministral-3b-latest',
    'open-mistral-nemo', 'open-mistral-nemo-2407',
    'open-mixtral-8x7b', 'open-mixtral-8x22b',
    'mathstral-7b-v0.1', 'mistral-embed',
  ],
  groq: [
    'llama-3.3-70b-versatile', 'llama-3.3-70b-specdec',
    'llama-3.1-8b-instant', 'llama-3.1-70b-versatile',
    'llama-3.2-3b-preview', 'llama-3.2-1b-preview',
    'llama-3.2-11b-vision-preview', 'llama-3.2-90b-vision-preview',
    'llama-3.1-405b-reasoning', 'llama-guard-3-8b',
    'mixtral-8x7b-32768', 'gemma-7b-it', 'gemma2-9b-it',
    'qwen-2.5-32b', 'deepseek-r1-distill-llama-70b',
    'llama3-70b-8192', 'llama3-8b-8192', 'llama2-70b-4096',
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
  custom: ['输入任意 OpenAI 兼容模型名'],
};

// ── Provider 元数据 ──
const PROVIDER_META = [
  // 中国
  { id: 'deepseek',    name: 'DeepSeek (深度求索)',    region: 'cn' },
  { id: 'zhipu',       name: '智谱AI (GLM系列)',       region: 'cn' },
  { id: 'moonshot',    name: '月之暗面 (Kimi)',        region: 'cn' },
  { id: 'baidu',       name: '百度千帆 (文心一言)',    region: 'cn' },
  { id: 'alibaba',     name: '阿里通义 (Qwen)',        region: 'cn' },
  { id: 'doubao',      name: '字节豆包 (Doubao)',      region: 'cn' },
  { id: 'hunyuan',     name: '腾讯混元',               region: 'cn' },
  { id: 'baichuan',    name: '百川智能',               region: 'cn' },
  { id: 'yi',          name: '零一万物 (Yi)',          region: 'cn' },
  { id: 'minimax',     name: 'MiniMax',                region: 'cn' },
  { id: 'stepfun',     name: '阶跃星辰 (Step)',        region: 'cn' },
  { id: 'spark',       name: '科大讯飞 (星火)',        region: 'cn' },
  { id: 'siliconflow', name: '硅基流动',               region: 'cn' },
  // 海外
  { id: 'openai',      name: 'OpenAI',                 region: 'overseas' },
  { id: 'anthropic',   name: 'Anthropic (Claude)',     region: 'overseas' },
  { id: 'google',      name: 'Google Gemini',          region: 'overseas' },
  { id: 'mistral',     name: 'Mistral AI',             region: 'overseas' },
  { id: 'groq',        name: 'Groq',                   region: 'overseas' },
  { id: 'together',    name: 'Together AI',            region: 'overseas' },
  { id: 'openrouter',  name: 'OpenRouter',             region: 'overseas' },
  { id: 'custom',      name: '自定义 (Custom)',        region: 'overseas' },
];

// ── 动态模型缓存 ──
const _modelCache = {};
const CACHE_TTL = 5 * 60 * 1000; // 5 分钟

// ── 导出：Provider 列表 ──
export const CHINESE_PROVIDERS = PROVIDER_META.filter(p => p.region === 'cn');
export const OVERSEAS_PROVIDERS = PROVIDER_META.filter(p => p.region === 'overseas');
export const ALL_PROVIDERS = [
  ...CHINESE_PROVIDERS,
  { id: '---', name: '─── 海外 ───', region: 'overseas' },
  ...OVERSEAS_PROVIDERS,
];

// ── 导出：获取模型列表（优先动态，fallback 静态）──
export async function getProviderModels(providerId, apiKeyId) {
  // 检查缓存
  const cached = _modelCache[providerId];
  if (cached && Date.now() - cached.ts < CACHE_TTL) {
    return cached.models;
  }

  let models = [];

  try {
    if (providerId === 'openrouter') {
      // OpenRouter 直接 fetch（公开 API）
      const { fetchOpenRouterModels } = await import('./api');
      models = await fetchOpenRouterModels();
    } else if (providerId === 'custom') {
      models = STATIC_MODELS['custom']?.map(id => ({ id, name: id, is_free: false })) || [];
    } else {
      // 其他供应商走后端代理
      const { fetchModels } = await import('./api');
      const result = await fetchModels(providerId, apiKeyId || '');
      if (result?.models?.length) {
        models = result.models;
      }
    }
  } catch {
    // API 失败 → fallback
  }

  // Fallback 到静态列表
  if (!models.length && STATIC_MODELS[providerId]) {
    models = STATIC_MODELS[providerId].map(id => ({ id, name: id, is_free: false }));
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
