from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from asr_evo.config import StatusConfig
from asr_evo.core.errors import ErrorFeedback


class StyleMenuItem(Protocol):
    id: str
    label: str
    category: tuple[str, ...]


class InputDeviceMenuItem(Protocol):
    id: str
    label: str
    is_default: bool


class AppStatsMenuItem(Protocol):
    app_name: str
    count: int
    total_chars: int


class MenuCommand(StrEnum):
    TOGGLE_REVIEW = "toggle_review"
    REVEAL_PROMPTS = "reveal_prompts"
    CLEAR_APP_STYLE = "clear_app_style"
    RELOAD_CONFIG = "reload_config"
    OPEN_CONFIG = "open_config"
    REFRESH_STATS = "refresh_stats"
    COPY_HISTORY_RAW = "copy_history_raw"
    COPY_HISTORY_FINAL = "copy_history_final"
    COPY_HISTORY_USER_EDIT = "copy_history_user_edit"
    COPY_ERROR = "copy_error"
    CLEAR_ERROR = "clear_error"
    QUIT = "quit"


@dataclass(frozen=True)
class MenuCommandSpec:
    command: MenuCommand
    title: str


@dataclass(frozen=True)
class TrayMenuActions:
    toggle_review: Callable[[], None]
    select_style: Callable[[str], None]
    reveal_prompts: Callable[[], None]
    reload_config: Callable[[], None]
    open_config: Callable[[], None]
    refresh_input_devices: Callable[[], None]
    select_input_device: Callable[[str], None]
    clear_app_style: Callable[[], None]
    refresh_app_binding: Callable[[], None]
    refresh_stats: Callable[[], None]
    copy_history_raw: Callable[[str], None]
    copy_history_final: Callable[[str], None]
    copy_history_user_edit: Callable[[str], None]
    copy_error: Callable[[], None]
    clear_error: Callable[[], None]
    quit: Callable[[], None]


@dataclass
class StyleMenuNode:
    name: str
    styles: list[StyleMenuItem]
    children: dict[str, "StyleMenuNode"]


@dataclass(frozen=True)
class HistoryMenuRecord:
    id: str
    title: str
    raw_preview: str
    final_preview: str
    user_edit_preview: str | None


@dataclass(frozen=True)
class StatusPresentation:
    title: str
    tooltip: str


PROMPT_MENU_TITLE = "润色风格与提示词"
INPUT_DEVICE_MENU_TITLE = "输入来源"
STATS_MENU_TITLE = "听写统计"
HISTORY_MENU_TITLE = "历史记录"
ERROR_MENU_TITLE = "当前错误"
APP_BINDING_UNKNOWN_TITLE = "当前应用绑定：未检测"
NO_INPUT_DEVICES_TITLE = "未找到输入设备"
NO_HISTORY_RECORDS_TITLE = "暂无历史记录"

MENU_COMMAND_SPECS = {
    MenuCommand.TOGGLE_REVIEW: MenuCommandSpec(
        command=MenuCommand.TOGGLE_REVIEW,
        title="插入前确认文本",
    ),
    MenuCommand.REVEAL_PROMPTS: MenuCommandSpec(
        command=MenuCommand.REVEAL_PROMPTS,
        title="打开提示词文件夹",
    ),
    MenuCommand.CLEAR_APP_STYLE: MenuCommandSpec(
        command=MenuCommand.CLEAR_APP_STYLE,
        title="清除当前应用绑定",
    ),
    MenuCommand.RELOAD_CONFIG: MenuCommandSpec(
        command=MenuCommand.RELOAD_CONFIG,
        title="重新加载配置",
    ),
    MenuCommand.OPEN_CONFIG: MenuCommandSpec(
        command=MenuCommand.OPEN_CONFIG,
        title="打开配置文件",
    ),
    MenuCommand.REFRESH_STATS: MenuCommandSpec(
        command=MenuCommand.REFRESH_STATS,
        title="刷新统计",
    ),
    MenuCommand.COPY_HISTORY_RAW: MenuCommandSpec(
        command=MenuCommand.COPY_HISTORY_RAW,
        title="复制原始转写",
    ),
    MenuCommand.COPY_HISTORY_FINAL: MenuCommandSpec(
        command=MenuCommand.COPY_HISTORY_FINAL,
        title="复制润色结果",
    ),
    MenuCommand.COPY_HISTORY_USER_EDIT: MenuCommandSpec(
        command=MenuCommand.COPY_HISTORY_USER_EDIT,
        title="复制用户修订",
    ),
    MenuCommand.COPY_ERROR: MenuCommandSpec(
        command=MenuCommand.COPY_ERROR,
        title="复制错误详情",
    ),
    MenuCommand.CLEAR_ERROR: MenuCommandSpec(
        command=MenuCommand.CLEAR_ERROR,
        title="清除错误状态",
    ),
    MenuCommand.QUIT: MenuCommandSpec(
        command=MenuCommand.QUIT,
        title="退出 ASR-EVO",
    ),
}


def command_title(command: MenuCommand) -> str:
    return MENU_COMMAND_SPECS[command].title


def control_menu_title(endpoint: str) -> str:
    return f"外部控制：{endpoint}"


def build_style_tree(styles: list[StyleMenuItem]) -> StyleMenuNode:
    root = StyleMenuNode(name="", styles=[], children={})
    for style in styles:
        node = root
        for category in style.category:
            node = node.children.setdefault(
                category,
                StyleMenuNode(name=category, styles=[], children={}),
            )
        node.styles.append(style)
    return root


def selected_input_device_title(
    devices: list[InputDeviceMenuItem],
    selected_device_id: str,
) -> str:
    for device in devices:
        if device.id == selected_device_id:
            return ellipsize(device.label, 24)
    if selected_device_id:
        return ellipsize(f"设备 {selected_device_id}（不可用）", 24)
    return "系统默认输入"


def input_device_menu_title(
    devices: list[InputDeviceMenuItem],
    selected_device_id: str,
) -> str:
    return f"输入来源：{selected_input_device_title(devices, selected_device_id)}"


def should_separate_input_device(
    devices: list[InputDeviceMenuItem],
    index: int,
) -> bool:
    return devices[index].is_default and index < len(devices) - 1


def stats_menu_lines(
    *,
    totals: dict[str, int | float],
    app_stats: list[AppStatsMenuItem],
    app_limit: int = 8,
) -> tuple[list[str], list[str]]:
    totals_lines = [
        f"听写次数：{totals.get('count', 0)}",
        f"累计字数：{totals.get('total_chars', 0)}",
        f"累计音频：{float(totals.get('total_audio_seconds', 0)):.1f} 秒",
    ]
    app_lines = [
        f"{stat.app_name}: {stat.count} 次，{stat.total_chars} 字"
        for stat in app_stats[:app_limit]
    ]
    return totals_lines, app_lines


def history_menu_records(records: list[dict], limit: int = 10) -> list[HistoryMenuRecord]:
    return [
        HistoryMenuRecord(
            id=str(record["id"]),
            title=history_title(record),
            raw_preview=readonly_preview_title("原始", record.get("raw_text", "")),
            final_preview=readonly_preview_title("润色", record.get("final_text", "")),
            user_edit_preview=(
                readonly_preview_title("修订", record.get("user_edited_text", ""))
                if record.get("user_edited_text")
                else None
            ),
        )
        for record in records[:limit]
    ]


def history_title(record: dict) -> str:
    text = " ".join(str(record.get("user_edited_text") or record.get("final_text", "")).split())
    if not text and record.get("raw_text"):
        text = "转写失败待重试"
    text = ellipsize(text, 24)
    app = record.get("app_name") or record.get("bundle_id") or "未知应用"
    return f"{app}: {text or '（空）'}"


def readonly_preview_title(label: str, value: str) -> str:
    text = ellipsize(" ".join(str(value).split()), 42) or "（空）"
    return f"{label}：{text}"


def error_feedback_lines(feedback: ErrorFeedback) -> list[str]:
    lines = [
        f"原因：{ellipsize(feedback.detail, 42)}",
        f"建议：{ellipsize(feedback.suggestion, 52)}",
    ]
    if feedback.raw_text_saved:
        lines.append("原始转写已保存到历史记录")
    if feedback.technical_detail and feedback.technical_detail != feedback.detail:
        lines.append(f"技术细节：{ellipsize(feedback.technical_detail, 52)}")
    return lines


def status_presentation(config: StatusConfig, state: str, detail: str = "") -> StatusPresentation:
    title = status_icon_map(config).get(state, "ASR")
    tooltip = status_text_map(config).get(state, state)
    if detail:
        tooltip = f"{tooltip}：{detail}"
    return StatusPresentation(title=title, tooltip=tooltip)


def status_icon_map(config: StatusConfig) -> dict[str, str]:
    return {
        "idle": config.idle_icon,
        "recording": config.recording_icon,
        "transcribing": config.transcribing_icon,
        "polishing": config.polishing_icon,
        "reviewing": config.reviewing_icon,
        "inserting": config.inserting_icon,
        "error": config.error_icon,
    }


def status_text_map(config: StatusConfig) -> dict[str, str]:
    return {
        "idle": config.idle_text,
        "recording": config.recording_text,
        "transcribing": config.transcribing_text,
        "polishing": config.polishing_text,
        "reviewing": config.reviewing_text,
        "inserting": config.inserting_text,
        "error": config.error_text,
    }


def ellipsize(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "..."
