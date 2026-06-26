from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

import tomli_w
from dotenv import load_dotenv
from pydantic import BaseModel, Field

from asr_evo.core.context import ContextStore


class ControlConfig(BaseModel):
    port: int = Field(default=8765, ge=1, le=65535)


class ASRConfig(BaseModel):
    model: str = "qwen3-asr-flash"
    base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"


class LLMConfig(BaseModel):
    base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    model: str = "qwen-plus"
    enable_thinking: bool = False


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
    control: ControlConfig = ControlConfig()
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
            "control": self.control.model_dump(),
            "asr": self.asr.model_dump(),
            "llm": self.llm.model_dump(),
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


API_KEY_ENV = "DASHSCOPE_API_KEY"


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
    "control": [
        "外部触发控制接口。默认只监听 127.0.0.1，供本机工具调用。",
        "port 可改成其他本机端口；可用命令：asr-evo-control start | stop | toggle | status。",
    ],
    "asr": [
        "语音识别服务配置。API Key 从 .env 的 DASHSCOPE_API_KEY 读取。",
    ],
    "llm": [
        "文本润色模型配置。API Key 从 .env 的 DASHSCOPE_API_KEY 读取。",
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
        "状态栏图标和提示文字。symbol 使用 SF Symbols 名称，由 macOS 渲染为状态栏模板图标。",
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
    ("debug", "include_large_request_values"): [
        "设为 true 会打印完整大字段，例如音频 base64；只建议临时排查时开启。"
    ],
    ("debug", "max_request_value_chars"): ["普通字符串超过这个长度会被截断。"],
}
