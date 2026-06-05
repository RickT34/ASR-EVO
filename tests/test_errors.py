from __future__ import annotations

from asr_evo.core.errors import ErrorFeedback, feedback_from_exception
from asr_evo.ui.menu import error_feedback_lines


def test_feedback_from_missing_api_key_suggests_env_fix() -> None:
    feedback = feedback_from_exception(
        RuntimeError("Missing API key in $DASHSCOPE_API_KEY. Add it to .env.")
    )

    assert feedback.title == "缺少 API Key"
    assert "DASHSCOPE_API_KEY" in feedback.detail
    assert ".env" in feedback.suggestion
    assert "技术细节" in feedback.copy_text()


def test_feedback_from_pipeline_error_mentions_saved_raw_text() -> None:
    feedback = feedback_from_exception(RuntimeError("remote failed"), raw_text_saved=True)

    assert feedback.raw_text_saved is True
    assert "历史记录" in feedback.suggestion
    assert "原始转写已保存" in feedback.copy_text()


def test_feedback_from_openai_status_error_maps_service_config() -> None:
    feedback = feedback_from_exception(RuntimeError("Error code: 404 - model not found"))

    assert feedback.title == "服务配置有误"
    assert "model" in feedback.suggestion


def test_error_feedback_lines_include_saved_raw_text_marker() -> None:
    feedback = ErrorFeedback(
        title="听写失败",
        detail="remote failed",
        suggestion="请稍后重试",
        technical_detail="remote failed",
        raw_text_saved=True,
    )

    assert error_feedback_lines(feedback) == [
        "原因：remote failed",
        "建议：请稍后重试",
        "原始转写已保存到历史记录",
    ]
