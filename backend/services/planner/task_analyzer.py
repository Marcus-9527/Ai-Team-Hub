"""TaskAnalyzer — keyword-based natural language task analysis.

Extracts task type, complexity, and keywords from a natural language goal.
Rule-based, zero LLM calls.  ponytail: simple keyword matching; swap for
an LLM call when classification needs improve (e.g. "build a dashboard"
is both coding and design).
"""

from __future__ import annotations


TASK_TYPE_PATTERNS: dict[str, list[str]] = {
    "coding": [
        "write", "implement", "build", "code", "develop", "program",
        "script", "api", "backend", "frontend", "function", "class",
        "refactor", "debug", "fix", "test", "deploy", "migrate",
        # CJK
        "后端", "接口", "数据库", "服务", "编码", "编程", "实现",
        "开发", "调试", "修复", "重构", "部署", "迁移",
    ],
    "writing": [
        "write", "document", "draft", "compose", "edit", "rewrite",
        "summarize", "translate", "report", "article", "doc",
        # CJK
        "文档", "撰写", "编辑", "翻译", "报告", "总结",
    ],
    "analysis": [
        "analyze", "research", "investigate", "compare", "evaluate",
        "assess", "review", "audit", "inspect", "monitor", "metrics",
        # CJK
        "分析", "调研", "研究", "评估", "审查", "审计", "监控",
    ],
    "design": [
        "design", "ui", "ux", "layout", "mockup", "prototype",
        "wireframe", "visual", "style", "theme",
        # CJK
        "前端", "页面", "组件", "UI", "界面", "布局", "样式",
        "设计", "原型",
    ],
    "devops": [
        "deploy", "ci", "cd", "infrastructure", "config", "docker",
        "kubernetes", "monitor", "backup", "restore", "pipeline",
        # CJK
        "部署", "服务器", "容器", "监控", "备份", "配置",
    ],
    "testing": [
        "test", "testing", "regression", "verify", "validation",
        "assert", "coverage", "integration", "e2e",
        # CJK
        "测试", "验证", "回归", "覆盖率",
    ],
}


class TaskAnalysis:
    """Result of task analysis."""

    __slots__ = ("task_type", "complexity", "keywords")

    def __init__(self, task_type: str = "general",
                 complexity: str = "simple",
                 keywords: list[str] | None = None):
        self.task_type = task_type
        self.complexity = complexity
        self.keywords = keywords or []

    def to_dict(self) -> dict:
        return {
            "task_type": self.task_type,
            "complexity": self.complexity,
            "keywords": list(self.keywords),
        }


class TaskAnalyzer:
    """Analyze a natural language task goal."""

    def analyze(self, goal: str) -> TaskAnalysis:
        """Extract task_type, keywords, complexity from a goal string."""
        if not goal or not goal.strip():
            return TaskAnalysis()

        goal_lower = goal.lower()
        words = goal_lower.split()
        keywords = [w for w in words if len(w) > 2]

        # Score each task type
        scores: dict[str, int] = {}
        for ttype, patterns in TASK_TYPE_PATTERNS.items():
            score = sum(1 for p in patterns if p in goal_lower)
            if score:
                scores[ttype] = score

        task_type = max(scores, key=scores.get) if scores else "general"
        complexity = "complex" if len(words) > 20 else "simple"
        return TaskAnalysis(task_type=task_type, complexity=complexity,
                            keywords=keywords)
