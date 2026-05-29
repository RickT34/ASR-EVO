from __future__ import annotations

from pathlib import Path

from asr_evo.config import AppConfig
from asr_evo.core.ports import AppContext
from asr_evo.core.style_binding import StyleBindingService
from asr_evo.postprocess.styles import StyleRegistry


def test_style_binding_syncs_app_specific_style(tmp_path: Path) -> None:
    prompts = _write_prompts(tmp_path)
    config = AppConfig()
    config.style.prompts_dir = str(prompts)
    config.style.mode = "通用润色"
    config.style.app_styles["com.example.mail"] = "情景/邮件"
    service = StyleBindingService(config=config, styles=StyleRegistry(prompts_dir=prompts))

    sync = service.sync_for_app(AppContext(bundle_id="com.example.mail", app_name="Mail"))

    assert sync.style_id == "情景/邮件"
    assert service.current_style_id == "情景/邮件"
    assert sync.summary == "当前应用绑定：Mail -> 邮件"


def test_style_binding_falls_back_when_bound_style_is_missing(tmp_path: Path) -> None:
    prompts = _write_prompts(tmp_path)
    config = AppConfig()
    config.style.prompts_dir = str(prompts)
    config.style.app_styles["com.example.mail"] = "不存在"
    service = StyleBindingService(config=config, styles=StyleRegistry(prompts_dir=prompts))

    sync = service.sync_for_app(AppContext(bundle_id="com.example.mail", app_name="Mail"))

    assert sync.style_id == "通用润色"
    assert sync.warning == "应用绑定的风格不存在：不存在"
    assert sync.summary == "当前应用绑定：Mail -> 不存在（不存在）"


def test_style_binding_uses_last_seen_app_when_current_app_is_unknown(tmp_path: Path) -> None:
    prompts = _write_prompts(tmp_path)
    config = AppConfig()
    config.style.prompts_dir = str(prompts)
    service = StyleBindingService(config=config, styles=StyleRegistry(prompts_dir=prompts))
    service.sync_for_app(AppContext(bundle_id="com.example.editor", app_name="Editor"))
    service.select("情景/邮件")

    update = service.bind_current_style(AppContext())

    assert update.config is not None
    assert update.config.style.app_styles["com.example.editor"] == "情景/邮件"


def _write_prompts(tmp_path: Path) -> Path:
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    (prompts / "通用润色.md").write_text("polish", encoding="utf-8")
    scene = prompts / "情景"
    scene.mkdir()
    (scene / "邮件.md").write_text("mail", encoding="utf-8")
    return prompts
