from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from asr_evo.config import AppConfig
from asr_evo.core.context import DictationRecord
from asr_evo.core.pipeline import DictationResult
from asr_evo.core.ports import (
    AppContext,
    TextReviewPreviewRequest,
    TextReviewRequest,
    TextReviewResult,
    TextReviewSaveRequest,
    TextReviewSaveResult,
)
from asr_evo.core.review import TextReviewService
from asr_evo.core.style_binding import StyleBindingService
from asr_evo.postprocess.styles import StyleRegistry


async def test_review_service_bypasses_reviewer_when_disabled(tmp_path: Path) -> None:
    service, reviewer, _, _, _ = _make_service(tmp_path)

    result = await service.review(_dictation_result(), enabled=False)

    assert reviewer.seen == []
    assert result == TextReviewResult(
        text="polished",
        polished_text="polished",
        style_id="通用润色",
        prompt_instruction="",
    )


async def test_review_service_builds_request_and_previews_with_selected_style(
    tmp_path: Path,
) -> None:
    service, reviewer, llm, bindings, _ = _make_service(tmp_path)
    reviewer.preview_request = TextReviewPreviewRequest(
        style_id="情景/邮件",
        prompt_instruction="custom email",
    )

    result = await service.review(_dictation_result(context="history"), enabled=True)

    assert reviewer.seen[0].raw_text == "raw"
    assert reviewer.seen[0].polished_text == "polished"
    assert reviewer.seen[0].prompt_instruction == "polish"
    assert [style.id for style in reviewer.seen[0].styles] == ["通用润色", "情景/邮件"]
    assert llm.calls == [("raw", "history", "custom email")]
    assert bindings.current_style_id == "情景/邮件"
    assert result is not None
    assert result.polished_text == "preview:custom email"


async def test_review_service_saves_prompt_and_app_binding(tmp_path: Path) -> None:
    service, reviewer, _, _, applied = _make_service(tmp_path)
    reviewer.save_request = TextReviewSaveRequest(
        style_id="情景/邮件",
        prompt_instruction="saved email",
    )

    result = await service.review(_dictation_result(), enabled=True)

    assert (tmp_path / "prompts" / "情景" / "邮件.md").read_text(encoding="utf-8") == (
        "saved email\n"
    )
    assert applied.config is not None
    assert applied.config.style.app_styles["com.example.App"] == "情景/邮件"
    assert applied.persist is True
    assert reviewer.save_result == TextReviewSaveResult(message="已保存提示词并绑定 Example")
    assert result is not None
    assert result.style_id == "情景/邮件"


def test_review_service_applies_review_result(tmp_path: Path) -> None:
    service, _, _, _, _ = _make_service(tmp_path)
    result = _dictation_result()

    reviewed = service.apply_result(
        result,
        TextReviewResult(
            text="accepted",
            polished_text="preview",
            style_id="情景/邮件",
            prompt_instruction="email",
        ),
    )

    assert reviewed.record.user_edited_text == "accepted"
    assert reviewed.record.final_text == "preview"
    assert reviewed.record.style == "情景/邮件"


@dataclass
class AppliedConfig:
    config: AppConfig | None = None
    persist: bool = False


class FakeReviewer:
    def __init__(self) -> None:
        self.seen: list[TextReviewRequest] = []
        self.preview_request: TextReviewPreviewRequest | None = None
        self.save_request: TextReviewSaveRequest | None = None
        self.save_result: TextReviewSaveResult | None = None

    async def review(self, request, previewer, saver) -> TextReviewResult:
        self.seen.append(request)
        style_id = request.style_id
        prompt_instruction = request.prompt_instruction
        polished_text = request.polished_text
        if self.preview_request is not None:
            polished_text = await previewer(self.preview_request)
            style_id = self.preview_request.style_id
            prompt_instruction = self.preview_request.prompt_instruction
        if self.save_request is not None:
            self.save_result = await saver(self.save_request)
            style_id = self.save_request.style_id
            prompt_instruction = self.save_request.prompt_instruction
        return TextReviewResult(
            text=polished_text,
            polished_text=polished_text,
            style_id=style_id,
            prompt_instruction=prompt_instruction,
        )


class FakeLLM:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    async def polish(self, raw_text: str, context: str, prompt_instruction: str) -> str:
        self.calls.append((raw_text, context, prompt_instruction))
        return f"preview:{prompt_instruction}"


def _make_service(
    tmp_path: Path,
) -> tuple[TextReviewService, FakeReviewer, FakeLLM, StyleBindingService, AppliedConfig]:
    prompts = _write_prompts(tmp_path)
    config = AppConfig()
    config.style.prompts_dir = str(prompts)
    styles = StyleRegistry(prompts_dir=prompts)
    bindings = StyleBindingService(config=config, styles=styles)
    reviewer = FakeReviewer()
    llm = FakeLLM()
    applied = AppliedConfig()

    def apply_config(config: AppConfig, *, persist: bool = False) -> None:
        applied.config = config
        applied.persist = persist

    service = TextReviewService(
        reviewer=reviewer,
        llm=llm,
        styles=styles,
        style_bindings=bindings,
        apply_config=apply_config,
        sync_style_menu=lambda: None,
    )
    return service, reviewer, llm, bindings, applied


def _dictation_result(context: str = "") -> DictationResult:
    app_context = AppContext(bundle_id="com.example.App", app_name="Example")
    return DictationResult(
        raw_text="raw",
        final_text="polished",
        record=DictationRecord.create(
            started_at=datetime.now(UTC),
            raw_text="raw",
            final_text="polished",
            style="通用润色",
            app_context=app_context,
        ),
        audio_seconds=1,
        app_context=app_context,
        context=context,
    )


def _write_prompts(tmp_path: Path) -> Path:
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    (prompts / "通用润色.md").write_text("polish", encoding="utf-8")
    scene = prompts / "情景"
    scene.mkdir()
    (scene / "邮件.md").write_text("email", encoding="utf-8")
    return prompts
