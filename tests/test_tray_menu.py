from __future__ import annotations

from dataclasses import dataclass

from asr_evo.config import StatusConfig
from asr_evo.ui.menu import (
    MenuCommand,
    build_style_tree,
    command_title,
    control_menu_title,
    history_menu_records,
    input_device_menu_title,
    selected_input_device_title,
    stats_menu_lines,
    status_presentation,
)
from asr_evo.postprocess.styles import StyleDefinition


def test_build_style_tree_groups_nested_prompt_categories() -> None:
    root = build_style_tree(
        [
            StyleDefinition(
                id="通用润色",
                label="通用润色",
                prompt="prompt",
                source="prompts/通用润色.md",
            ),
            StyleDefinition(
                id="写作/邮件",
                label="邮件",
                prompt="prompt",
                source="prompts/写作/邮件.md",
                category=("写作",),
            ),
            StyleDefinition(
                id="写作/正式/公文",
                label="公文",
                prompt="prompt",
                source="prompts/写作/正式/公文.md",
                category=("写作", "正式"),
            ),
        ]
    )

    assert [style.id for style in root.styles] == ["通用润色"]
    assert [style.id for style in root.children["写作"].styles] == ["写作/邮件"]
    assert root.children["写作"].children["正式"].styles[0].id == "写作/正式/公文"


def test_selected_input_device_title_uses_selected_device_label() -> None:
    devices = [
        _Device(id="", label="系统默认输入", is_default=True),
        _Device(id="2", label="MacBook Pro 麦克风（系统默认）", is_default=False),
    ]

    assert selected_input_device_title(devices, "2") == "MacBook Pro 麦克风（系统默认）"
    assert selected_input_device_title(devices, "") == "系统默认输入"
    assert selected_input_device_title(devices, "9") == "设备 9（不可用）"
    assert input_device_menu_title(devices, "2") == "输入来源：MacBook Pro 麦克风（系统默认）"


def test_stats_menu_lines_format_totals_and_top_apps() -> None:
    totals, apps = stats_menu_lines(
        totals={"count": 2, "total_chars": 30, "total_audio_seconds": 3.25},
        app_stats=[_AppStats(app_name="Notes", count=2, total_chars=30)],
    )

    assert totals == ["听写次数：2", "累计字数：30", "累计音频：3.2 秒"]
    assert apps == ["Notes: 2 次，30 字"]


def test_history_menu_records_format_titles_and_previews() -> None:
    records = history_menu_records(
        [
            {
                "id": "abc",
                "app_name": "Notes",
                "bundle_id": "com.example.notes",
                "raw_text": " raw   text ",
                "final_text": " polished   text ",
                "user_edited_text": " user   edit ",
            }
        ]
    )

    assert records[0].id == "abc"
    assert records[0].title == "Notes: user edit"
    assert records[0].raw_preview == "原始：raw text"
    assert records[0].final_preview == "润色：polished text"
    assert records[0].user_edit_preview == "修订：user edit"


def test_status_presentation_uses_configured_symbol_and_text() -> None:
    status = status_presentation(StatusConfig(), "recording", "ready")

    assert status.symbol_name == "record.circle"
    assert status.tooltip == "正在录音：ready"

    reviewing = status_presentation(StatusConfig(), "reviewing")
    assert reviewing.symbol_name == "square.and.pencil"
    assert reviewing.tooltip == "等待确认文本"


def test_menu_command_titles_are_shared_for_platform_renderers() -> None:
    assert command_title(MenuCommand.TOGGLE_REVIEW) == "插入前确认文本"
    assert command_title(MenuCommand.REVEAL_PROMPTS) == "打开提示词文件夹"
    assert command_title(MenuCommand.COPY_HISTORY_FINAL) == "复制润色结果"
    assert command_title(MenuCommand.COPY_HISTORY_USER_EDIT) == "复制用户修订"
    assert control_menu_title("127.0.0.1:8765") == "外部控制：127.0.0.1:8765"


@dataclass(frozen=True)
class _Device:
    id: str
    label: str
    is_default: bool


@dataclass(frozen=True)
class _AppStats:
    app_name: str
    count: int
    total_chars: int
