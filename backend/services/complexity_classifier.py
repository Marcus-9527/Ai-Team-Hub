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
