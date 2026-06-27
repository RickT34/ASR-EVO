from __future__ import annotations

from collections.abc import Callable

from asr_evo.core.pipeline import DictationResult
from asr_evo.core.ports import (
    AppContext,
    LLMProvider,
    TextReviewPreviewRequest,
    TextReviewRequest,
    TextReviewResult,
    TextReviewSaveRequest,
    TextReviewSaveResult,
    TextReviewStyle,
    TextReviewer,
)
from asr_evo.core.style_binding import StyleBindingService
from asr_evo.postprocess.styles import StyleRegistry


class TextReviewService:
    def __init__(
        self,
        *,
        reviewer: TextReviewer,
        llm: LLMProvider,
        styles: StyleRegistry,
        style_bindings: StyleBindingService,
        apply_config: Callable[..., None],
        sync_style_menu: Callable[[], None],
    ) -> None:
        self.reviewer = reviewer
        self.llm = llm
        self.styles = styles
        self.style_bindings = style_bindings
        self.apply_config = apply_config
        self.sync_style_menu = sync_style_menu

    async def review(
        self,
        result: DictationResult,
        *,
        enabled: bool,
    ) -> TextReviewResult | None:
        if not enabled:
            return TextReviewResult(
                text=result.final_text,
                polished_text=result.final_text,
                style_id=result.record.style,
                prompt_instruction="",
            )

        return await self.reviewer.review(
            self._request_for(result),
            self._previewer(result),
            self._saver(result.app_context or AppContext()),
        )

    def apply_result(self, result: DictationResult, review: TextReviewResult) -> DictationResult:
        return result.with_reviewed_text(
            user_text=review.text,
            final_text=review.polished_text,
            style=review.style_id,
        )

    def _request_for(self, result: DictationResult) -> TextReviewRequest:
        return TextReviewRequest(
            raw_text=result.raw_text,
            polished_text=result.final_text,
            style_id=result.record.style,
            prompt_instruction=self.styles.get(result.record.style).prompt,
            styles=[
                TextReviewStyle(id=style.id, label=style.label, prompt=style.prompt)
                for style in self.styles.all()
            ],
            context=result.context,
        )

    def _previewer(self, result: DictationResult):
        async def preview(request: TextReviewPreviewRequest) -> str:
            self._select_existing_style(request.style_id)
            return await self.llm.polish(
                result.raw_text,
                result.context,
                request.prompt_instruction,
            )

        return preview

    def _saver(self, app_context: AppContext):
        async def save(request: TextReviewSaveRequest) -> TextReviewSaveResult:
            self._select_existing_style(request.style_id)
            self.styles.update_prompt(request.style_id, request.prompt_instruction)
            self.style_bindings.select(request.style_id)
            update = self.style_bindings.bind_current_style(app_context)
            if update.config is None:
                self.sync_style_menu()
                return TextReviewSaveResult(message="已保存提示词")

            self.apply_config(update.config, persist=True)
            app_name = update.app.app_name or update.app.bundle_id
            return TextReviewSaveResult(message=f"已保存提示词并绑定 {app_name}")

        return save

    def _select_existing_style(self, style_id: str) -> None:
        if not self.style_bindings.select(style_id):
            raise RuntimeError(f"style not found: {style_id}")
