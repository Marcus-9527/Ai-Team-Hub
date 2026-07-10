"""
test_debate_gating.py — Test suite for should_enter_debate() trigger gating.

Verifies:
  Phase 1: Complexity threshold → triggers debate
  Phase 2: Risk presence → triggers debate
  Phase 3: Multi-role necessity → triggers debate
  Phase 3: Block simple inputs → does NOT trigger debate
  Phase 4: Fallback → does NOT trigger debate
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from backend.services.complexity_classifier import should_enter_debate


# ── Phase 3: Block Simple Inputs ──

class TestBlockSimpleInputs:
    """Phase 3: greetings, trivial inputs, single-intent must NOT enter debate."""

    def test_greeting_english(self):
        assert should_enter_debate("hello") is False
        assert should_enter_debate("hi") is False
        assert should_enter_debate("hey") is False
        assert should_enter_debate("yo") is False
        assert should_enter_debate("sup") is False
        assert should_enter_debate("howdy") is False
        assert should_enter_debate("greetings") is False

    def test_greeting_chinese(self):
        assert should_enter_debate("你好") is False
        assert should_enter_debate("嗨") is False
        assert should_enter_debate("哈喽") is False
        assert should_enter_debate("早上好") is False
        assert should_enter_debate("下午好") is False

    def test_thanks(self):
        assert should_enter_debate("谢谢") is False
        assert should_enter_debate("thanks") is False
        assert should_enter_debate("thank you") is False

    def test_acknowledgment(self):
        assert should_enter_debate("好的") is False
        assert should_enter_debate("ok") is False
        assert should_enter_debate("okay") is False
        assert should_enter_debate("sure") is False
        assert should_enter_debate("行") is False
        assert should_enter_debate("嗯") is False

    def test_farewell(self):
        assert should_enter_debate("bye") is False
        assert should_enter_debate("goodbye") is False
        assert should_enter_debate("see you") is False
        assert should_enter_debate("再见") is False
        assert should_enter_debate("拜拜") is False

    def test_trivial_short_input(self):
        assert should_enter_debate("lol") is False
        assert should_enter_debate("haha") is False
        assert should_enter_debate("what") is False

    def test_empty_input(self):
        assert should_enter_debate("") is False
        assert should_enter_debate("   ") is False
        assert should_enter_debate(None) is False

    def test_punctuation_only(self):
        assert should_enter_debate("...") is False
        assert should_enter_debate("?!") is False

    def test_single_intent_trivial(self):
        assert should_enter_debate("天气") is False
        assert should_enter_debate("time") is False


# ── Phase 1: Complexity Threshold ──

class TestComplexityThreshold:
    """Phase 1: > 2 actionable constraints OR architecture decisions → debate."""

    def test_multiple_constraints_chinese(self):
        assert should_enter_debate(
            "既要保证性能，又要确保数据安全，同时还要控制成本"
        ) is True

    def test_multiple_constraints_english(self):
        assert should_enter_debate(
            "We need performance and also security while keeping costs low"
        ) is True

    def test_constraint_with_architecture(self):
        assert should_enter_debate(
            "设计一个系统，需要同时满足高并发和低延迟"
        ) is True

    def test_constraint_pattern_both_and(self):
        assert should_enter_debate(
            "既要快速上线，又要保证代码质量"
        ) is True

    def test_complex_api_with_security(self):
        assert should_enter_debate(
            "Design an API system that handles 10k req/s with strict security compliance"
        ) is True

    def test_single_constraint_not_enough(self):
        # Only 1 constraint signal → should not trigger
        assert should_enter_debate(
            "需要控制成本"
        ) is False

    def test_architecture_keyword_triggers(self):
        assert should_enter_debate(
            "架构设计需要考虑扩展性"
        ) is True

    def test_design_technical_choice(self):
        assert should_enter_debate(
            "技术选型：微服务架构 vs 单体部署，需要考虑团队规模"
        ) is True


# ── Phase 2: Risk Presence ──

class TestRiskPresence:
    """Phase 2: security / cost / performance / UX tradeoff → debate."""

    def test_risk_and_performance(self):
        assert should_enter_debate(
            "这个方案有性能风险，需要权衡安全"
        ) is True

    def test_cost_and_security_tradeoff(self):
        assert should_enter_debate(
            "Security improvements will increase cost, need to balance"
        ) is True

    def test_ux_vs_performance(self):
        assert should_enter_debate(
            "UX和性能之间的权衡"
        ) is True

    def test_scalability_concern(self):
        assert should_enter_debate(
            "系统扩展性有风险，成本也会增加"
        ) is True

    def test_single_risk_keyword_not_enough(self):
        # Only 1 risk keyword → should not trigger
        assert should_enter_debate(
            "这里有风险"
        ) is False

    def test_tradeoff_explicit(self):
        assert should_enter_debate(
            "tradeoff between latency and consistency"
        ) is True


# ── Phase 3: Multi-role Necessity ──

class TestMultiRoleNecessity:
    """Phase 3: question touches ≥2 domains → debate."""

    def test_technical_and_product(self):
        assert should_enter_debate(
            "这个功能用户需要，但API实现很复杂"
        ) is True

    def test_design_and_business(self):
        assert should_enter_debate(
            "界面设计要考虑用户需求和成本预算"
        ) is True

    def test_code_and_ux(self):
        assert should_enter_debate(
            "前端代码优化对用户体验的影响"
        ) is True

    def test_single_domain_only(self):
        # Only technical domain → no multi-role need
        assert should_enter_debate(
            "写一个Python函数"
        ) is False

    def test_only_product_domain(self):
        assert should_enter_debate(
            "用户需要什么功能"
        ) is False


# ── Phase 4: Fallback ──

class TestFallback:
    """Phase 4: no strong signals → simple mode."""

    def test_casual_question(self):
        assert should_enter_debate(
            "Python怎么读取文件"
        ) is False

    def test_simple_translation(self):
        assert should_enter_debate(
            "翻译一下这段话"
        ) is False

    def test_simple_explanation(self):
        assert should_enter_debate(
            "解释一下什么是REST"
        ) is False

    def test_straightforward_coding(self):
        assert should_enter_debate(
            "写一个冒泡排序"
        ) is False


# ── Edge Cases ──

class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_mixed_greeting_with_real_question(self):
        # If it starts with greeting but has real content after, check full text
        # "hello" alone is blocked, but "hello, need to design..." is complex
        result = should_enter_debate(
            "你好，我需要设计一个系统架构，同时保证性能和安全性"
        )
        # This starts with greeting but has strong complexity signals
        # The greeting pattern matches the START only, so this should pass through
        assert result is True

    def test_very_long_complex_input(self):
        long_text = "性能 " * 50 + "安全 " * 50 + "成本 " * 50
        assert should_enter_debate(long_text) is True

    def test_greeting_with_punctuation_variation(self):
        assert should_enter_debate("hi!") is False
        assert should_enter_debate("hey.") is False
        assert should_enter_debate("hello?") is False
