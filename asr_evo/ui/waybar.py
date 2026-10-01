from __future__ import annotations

from html import escape


STATES = {
    "idle": "空闲",
    "recording": "正在录音",
    "transcribing": "正在转写",
    "polishing": "正在润色",
    "reviewing": "等待确认文本",
    "inserting": "正在插入",
    "error": "错误",
    "offline": "未启动",
}


def waybar_status(response: dict | None) -> dict[str, str]:
    state = str(response.get("state", "error")) if response else "offline"
    if state not in STATES or (response and not response.get("ok")):
        state = "error"
    detail = (response or {}).get("detail") or (response or {}).get("error") or STATES[state]
    return {
        "text": "",
        "alt": state,
        "class": state,
        "tooltip": escape(f"ASR-EVO · {detail}"),
    }
