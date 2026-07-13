/**
 * 模型展示元数据（前端派生，不触碰后端 API）。
 * 后端模型条目仅含 id / name / context_length / description / is_free，
 * 故「适用场景 / 价格 / 速度 / 能力标签」按 id 关键词启发式派生。
 */

const SPEED_FAST = ['mini', 'nano', 'flash', 'lite', 'turbo', 'haiku', 'speed', 'instant', '-8k', '-4k', '-32k'];
const SPEED_SLOW = ['opus', 'pro', 'reasoner', 'r1', 'reasoning', 'thinking', 'deep', '-405b', '235b', '70b', '32b'];

const KIND_TAGS = [
  { re: /reason|r1|o1|o3|o4|thinking|deepseek.*r|qwq|qwen.*-r/i, tag: '推理' },
  { re: /coder|code|codex|code-|\/code/i, tag: '代码' },
  { re: /vl|vision|omni|image|gemini.*image|视觉|pixtral|gemma.*vision/i, tag: '多模态' },
  { re: /embed/i, tag: '嵌入' },
  { re: /chat|gpt-|claude-|kimi|glm|qwen|deepseek|baichuan|yi|minimax|step|spark|ernie|hunyuan|abab|moonshot/i, tag: '对话' },
  { re: /instruct|chat|turbo|lite|flash|haiku|mini|air|plus/i, tag: '通用' },
];

const SCENARIO_KEYWORDS = [
  { re: /reason|r1|o1|o3|o4|thinking|qwq|deepseek.*r/i, text: '复杂推理、数学、逻辑分析' },
  { re: /coder|code|codex|code-|\/code/i, text: '代码生成、补全、重构' },
  { re: /vl|vision|omni|image|pixtral|gemma.*vision|视觉/i, text: '图像理解、图文混合输入' },
  { re: /embed/i, text: '文本向量化、检索、聚类' },
  { re: /mini|nano|flash|lite|haiku|speed|turbo/i, text: '高频对话、实时响应' },
  { re: /opus|pro|max|235b|405b|70b/i, text: '高质量长文、复杂任务' },
  { re: /chat|gpt-|claude-|kimi|glm|qwen|deepseek/i, text: '通用对话、内容创作' },
];

/** 派生能力标签（去重，最多 4 个） */
export function modelTags(id = '') {
  const tags = [];
  for (const { re, tag } of KIND_TAGS) {
    if (re.test(id) && !tags.includes(tag)) tags.push(tag);
  }
  return tags.slice(0, 4);
}

/** 派生适用场景（单句，最多拼接 2 条） */
export function modelScenario(id = '') {
  const hits = SCENARIO_KEYWORDS.filter(({ re }) => re.test(id)).map(({ text }) => text);
  if (hits.length === 0) return '通用 AI 任务';
  return [...new Set(hits)].slice(0, 2).join('；');
}

/** 派生速度档：'fast' | 'balanced' | 'slow' */
export function modelSpeed(id = '') {
  if (SPEED_FAST.some((k) => id.toLowerCase().includes(k))) return 'fast';
  if (SPEED_SLOW.some((k) => id.toLowerCase().includes(k))) return 'slow';
  return 'balanced';
}

const FREE_LABEL = { fast: '快', balanced: '中', slow: '慢' };

/**
 * 把一个后端模型条目（{id,name,context_length,is_free}）补全展示字段。
 * 返回 { ..., description, tags, scenario, speed }。
 */
export function decorateModel(m) {
  const id = m.id || '';
  return {
    ...m,
    description: m.description || '',
    tags: modelTags(id),
    scenario: modelScenario(id),
    speed: modelSpeed(id),
    speedLabel: FREE_LABEL[modelSpeed(id)],
  };
}

/** 把模型列表按 免费 / 付费 分组（免费在前） */
export function groupByTier(models = []) {
  const free = [];
  const paid = [];
  for (const m of models) (m.is_free ? free : paid).push(m);
  return { free, paid };
}
