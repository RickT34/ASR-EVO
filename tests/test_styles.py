from __future__ import annotations

from pathlib import Path

from asr_evo.postprocess.styles import StyleRegistry


def test_style_registry_loads_prompt_files(tmp_path: Path) -> None:
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    (prompts / "work-chat.txt").write_text("Make it polite.", encoding="utf-8")
    (prompts / "empty.md").write_text("  ", encoding="utf-8")
    (prompts / "README.md").write_text("Docs only.", encoding="utf-8")

    registry = StyleRegistry(prompts_dir=prompts)

    style = registry.get("file:work-chat")
    assert style.label == "work-chat.txt"
    assert style.prompt == "Make it polite."
    style_ids = [item.id for item in registry.all()]
    assert "file:empty" not in style_ids
    assert "file:README" not in style_ids


def test_style_registry_writes_default_prompt_files(tmp_path: Path) -> None:
    prompts = tmp_path / "prompts"

    registry = StyleRegistry(prompts_dir=prompts)

    assert (prompts / "exact.txt").exists()
    assert (prompts / "polished.txt").exists()
    assert (prompts / "concise.txt").exists()
    assert registry.get("polished").source == str(prompts / "polished.txt")


def test_style_registry_falls_back_to_polished(tmp_path: Path) -> None:
    registry = StyleRegistry(prompts_dir=tmp_path)

    assert registry.get("missing").id == "polished"
