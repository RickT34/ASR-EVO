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


class AppConfig(BaseModel):
    hotkey: HotkeyConfig = HotkeyConfig()
    asr: ASRConfig = ASRConfig()
    llm: LLMConfig = LLMConfig()
    style: StyleConfig = StyleConfig()
    context: ContextConfig = ContextConfig()
    insert: InsertConfig = InsertConfig()
    audio: AudioConfig = AudioConfig()
    storage: StorageConfig = StorageConfig()

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
        }
        lines = []
        for section, values in sections.items():
            lines.append(f"[{section}]")
            for key, value in values.items():
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
    if value is None:
        return '""'
    escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'
