from __future__ import annotations

import pytest

from preference_prompt_optimizer.core import EditSample, OptimizationReport, OptimizedPrompt
from preference_prompt_optimizer.io import load_jsonl, prompt_to_dict


def test_load_jsonl_reads_training_schema(tmp_path) -> None:
    path = tmp_path / "edits.jsonl"
    path.write_text(
        '{"input": "嗯继续写", "model_output": "我们继续写。", '
        '"user_edit": "继续写。", "prompt_instruction": "整理成聊天消息。", "segment": "chat"}\n',
        encoding="utf-8",
    )

    samples = load_jsonl(path)

    assert len(samples) == 1
    assert samples[0].input == "嗯继续写"
    assert samples[0].model_output == "我们继续写。"
    assert samples[0].user_edit == "继续写。"
    assert samples[0].prompt_instruction == "整理成聊天消息。"
    assert samples[0].segment == "chat"


def test_load_jsonl_rejects_old_alias_schema(tmp_path) -> None:
    path = tmp_path / "edits.jsonl"
    path.write_text('{"source": "嗯继续写", "model_output": "继续写。", "user_edit": "继续写。"}\n', encoding="utf-8")

    with pytest.raises(ValueError, match="input"):
        load_jsonl(path)


def test_prompt_to_dict_contains_report() -> None:
    prompt = OptimizedPrompt(
        system_addendum="rules",
        user_addendum="rules plus examples",
        rules=(),
        exemplars=(
            EditSample(
                input="嗯然后请跟进报价",
                model_output="请帮忙跟进报价，并在今天给出版本。",
                user_edit="请跟进报价，今天给一版。",
            ),
        ),
    )
    report = OptimizationReport(
        sample_count=1,
        segment="default",
        rule_count=0,
        avg_prompt_score=0.0,
        avg_similarity_before=0.5,
        recommended_min_samples=30,
        notes=(),
    )

    payload = prompt_to_dict(prompt, report)

    assert "system_addendum" in payload
    assert "report" in payload
