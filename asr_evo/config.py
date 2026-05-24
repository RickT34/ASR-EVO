from __future__ import annotations

import os
import tomllib
from enum import StrEnum
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field


class ContextScope(StrEnum):
    TIME = "time"
    APP = "app"
    WINDOW = "window"


class HotkeyConfig(BaseModel):
    toggle: str = "cmd+shift+space"
    mode: str = "toggle"


class ASRConfig(BaseModel):
    provider: str = "aliyun"
    model: str = "qwen3-asr-flash"
    base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    api_key_env: str = "DASHSCOPE_API_KEY"
    language: str | None = "zh"
    enable_itn: bool = True
    max_audio_mb: int = Field(default=10, ge=1)


class LLMConfig(BaseModel):
    provider: str = "openai_compat"
    base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    model: str = "qwen-plus"
    api_key_env: str = "DASHSCOPE_API_KEY"


class StyleConfig(BaseModel):
    mode: str = "polished"
    custom_prompt: str = ""
    prompts_dir: str = "prompts"
    app_styles: dict[str, str] = Field(default_factory=dict)


class ContextConfig(BaseModel):
    enabled: bool = True
    ttl_seconds: int = Field(default=600, ge=1)
    max_items: int = Field(default=20, ge=1)
    max_chars: int = Field(default=6000, ge=256)
    scope: ContextScope = ContextScope.APP


class InsertConfig(BaseModel):
    mode: str = "pasteboard_restore"
    fallback: str = "unicode_events"
    restore_delay_ms: int = Field(default=300, ge=50)


class AudioConfig(BaseModel):
    sample_rate: int = Field(default=16000, ge=8000)
    channels: int = Field(default=1, ge=1)


class StorageConfig(BaseModel):
    enabled: bool = True
    database_path: str = "data/asr_evo.sqlite3"


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
    insert: InsertConfig = InsertConfig()
    audio: AudioConfig = AudioConfig()
    storage: StorageConfig = StorageConfig()
    status: StatusConfig = StatusConfig()

    @classmethod
    def load(cls, path: str | Path = "config.toml") -> "AppConfig":
        load_dotenv()
        config_path = Path(path)
        data = {}
        if config_path.exists():
            data = tomllib.loads(config_path.read_text(encoding="utf-8"))
        return cls.model_validate(data)

    def llm_api_key(self) -> str | None:
        return os.getenv(self.llm.api_key_env)

    def asr_api_key(self) -> str | None:
        return os.getenv(self.asr.api_key_env)

    def save(self, path: str | Path = "config.toml") -> None:
        config_path = Path(path)
        config_path.write_text(self.to_toml(), encoding="utf-8")

    def to_toml(self) -> str:
        sections = {
            "hotkey": self.hotkey.model_dump(),
            "asr": self.asr.model_dump(),
            "llm": self.llm.model_dump(),
            "style": self.style.model_dump(),
            "context": {
                **self.context.model_dump(),
                "scope": self.context.scope.value,
            },
            "insert": self.insert.model_dump(),
            "audio": self.audio.model_dump(),
            "storage": self.storage.model_dump(),
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


def save_env_value(key: str, value: str, path: str | Path = ".env") -> None:
    env_path = Path(path)
    lines = []
    found = False
    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines()
    next_lines = []
    for line in lines:
        if line.startswith(f"{key}="):
            next_lines.append(f"{key}={value}")
            found = True
        else:
            next_lines.append(line)
    if not found:
        next_lines.append(f"{key}={value}")
    env_path.write_text("\n".join(next_lines) + "\n", encoding="utf-8")
    os.environ[key] = value


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


CONFIG_COMMENTS: dict[str, list[str]] = {
    "hotkey": [
        "全局快捷键。mode = \"toggle\" 表示按一次开始、再按一次停止；",
        "mode = \"hold\" 表示按住录音、松开停止。地球仪键可写为 \"globe\" 或 \"fn\"。",
        "修改后请在托盘点击“重新加载配置”。",
    ],
    "asr": [
        "语音识别服务配置。默认使用阿里 DashScope 的 OpenAI-compatible endpoint。",
        "api_key_env 指向 .env 或环境变量中的密钥名称，不要把真实密钥写进本文件。",
    ],
    "llm": [
        "文本润色模型配置。任何 OpenAI-compatible API 都可以通过 base_url/model/api_key_env 接入。",
    ],
    "style": [
        "提示词风格配置。所有风格都来自 prompts_dir 目录中的 .txt/.md 文件。",
        "mode 是默认风格 id；默认提示词文件名 exact.txt/polished.txt/concise.txt 对应 exact/polished/concise。",
        "其他文件会使用 file:<文件名> 作为 id，例如 prompts/会议纪要.txt 对应 file:会议纪要。",
    ],
    "context": [
        "短期上下文配置。开启后，最近听写记录会作为上下文发给 LLM，用于更连贯地润色。",
    ],
    "insert": [
        "文本插入配置。默认通过临时剪贴板粘贴并恢复原剪贴板，兼容性最好。",
    ],
    "audio": [
        "录音参数。除非供应商要求其他格式，通常不需要修改。",
    ],
    "storage": [
        "持久化历史配置。开启后可在托盘历史记录中复制原始转写或 AI 润色结果。",
    ],
    "status": [
        "状态栏图标和提示文字。icon 会直接显示在 macOS 状态栏中，建议保持简短。",
    ],
}


FIELD_COMMENTS: dict[tuple[str, str], list[str]] = {
    ("style", "custom_prompt"): [
        "非空时会覆盖当前风格文件中的提示词；通常建议保持为空，直接编辑 prompts_dir 里的文件。",
    ],
    ("style", "app_styles"): [
        "按应用绑定风格，key 是 bundle id，value 是风格 id。",
        "示例：{ \"com.apple.TextEdit\" = \"polished\", \"md.obsidian\" = \"file:会议纪要\" }",
    ],
    ("context", "ttl_seconds"): ["超过这个时间的短期上下文不会继续传给 LLM。"],
    ("context", "max_items"): ["最多传入多少条近期听写记录。"],
    ("context", "max_chars"): ["传给 LLM 的上下文总字符上限，用于控制速度、成本和隐私暴露面。"],
    ("context", "scope"): [
        "\"app\" 表示只使用同一应用的上下文；\"time\" 表示跨应用按时间取最近记录；\"window\" 预留给更细粒度窗口上下文。",
    ],
}
