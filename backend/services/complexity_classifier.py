"""
complexity_classifier.py — Zero-LLM-call task complexity classifier

Classifies tasks into SIMPLE / STANDARD / COMPLEX using deterministic
keyword + heuristic analysis. No LLM calls needed.

Classification rules:
  SIMPLE:   Direct answer, low risk, no multi-step reasoning
            e.g. "what time is it", "define X", "fix this typo"
  STANDARD: Requires reasoning or tool use, single-step
            e.g. "write a function to...", "analyze this code"
  COMPLEX:  Requires multi-step planning + validation
            e.g. "build a full app", "design and implement..."
"""

import re
import logging
from enum import Enum
from dataclasses import dataclass

logger = logging.getLogger("complexity_classifier")


class Complexity(str, Enum):
    SIMPLE = "SIMPLE"
    STANDARD = "STANDARD"
    COMPLEX = "COMPLEX"


@dataclass
class Classification:
    level: Complexity
    confidence: float  # 0.0–1.0
    reasons: list[str]

    def to_dict(self) -> dict:
        return {
            "level": self.level.value,
            "confidence": self.confidence,
            "reasons": self.reasons,
        }


# ── Heuristic keyword sets ──

# SIMPLE: factual, definitional, trivial
_SIMPLE_KEYWORDS = {
    # Chinese
    "什么", "定义", "解释", "意思", "时间", "日期", "天气",
    "翻译", "拼写", "读音", "多少", "哪个", "是谁",
    # English
    "what is", "define", "explain", "meaning", "time", "date",
    "translate", "spell", "pronounce", "how many", "which",
    "who is", "trivial", "simple", "quick",
}

# SINGLE_ACTION verbs — one clear action
_SIMPLE_ACTIONS = {
    "fix", "correct", "update", "change", "rename", "delete",
    "add", "remove", "replace", "convert", "format",
    "修复", "修改", "更新", "删除", "添加", "替换",
}

# STANDARD: requires reasoning or tool use
_STANDARD_KEYWORDS = {
    # Chinese
    "写", "创建", "实现", "分析", "优化", "重构", "调试",
    "计算", "排序", "搜索", "过滤", "解析", "验证",
    # English
    "write", "create", "implement", "analyze", "optimize",
    "refactor", "debug", "calculate", "sort", "search",
    "filter", "parse", "validate", "test", "review",
    "function", "class", "module", "script",
}

# COMPLEX: multi-system, architecture, full-pipeline
_COMPLEX_KEYWORDS = {
    # Chinese
    "设计", "架构", "系统", "平台", "框架", "完整", "全栈",
    "部署", "集成", "迁移", "重构整个", "构建", "搭建",
    "多步骤", "工作流", "管道", "流水线",
    # English
    "design", "architecture", "system", "platform", "framework",
    "full-stack", "fullstack", "deploy", "integrate", "migrate",
    "build a", "build an", "create a complete", "end-to-end",
    "pipeline", "workflow", "multi-step", "microservice",
    "orchestrator", "orchestration",
}

# Patterns that indicate multi-step complexity
_COMPLEX_PATTERNS = [
    re.compile(r"(and\s+then|then\s+\w+|step\s+\d+|first.*then.*finally)", re.I),
    re.compile(r"(首先.*然后|第一步.*第二步|先.*再.*最后)", re.I),
    re.compile(r"(multiple|several|various)\s+(steps?|components?|services?)", re.I),
    re.compile(r"(前端|后端|数据库|API|认证|部署).*(前端|后端|数据库|API|认证|部署)", re.I),
]


def classify_task(task: str) -> Classification:
    """
    Classify task complexity using deterministic heuristics.

    No LLM calls — pure keyword + structural analysis.

    Returns:
        Classification with level, confidence, and reasons.
    """
    text = task.lower().strip()
    reasons: list[str] = []

    # ── Quick length heuristic ──
    word_count = len(text.split())
    char_count = len(text)

    # Very short tasks are likely SIMPLE
    if word_count <= 5 and char_count <= 30:
        reasons.append(f"Short query ({word_count} words)")
        return Classification(Complexity.SIMPLE, 0.9, reasons)

    # ── Keyword scoring ──
    simple_score = 0
    standard_score = 0
    complex_score = 0

    for kw in _SIMPLE_KEYWORDS:
        if kw in text:
            simple_score += 2
            reasons.append(f"Simple keyword: '{kw}'")

    for kw in _STANDARD_KEYWORDS:
        if kw in text:
            standard_score += 1
            reasons.append(f"Standard keyword: '{kw}'")

    for kw in _COMPLEX_KEYWORDS:
        if kw in text:
            complex_score += 2
            reasons.append(f"Complex keyword: '{kw}'")

    # ── Pattern matching ──
    for pattern in _COMPLEX_PATTERNS:
        if pattern.search(text):
            complex_score += 3
            reasons.append(f"Complex pattern match: {pattern.pattern[:40]}")

    # ── Structural heuristics ──
    # Multiple sentences → higher complexity
    sentence_count = len(re.split(r'[.!?。！？]+', text))
    if sentence_count >= 3:
        standard_score += 1
        reasons.append(f"Multiple sentences ({sentence_count})")

    # Very long tasks → likely complex
    if word_count > 50:
        complex_score += 1
        reasons.append(f"Long task ({word_count} words)")

    # Code blocks present → at least STANDARD
    if "```" in text or re.search(r'\b(def |class |import |from |function |const |let |var )', text):
        standard_score += 2
        reasons.append("Contains code references")

    # ── Decision ──
    scores = {
        Complexity.SIMPLE: simple_score,
        Complexity.STANDARD: standard_score,
        Complexity.COMPLEX: complex_score,
    }

    # Default to STANDARD if no signals
    if max(scores.values()) == 0:
        reasons.append("No strong signals → default STANDARD")
        return Classification(Complexity.STANDARD, 0.5, reasons)

    # Pick highest score
    best = max(scores, key=scores.get)
    total = sum(scores.values())
    confidence = scores[best] / total if total > 0 else 0.5

    # Boost confidence if one category dominates
    sorted_scores = sorted(scores.values(), reverse=True)
    if len(sorted_scores) > 1 and sorted_scores[0] > 2 * sorted_scores[1]:
        confidence = min(confidence + 0.15, 1.0)

    reasons.append(f"Scores: SIMPLE={simple_score}, STANDARD={standard_score}, COMPLEX={complex_score}")

    return Classification(best, round(confidence, 2), reasons)


# ── Debate Trigger Gating ──

# Greetings / trivial inputs that should NEVER enter debate
_GREETING_PATTERNS = [
    # Pure greetings — must end with punctuation/space/end, not followed by content
    re.compile(r"^(hi|hello|hey|yo|sup|howdy|greetings)$", re.I),
    re.compile(r"^(谢谢|感谢|thanks|thank you)[\.。!！]?$", re.I),
    re.compile(r"^(好的|ok|okay|sure|行|嗯)$", re.I),
    re.compile(r"^(bye|goodbye|see you|晚安|goodnight)$", re.I),
    # Chinese greetings — strict (e.g. "你好" alone or with punctuation)
    re.compile(r"^(你好|嗨|哈喽|喂)[!！\.。\s]*$", re.I),
    re.compile(r"^(早上好|下午好|晚上好|早安|午安)[!！\.。\s]*$", re.I),
    re.compile(r"^([？！?。，、\s]+)$"),  # punctuation-only
    re.compile(r"^(lol|haha|哈哈|😂)$", re.I),
]

# Signals that indicate genuine multi-stakeholder complexity
_TRADEOFF_KEYWORDS = [
    "risk", "cost", "performance", "security", "scalability", "ux",
    "tradeoff", "trade-off", "vs", "versus", "balance",
    "风险", "成本", "性能", "安全", "扩展", "权衡", "对比", "取舍",
    "架构设计", "技术选型", "方案对比", "优劣",
]

_ARCHITECTURE_KEYWORDS = [
    "design", "architecture", "system", "platform", "framework",
    "microservice", "monolith", "distributed", "migration",
    "设计", "架构", "系统", "平台", "框架", "微服务", "迁移",
    "技术选型", "方案", "选型",
]

# Combined: tradeoff + architecture signals indicate risk/complexity
_TRADECTURE_KEYWORDS = _TRADEOFF_KEYWORDS + _ARCHITECTURE_KEYWORDS

_CONSTRAINT_INDICATORS = [
    re.compile(r"(同时|并且|同时满足|and also)", re.I),
    re.compile(r"(必须|must|need to|require).{0,10}(同时|且|and|同时)", re.I),
    re.compile(r"(限制|约束|constraint|limit|boundary|deadline)", re.I),
    re.compile(r"(不能|cannot|can't|unable).{0,10}(同时|且|and|同时)", re.I),
    # Chinese both-and patterns (no \b — word boundaries unreliable in CJK)
    re.compile(r"(既要|both).{0,20}(又要|还要|and)", re.I),
    # Multiple "need to" / imperative chaining
    re.compile(r"(同时需要|同时保证|同时考虑|同时兼顾|并且需要|并且要)", re.I),
    # English multi-constraint
    re.compile(r"(while|meanwhile).{0,20}(also|keeping|maintaining)", re.I),
]

_ARCHITECTURE_KEYWORDS = [
    "design", "architecture", "system", "platform", "framework",
    "microservice", "monolith", "distributed", "migration",
    "设计", "架构", "系统", "平台", "框架", "微服务", "迁移",
    "技术选型", "方案", "选型",
]


def should_enter_debate(context: str) -> bool:
    """
    Determine whether a user input should enter the debate/conflict/decision pipeline.

    Returns True ONLY if ANY of these conditions are met:
      1. Complexity: > 2 actionable constraints OR requires architecture decisions
      2. Risk: security / cost / performance / UX tradeoff present
      3. Multi-role: at least 2 roles have materially different perspectives

    Returns False (simple mode) for:
      - Greetings, trivial Q&A, single-intent requests
      - No tradeoff exists, no decision required
    """
    if not context or not context.strip():
        return False

    text = context.strip()
    text_lower = text.lower()

    # ── Phase 3: Block simple inputs ──
    # Check greetings
    for pattern in _GREETING_PATTERNS:
        if pattern.match(text):
            return False

    # Very short inputs (<=20 chars for Latin, <=10 chars for CJK-only)
    # CJK characters much more information per char
    import unicodedata
    has_cjk = any(
        unicodedata.category(c).startswith('Lo') and '\u4e00' <= c <= '\u9fff'
        for c in text
    )
    max_chars = 20 if not has_cjk else 8
    if len(text) <= max_chars:
        return False

    # ── Phase 1: Complexity threshold ──
    # Count actionable constraints
    constraint_count = 0
    for pattern in _CONSTRAINT_INDICATORS:
        if pattern.search(text):
            constraint_count += 1
            # "both-and" patterns (既要...又要) count as 2 constraints
            # because they express two simultaneous requirements
            if "既要" in pattern.pattern or "both" in pattern.pattern.lower():
                constraint_count += 1

    # Check for architecture/design keywords
    arch_signals = sum(1 for kw in _ARCHITECTURE_KEYWORDS if kw in text_lower)
    if arch_signals >= 1:
        constraint_count += 1

    if constraint_count >= 2:
        return True

    # ── Phase 2: Risk presence ──
    risk_signals = sum(1 for kw in _TRADECTURE_KEYWORDS if kw in text_lower)
    # "between X and Y" in English implies a tradeoff between two concerns
    if "between" in text_lower and "and" in text_lower:
        risk_signals += 1
    if risk_signals >= 2:
        return True

    # ── Phase 3: Multi-role necessity ──
    # If the question touches multiple domains simultaneously
    _DOMAIN_SIGNALS = {
        "technical": ["code", "api", "database", "server", "bug", "deploy",
                       "代码", "接口", "数据库", "服务器", "部署", "技术"],
        "product": ["feature", "user", "requirement", "priority", "roadmap",
                    "功能", "用户", "需求", "优先级", "产品"],
        "design": ["ui", "ux", "design", "layout", "visual", "interaction",
                   "设计", "界面", "交互", "视觉", "体验"],
        "business": ["cost", "revenue", "market", "budget", "pricing",
                     "成本", "收入", "市场", "预算", "价格"],
    }
    domains_hit = set()
    for domain, keywords in _DOMAIN_SIGNALS.items():
        if any(kw in text_lower for kw in keywords):
            domains_hit.add(domain)
    if len(domains_hit) >= 2:
        return True

    # ── Phase 4: Fallback — simple mode ──
    return False
