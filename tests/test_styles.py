from __future__ import annotations

from pathlib import Path

from asr_evo.postprocess.styles import StyleRegistry


def test_style_registry_loads_prompt_files(tmp_path: Path) -> None:
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    (prompts / "work-chat.txt").write_text("Make it polite.", encoding="utf-8")
    (prompts / "empty.md").write_text("  ", encoding="utf-8")

    registry = StyleRegistry(prompts_dir=prompts)

    style = registry.get("file:work-chat")
    assert style.label == "Work Chat"
    assert style.prompt == "Make it polite."
    assert "file:empty" not in [item.id for item in registry.all()]


def test_style_registry_falls_back_to_polished(tmp_path: Path) -> None:
    registry = StyleRegistry(prompts_dir=tmp_path)

    assert registry.get("missing").id == "polished"
