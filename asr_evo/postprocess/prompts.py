from __future__ import annotations

def build_polish_messages(
    *,
    raw_text: str,
    context: str,
    prompt_instruction: str,
) -> list[dict[str, str]]:
    user_parts = []
    if context.strip():
        user_parts.append(context.strip())
    user_parts.append(f"当前语音识别文本：\n{raw_text.strip()}")
    return [
        {
            "role": "system",
            "content": (
                "你是一个听写文本后处理器。只输出最终要插入到用户光标位置的文本，"
                "不要解释，不要添加引号，不要输出候选项。"
            ),
        },
        {
            "role": "user",
            "content": f"处理要求：{prompt_instruction.strip()}\n\n" + "\n\n".join(user_parts),
        },
    ]
