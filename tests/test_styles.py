from __future__ import annotations

from pathlib import Path

from asr_evo.postprocess.styles import StyleRegistry


def test_style_registry_loads_prompt_files(tmp_path: Path) -> None:
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    (prompts / "work-chat.txt").write_text("Make it polite.", encoding="utf-8")
    (prompts / "writing").mkdir()
    (prompts / "writing" / "email.txt").write_text("Write as email.", encoding="utf-8")
    (prompts / "writing" / "README.md").write_text("Nested docs only.", encoding="utf-8")
    (prompts / ".hidden").mkdir()
    (prompts / ".hidden" / "secret.txt").write_text("Ignore me.", encoding="utf-8")
    (prompts / "empty.md").write_text("  ", encoding="utf-8")
    (prompts / "README.md").write_text("Docs only.", encoding="utf-8")

    registry = StyleRegistry(prompts_dir=prompts)

    style = registry.get("work-chat")
    assert style.label == "work-chat.txt"
    assert style.prompt == "Make it polite."
    nested_style = registry.get("writing/email")
    assert nested_style.label == "email.txt"
    assert nested_style.category == ("writing",)
    assert nested_style.prompt == "Write as email."
    style_ids = [item.id for item in registry.all()]
    assert "writing/email" in style_ids
    assert "empty" not in style_ids
    assert "README" not in style_ids
    assert ".hidden/secret" not in style_ids


def test_style_registry_creates_empty_prompt_dir_without_default_files(tmp_path: Path) -> None:
    prompts = tmp_path / "prompts"

    registry = StyleRegistry(prompts_dir=prompts)

    assert prompts.exists()
    assert registry.all() == []


def test_style_registry_raises_when_no_prompt_files_exist(tmp_path: Path) -> None:
    registry = StyleRegistry(prompts_dir=tmp_path)

    try:
        registry.get("missing")
    except RuntimeError as exc:
        assert "No prompt files found" in str(exc)
    else:
        raise AssertionError("expected missing prompt files to raise")
