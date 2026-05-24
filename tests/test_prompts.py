from __future__ import annotations

from asr_evo.postprocess.prompts import build_polish_messages


def test_prompt_outputs_only_final_text_instruction() -> None:
    messages = build_polish_messages(
        raw_text="今天我们继续写这个项目",
        context="最近同一上下文中已经插入的文本：\n1. 这是前文。",
        prompt_instruction="整理为自然清楚的中文。只输出最终文本。",
    )

    assert messages[0]["role"] == "system"
    assert "只输出最终" in messages[0]["content"]
    assert "这是前文" in messages[1]["content"]
    assert "当前语音识别文本" in messages[1]["content"]
