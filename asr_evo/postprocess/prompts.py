from __future__ import annotations


STYLE_INSTRUCTIONS: dict[str, str] = {
    "exact": "尽量保留用户原意和表达，不主动扩写，只修正明显识别错误、标点和格式。",
    "polished": "在不改变事实和语气的前提下，将文本整理为自然、清楚、适合书面表达的中文。",
    "concise": "压缩冗余口语，使文本简洁直接，但不要丢失关键信息。",
}


def build_polish_messages(
    *,
    raw_text: str,
    context: str,
    style: str,
    custom_prompt: str = "",
) -> list[dict[str, str]]:
    instruction = custom_prompt.strip() or STYLE_INSTRUCTIONS.get(style, STYLE_INSTRUCTIONS["polished"])
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
            "content": f"处理要求：{instruction}\n\n" + "\n\n".join(user_parts),
        },
    ]
