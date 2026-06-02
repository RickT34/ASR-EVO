from __future__ import annotations

import os

import pytest

from asr_evo.config import AppConfig
from asr_evo.providers.factory import create_llm_provider
from preference_prompt_optimizer.core import (
    EditSample,
    LLMPreferenceExtractor,
    LLMPreferenceScorer,
    PreferencePromptOptimizer,
    PreferenceOptimizerError,
    build_extraction_messages,
    build_scoring_messages,
    parse_rule_response,
    parse_score_response,
)


def test_build_extraction_messages_contains_schema_and_samples() -> None:
    messages = build_extraction_messages(chat_samples())

    assert messages[0]["role"] == "system"
    assert "Return only JSON" in messages[0]["content"]
    assert "Allowed categories" in messages[1]["content"]
    assert "chat-001" in messages[1]["content"]
    assert "user_edit" in messages[1]["content"]


def test_build_scoring_messages_contains_candidate_prompt_and_samples() -> None:
    prompt = make_prompt()
    samples = chat_samples()
    samples[0] = EditSample(
        sample_id=samples[0].sample_id,
        input="最近同一上下文中已经插入的文本：\n1. prior accepted text\n\n当前语音识别文本：\n"
        + samples[0].input,
        model_output=samples[0].model_output,
        user_edit=samples[0].user_edit,
        prompt_instruction="整理成简洁聊天消息。",
        segment=samples[0].segment,
    )

    messages = build_scoring_messages(samples, prompt)

    assert messages[0]["role"] == "system"
    assert "strict prompt evaluator" in messages[0]["content"]
    assert "Candidate prompt" in messages[1]["content"]
    assert "input_seen_by_model" in messages[1]["content"]
    assert "prompt_instruction_under_optimization" in messages[1]["content"]
    assert "整理成简洁聊天消息" in messages[1]["content"]
    assert "prior accepted text" in messages[1]["content"]
    assert "user_expected_output" in messages[1]["content"]
    assert "chat-001" in messages[1]["content"]


def test_parse_rule_response_rejects_unknown_category() -> None:
    with pytest.raises(PreferenceOptimizerError, match="unknown category"):
        parse_rule_response(
            {
                "rules": [
                    {
                        "category": "not_a_category",
                        "instruction": "Do something.",
                    }
                ]
            }
        )


def test_parse_score_response_clamps_values() -> None:
    score = parse_score_response(
        {
            "score": 1.2,
            "sample_scores": {"a": -1, "b": 0.7},
            "rationale": "ok",
        }
    )

    assert score.score == 1.0
    assert score.sample_scores == {"a": 0.0, "b": 0.7}


async def test_optimizer_runs_multiple_rounds_and_keeps_best_score() -> None:
    client = ScriptedJSONClient(
        [
            {
                "rules": [
                    {
                        "category": "concision",
                        "instruction": "Prefer concise revisions.",
                        "evidence": ["chat-001"],
                        "support": 1,
                        "confidence": 0.7,
                    }
                ]
            },
            {"score": 0.62, "sample_scores": {"chat-001": 0.6}, "rationale": "first"},
            {
                "rules": [
                    {
                        "category": "format",
                        "instruction": "Avoid unnecessary bullets and headings.",
                        "evidence": ["chat-001"],
                        "support": 1,
                        "confidence": 0.82,
                    }
                ]
            },
            {"score": 0.81, "sample_scores": {"chat-001": 0.8}, "rationale": "better"},
        ]
    )
    optimizer = PreferencePromptOptimizer(
        LLMPreferenceExtractor(client, batch_size=2),
        scorer=LLMPreferenceScorer(client),
    )

    optimized = await optimizer.optimize(chat_samples(), segment="chat", rounds=2)

    assert optimized.score == 0.81
    assert len(optimized.rounds) == 2
    assert optimized.rounds[0].score == 0.62
    assert optimized.rounds[1].score == 0.81
    assert "Avoid unnecessary bullets" in optimized.system_addendum
    assert len(client.calls) == 4


@pytest.mark.integration
async def test_optimizer_uses_real_llm_api_when_configured() -> None:
    if not os.environ.get("DASHSCOPE_API_KEY"):
        pytest.skip("Set DASHSCOPE_API_KEY to run the real LLM API integration test.")

    client = create_llm_provider(AppConfig.load())
    optimizer = PreferencePromptOptimizer(LLMPreferenceExtractor(client, batch_size=2))
    try:
        optimized = await optimizer.optimize(chat_samples(), segment="chat", max_rules=4)
    finally:
        await client.aclose()

    assert optimized.rules
    assert optimized.system_addendum
    assert "Representative accepted edits" in optimized.user_addendum


def chat_samples() -> list[EditSample]:
    return [
        EditSample(
            sample_id="chat-001",
            input="嗯然后请你帮我跟进一下报价单",
            model_output="### 待办事项\n- 请帮我跟进一下报价单，并在今天下午三点前给我一个版本。",
            user_edit="请帮忙跟进报价单，今天下午三点前给我一版。",
            segment="chat",
        ),
        EditSample(
            sample_id="chat-002",
            input="那个今天开会我们主要讨论API timeout和retry",
            model_output="- 今天会议主要讨论了 API timeout 和 retry 相关问题，并形成了后续行动项。",
            user_edit="今天主要讨论 API timeout 和 retry 的问题。",
            segment="chat",
        ),
    ]


def make_prompt():
    from preference_prompt_optimizer.core import OptimizedPrompt, PreferenceRule, RuleCategory

    rule = PreferenceRule(
        category=RuleCategory.CONCISION,
        instruction="Prefer concise revisions.",
        evidence=("chat-001",),
        support=1,
        confidence=0.8,
    )
    return OptimizedPrompt(
        system_addendum="User preference rules inferred from accepted edits:\n1. Prefer concise revisions.",
        user_addendum="User preference rules inferred from accepted edits:\n1. Prefer concise revisions.",
        rules=(rule,),
        exemplars=tuple(chat_samples()[:1]),
        score=0.8,
    )


class ScriptedJSONClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    async def complete_json(self, messages, *, temperature=0):
        self.calls.append((messages, temperature))
        if not self._responses:
            raise AssertionError("No scripted response left")
        return self._responses.pop(0)
