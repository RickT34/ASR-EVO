from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import tomli_w
from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, model_validator

from asr_evo.core.context import ContextStore


ASR_API_KEY_ENV = "ASR_API_KEY"
LLM_API_KEY_ENV = "LLM_API_KEY"


class ControlConfig(BaseModel):
    port: int = Field(default=8765, ge=1, le=65535)


class HotkeyConfig(BaseModel):
    enabled: bool = True
    toggle: str = "ctrl+alt+space"
    mode: Literal["toggle", "hold"] = "toggle"


class ASRConfig(BaseModel):
    backend: Literal["openai", "qwen_local"] = "openai"
    model: str = "qwen3-asr-flash"
    base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    api_key_env: str = Field(default=ASR_API_KEY_ENV, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    device: str = "auto"
    dtype: Literal["auto", "float32", "float16", "bfloat16"] = "auto"
    language: str = ""
    python_executable: str = ""
    timeout_seconds: float = Field(default=600, gt=0)


class LinuxConfig(BaseModel):
    tray: Literal["standard", "waybar"] = "standard"
    paste_shortcut: Literal["ctrl+v", "ctrl+shift+v"] = "ctrl+v"


class LLMProfileConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    backend: Literal["openai", "ollama"] = "openai"
    base_url: str
    model: str
    api_key_env: str = Field(default=LLM_API_KEY_ENV, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    enable_thinking: bool | None = None
    keep_alive_seconds: int = Field(default=0, ge=0)
    timeout_seconds: float = Field(default=300, gt=0)


class LLMConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default_profile: str = "balanced"
    profiles: dict[str, LLMProfileConfig] = Field(
        default_factory=lambda: {
            "balanced": LLMProfileConfig(
                base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                model="qwen-plus",
                api_key_env=LLM_API_KEY_ENV,
            )
        }
    )

    @model_validator(mode="after")
    def validate_profiles(self) -> "LLMConfig":
        invalid_aliases = [alias for alias in self.profiles if not alias or alias != alias.strip()]
        if invalid_aliases:
            raise ValueError("LLM profile aliases must be non-empty and have no surrounding spaces")
        if self.default_profile not in self.profiles:
            raise ValueError(f"default LLM profile not found: {self.default_profile}")
        return self

    def profile(self, alias: str) -> LLMProfileConfig:
        try:
            return self.profiles[alias]
        except KeyError as exc:
            raise ValueError(f"LLM profile not found: {alias}") from exc


class StyleConfig(BaseModel):
    mode: str = "通用润色"
    prompts_dir: str = "prompts"
    app_styles: dict[str, str] = Field(default_factory=dict)


class ContextConfig(BaseModel):
    enabled: bool = True
    ttl_seconds: int = Field(default=600, ge=1)
    max_items: int = Field(default=20, ge=1)
    max_chars: int = Field(default=6000, ge=1)
    scope: str = "app"

    def store(self) -> ContextStore:
        return ContextStore(
            ttl_seconds=self.ttl_seconds,
            max_items=self.max_items,
            max_chars=self.max_chars,
            scope=self.scope,
        )


class ReviewConfig(BaseModel):
    enabled: bool = True


class AudioConfig(BaseModel):
    input_device: str | int = ""


class StatusConfig(BaseModel):
    idle_symbol: str = "mic"
    recording_symbol: str = "record.circle"
    transcribing_symbol: str = "waveform"
    polishing_symbol: str = "text.alignleft"
    inserting_symbol: str = "text.insert"
    reviewing_symbol: str = "square.and.pencil"
    error_symbol: str = "exclamationmark.triangle"
    idle_text: str = "空闲"
    recording_text: str = "正在录音"
    transcribing_text: str = "正在转写"
    polishing_text: str = "正在润色"
    inserting_text: str = "正在插入"
    reviewing_text: str = "等待确认文本"
    error_text: str = "错误"


class DebugConfig(BaseModel):
    dump_remote_requests: bool = False
    include_large_request_values: bool = False
    max_request_value_chars: int = Field(default=4000, ge=0)


class AppConfig(BaseModel):
    _asr_api_key: str | None = PrivateAttr(default=None)
    _llm_profile_api_keys: dict[str, str | None] = PrivateAttr(default_factory=dict)

    control: ControlConfig = ControlConfig()
    hotkey: HotkeyConfig = HotkeyConfig()
    linux: LinuxConfig = LinuxConfig()
    asr: ASRConfig = ASRConfig()
    llm: LLMConfig = LLMConfig()
    style: StyleConfig = StyleConfig()
    context: ContextConfig = ContextConfig()
    review: ReviewConfig = ReviewConfig()
    audio: AudioConfig = AudioConfig()
    status: StatusConfig = StatusConfig()
    debug: DebugConfig = DebugConfig()

    @classmethod
    def load(cls, path: str | Path = "config.toml") -> "AppConfig":
        config_path = Path(path)
        data = {}
        if config_path.exists():
            data = tomllib.loads(config_path.read_text(encoding="utf-8"))
        config = cls.model_validate(data)
        dotenv = dotenv_values(".env")
        config._asr_api_key = _read_api_key(config.asr.api_key_env, dotenv)
        config._llm_profile_api_keys = {
            alias: _read_api_key(profile.api_key_env, dotenv)
            for alias, profile in config.llm.profiles.items()
        }
        return config

    def asr_api_key(self) -> str | None:
        return self._asr_api_key or os.getenv(self.asr.api_key_env)

    def llm_api_key(self, alias: str | None = None) -> str | None:
        alias = alias or self.llm.default_profile
        profile = self.llm.profile(alias)
        return self._llm_profile_api_keys.get(alias) or os.getenv(profile.api_key_env)

    def llm_api_keys(self) -> tuple[tuple[str, str | None], ...]:
        return tuple(
            (alias, self.llm_api_key(alias))
            for alias in sorted(self.llm.profiles)
        )

    def save(self, path: str | Path = "config.toml") -> None:
        config_path = Path(path)
        config_path.write_text(self.to_toml(), encoding="utf-8")

    def to_toml(self) -> str:
        sections = {
            "control": self.control.model_dump(),
            "hotkey": self.hotkey.model_dump(),
            "linux": self.linux.model_dump(),
            "asr": self.asr.model_dump(),
            "llm": self.llm.model_dump(exclude_none=True),
            "style": self.style.model_dump(),
            "context": self.context.model_dump(),
            "review": self.review.model_dump(),
            "audio": self.audio.model_dump(),
            "status": self.status.model_dump(),
            "debug": self.debug.model_dump(),
        }
        lines = []
        for section, values in sections.items():
            if comment := CONFIG_COMMENTS.get(section):
                lines.extend(f"# {line}" for line in comment)
            section_lines = tomli_w.dumps({section: values}).strip().splitlines()
            lines.append(section_lines[0])
            rendered_values = section_lines[1:]
            for rendered_line in rendered_values:
                if nested_key := _nested_table_key(rendered_line, section):
                    if comment := FIELD_COMMENTS.get((section, nested_key)):
                        lines.extend(f"# {line}" for line in comment)
                    lines.append(rendered_line)
                    continue
                key = rendered_line.split("=", 1)[0].strip()
                if comment := FIELD_COMMENTS.get((section, key)):
                    lines.extend(f"# {line}" for line in comment)
                lines.append(rendered_line)
            lines.append("")
        return "\n".join(lines)


def _nested_table_key(line: str, section: str) -> str:
    prefix = f"[{section}."
    if line.startswith(prefix) and line.endswith("]"):
        return line.removeprefix(prefix).removesuffix("]")
    return ""


def _read_api_key(
    name: str,
    dotenv: dict[str, str | None],
) -> str | None:
    dotenv_value = dotenv.get(name)
    return os.getenv(name) or (str(dotenv_value) if dotenv_value else None)


@dataclass(frozen=True)
class ProviderDefaults:
    asr_language: str = "zh"
    asr_enable_itn: bool = True
    asr_max_audio_mb: int = 10


@dataclass(frozen=True)
class AudioDefaults:
    sample_rate: int = 16000
    channels: int = 1


@dataclass(frozen=True)
class InsertDefaults:
    mode: str = "pasteboard_restore"
    fallback: str = "unicode_events"
    restore_delay_ms: int = 300


@dataclass(frozen=True)
class StorageDefaults:
    database_path: str = "data/asr_evo.sqlite3"


PROVIDER_DEFAULTS = ProviderDefaults()
AUDIO_DEFAULTS = AudioDefaults()
INSERT_DEFAULTS = InsertDefaults()
STORAGE_DEFAULTS = StorageDefaults()


CONFIG_COMMENTS: dict[str, list[str]] = {
    "linux": [
        "Linux：standard 使用 AppIndicator 托盘；waybar 使用自定义模块。切换后重启。",
        "快捷键由桌面/合成器绑定 asr-evo-control；终端可用 ctrl+shift+v 粘贴。",
    ],
    "control": [
        "外部触发控制接口。默认只监听 127.0.0.1，供本机工具调用。",
        "port 可改成其他本机端口；可用命令：asr-evo-control start | stop | toggle | status。",
    ],
    "hotkey": [
        "macOS 和 Windows 内置全局快捷键配置，也可用外部工具调用 asr-evo-control。",
        "toggle 使用 ctrl+alt+space 这类写法。",
        "mode = \"toggle\" 表示按一次切换；mode = \"hold\" 表示按下开始、释放停止。",
    ],
    "asr": [
        "语音识别服务配置。api_key_env 指向 .env 中保存密钥的变量名。",
    ],
    "llm": [
        "文本润色模型配置。每个 [llm.profiles.别名] 都可使用不同服务、模型和密钥变量。",
        "模板通过 llm_profile 选择别名；未指定时使用 default_profile。",
    ],
    "style": [
        "提示词风格配置。所有风格都来自 prompts_dir 目录中的 .md 文件。",
        "风格 id 是提示词文件名去掉扩展名，例如 通用润色.md 对应 通用润色。",
        "子文件夹会显示为子菜单，例如 写作/邮件.md 对应 写作/邮件。",
    ],
    "context": [
        "润色上下文配置。开启后，最近听写记录会作为上下文发给 LLM，用于更连贯地润色。",
    ],
    "review": [
        "用户确认配置。开启后，润色结果会先显示在文本框中，",
        "确认后再记录用户最终文本并插入到当前光标处。",
    ],
    "audio": [
        "录音输入配置。input_device 为空表示跟随系统默认输入设备。",
        "也可以填写 sounddevice 设备编号；在托盘菜单切换后会自动保存。",
    ],
    "status": [
        "状态栏图标和提示文字。symbol 目前由 macOS 映射到 SF Symbols；Windows 托盘使用内置状态图标和这些提示文字。",
    ],
    "debug": [
        "调试配置。开启后会把调试快照打印到 stderr。",
        "Authorization 会自动脱敏；音频 base64 默认只显示长度摘要。",
    ],
}


FIELD_COMMENTS: dict[tuple[str, str], list[str]] = {
    ("style", "app_styles"): [
        "按应用绑定风格，key 是 bundle id，value 是风格 id。",
        "示例：{ \"com.apple.TextEdit\" = \"通用润色\", \"md.obsidian\" = \"会议纪要\", \"com.apple.mail\" = \"写作/邮件\" }",
    ],
    ("context", "ttl_seconds"): ["超过这个时间的历史记录不会继续作为上下文传给 LLM。"],
    ("context", "max_items"): ["最多传入多少条近期听写记录。"],
    ("context", "max_chars"): ["最多传入多少个上下文字数。"],
    ("context", "scope"): ["上下文范围：app 表示同一应用，window 表示同一窗口，time 表示仅按时间。"],
    ("llm", "enable_thinking"): ["是否开启模型思考模式；默认关闭以减少延迟和额外输出。"],
    ("asr", "api_key_env"): ["指定 .env 中保存 ASR 密钥的变量名。"],
    ("llm", "default_profile"): ["模板未指定 llm_profile 时使用的模型别名。"],
    ("debug", "include_large_request_values"): [
        "设为 true 会打印完整大字段，例如音频 base64；只建议临时排查时开启。"
    ],
    ("debug", "max_request_value_chars"): ["普通字符串超过这个长度会被截断。"],
}
