from __future__ import annotations

import os
import tomllib
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field


class HotkeyConfig(BaseModel):
    toggle: str = "cmd+shift+space"
    mode: str = "toggle"


class ASRConfig(BaseModel):
    model: str = "qwen3-asr-flash"
    base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"


class LLMConfig(BaseModel):
    base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    model: str = "qwen-plus"


class StyleConfig(BaseModel):
    mode: str = "通用润色"
    prompts_dir: str = "prompts"
    app_styles: dict[str, str] = Field(default_factory=dict)


class ContextConfig(BaseModel):
    enabled: bool = True
    ttl_seconds: int = Field(default=600, ge=1)
    max_items: int = Field(default=20, ge=1)


class AudioConfig(BaseModel):
    input_device: str | int = ""


class StatusConfig(BaseModel):
    idle_icon: str = "ASR"
    recording_icon: str = "REC ASR"
    transcribing_icon: str = "... ASR"
    polishing_icon: str = "TXT ASR"
    inserting_icon: str = "INS ASR"
    error_icon: str = "! ASR"
    idle_text: str = "空闲"
    recording_text: str = "正在录音，再按快捷键停止"
    transcribing_text: str = "正在转写"
    polishing_text: str = "正在润色"
    inserting_text: str = "正在插入"
    error_text: str = "错误"


class AppConfig(BaseModel):
    hotkey: HotkeyConfig = HotkeyConfig()
    asr: ASRConfig = ASRConfig()
    llm: LLMConfig = LLMConfig()
    style: StyleConfig = StyleConfig()
    context: ContextConfig = ContextConfig()
    audio: AudioConfig = AudioConfig()
    status: StatusConfig = StatusConfig()

    @classmethod
    def load(cls, path: str | Path = "config.toml") -> "AppConfig":
        load_dotenv()
        config_path = Path(path)
        data = {}
        if config_path.exists():
            data = tomllib.loads(config_path.read_text(encoding="utf-8"))
        return cls.model_validate(data)

    def api_key(self) -> str | None:
        return os.getenv(API_KEY_ENV)

    def save(self, path: str | Path = "config.toml") -> None:
        config_path = Path(path)
        config_path.write_text(self.to_toml(), encoding="utf-8")

    def to_toml(self) -> str:
        sections = {
            "hotkey": self.hotkey.model_dump(),
            "asr": self.asr.model_dump(),
            "llm": self.llm.model_dump(),
            "style": self.style.model_dump(),
            "context": self.context.model_dump(),
            "audio": self.audio.model_dump(),
            "status": self.status.model_dump(),
        }
        lines = []
        for section, values in sections.items():
            if comment := CONFIG_COMMENTS.get(section):
                lines.extend(f"# {line}" for line in comment)
            lines.append(f"[{section}]")
            for key, value in values.items():
                if comment := FIELD_COMMENTS.get((section, key)):
                    lines.extend(f"# {line}" for line in comment)
                lines.append(f"{key} = {_toml_value(value)}")
            lines.append("")
        return "\n".join(lines)


def _toml_value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    if isinstance(value, dict):
        if not value:
            return "{}"
        items = []
        for key, item_value in value.items():
            escaped_key = str(key).replace("\\", "\\\\").replace('"', '\\"')
            items.append(f'"{escaped_key}" = {_toml_value(item_value)}')
        return "{ " + ", ".join(items) + " }"
    if value is None:
        return '""'
    escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


API_KEY_ENV = "DASHSCOPE_API_KEY"
ASR_LANGUAGE = "zh"
ASR_ENABLE_ITN = True
ASR_MAX_AUDIO_MB = 10
AUDIO_SAMPLE_RATE = 16000
AUDIO_CHANNELS = 1
CONTEXT_MAX_CHARS = 6000
CONTEXT_SCOPE = "app"
INSERT_MODE = "pasteboard_restore"
INSERT_FALLBACK = "unicode_events"
INSERT_RESTORE_DELAY_MS = 300
STORAGE_DATABASE_PATH = "data/asr_evo.sqlite3"


CONFIG_COMMENTS: dict[str, list[str]] = {
    "hotkey": [
        "全局快捷键。mode = \"toggle\" 表示按一次开始、再按一次停止；",
        "mode = \"hold\" 表示按住录音、松开停止。地球仪键可写为 \"globe\" 或 \"fn\"。",
        "修改后请在托盘点击“重新加载配置”。",
    ],
    "asr": [
        "语音识别服务配置。API Key 从 .env 的 DASHSCOPE_API_KEY 读取。",
    ],
    "llm": [
        "文本润色模型配置。API Key 从 .env 的 DASHSCOPE_API_KEY 读取。",
    ],
    "style": [
        "提示词风格配置。所有风格都来自 prompts_dir 目录中的 .txt/.md 文件。",
        "风格 id 是提示词文件名去掉扩展名，例如 通用润色.txt 对应 通用润色。",
        "子文件夹会显示为子菜单，例如 写作/邮件.txt 对应 写作/邮件。",
    ],
    "context": [
        "短期上下文配置。开启后，最近听写记录会作为上下文发给 LLM，用于更连贯地润色。",
    ],
    "audio": [
        "录音输入配置。input_device 为空表示跟随系统默认输入设备。",
        "也可以填写 sounddevice 设备编号；在托盘菜单切换后会自动保存。",
    ],
    "status": [
        "状态栏图标和提示文字。icon 会直接显示在 macOS 状态栏中，建议保持简短。",
    ],
}


FIELD_COMMENTS: dict[tuple[str, str], list[str]] = {
    ("style", "app_styles"): [
        "按应用绑定风格，key 是 bundle id，value 是风格 id。",
        "示例：{ \"com.apple.TextEdit\" = \"通用润色\", \"md.obsidian\" = \"会议纪要\", \"com.apple.mail\" = \"写作/邮件\" }",
    ],
    ("context", "ttl_seconds"): ["超过这个时间的短期上下文不会继续传给 LLM。"],
    ("context", "max_items"): ["最多传入多少条近期听写记录。"],
}
