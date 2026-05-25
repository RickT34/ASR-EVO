from __future__ import annotations

from dataclasses import dataclass

from asr_evo.platforms.macos.tray import _build_style_tree, _selected_input_device_title
from asr_evo.postprocess.styles import StyleDefinition


def test_build_style_tree_groups_nested_prompt_categories() -> None:
    root = _build_style_tree(
        [
            StyleDefinition(
                id="通用润色",
                label="通用润色.txt",
                prompt="prompt",
                source="prompts/通用润色.txt",
            ),
            StyleDefinition(
                id="写作/邮件",
                label="邮件.txt",
                prompt="prompt",
                source="prompts/写作/邮件.txt",
                category=("写作",),
            ),
            StyleDefinition(
                id="写作/正式/公文",
                label="公文.txt",
                prompt="prompt",
                source="prompts/写作/正式/公文.txt",
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

    assert _selected_input_device_title(devices, "2") == "MacBook Pro 麦克风（系统默认）"
    assert _selected_input_device_title(devices, "") == "系统默认输入"
    assert _selected_input_device_title(devices, "9") == "设备 9（不可用）"


@dataclass(frozen=True)
class _Device:
    id: str
    label: str
    is_default: bool
