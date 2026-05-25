from __future__ import annotations

from asr_evo.platforms.macos.tray import _build_style_tree
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
