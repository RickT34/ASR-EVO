from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from asr_evo.config import ContextConfig
from asr_evo.core.context import ContextStore, DictationRecord
from asr_evo.core.ports import AppContext
from asr_evo.postprocess.prompts import render_polish_input
from asr_evo.postprocess.styles import StyleRegistry
from asr_evo.storage.history import HistoryStore
from preference_prompt_optimizer.asr_evo_history import (
    load_history_samples,
    samples_from_records,
    write_samples_jsonl,
)
from preference_prompt_optimizer.io import load_jsonl


def test_samples_from_records_reconstructs_prior_context_only() -> None:
    now = datetime(2026, 5, 29, 12, tzinfo=UTC)
    records = [
        make_record("1", "raw first", "ai first", "user first", now),
        make_record("2", "raw second", "ai second", "user second", now + timedelta(seconds=5)),
        make_record("3", "raw other", "ai other", "user other", now + timedelta(seconds=6), "other"),
    ]

    samples = samples_from_records(
        records,
        context_store=ContextStore(ttl_seconds=600, scope="app"),
        style_registry=None,
    )

    assert samples[1].input == render_polish_input(
        raw_text="raw second",
        context="最近同一上下文中已经插入的文本：\n1. user first",
    )
    assert samples[1].model_output == "ai second"
    assert samples[1].user_edit == "user second"
    assert samples[1].prompt_instruction == ""


def test_load_history_samples_and_write_jsonl(tmp_path: Path) -> None:
    db = tmp_path / "history.sqlite3"
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    (prompts / "chat.md").write_text("整理成简洁聊天消息。", encoding="utf-8")
    store = HistoryStore(db)
    now = datetime(2026, 5, 29, 12, tzinfo=UTC)
    store.add(make_record("1", "raw first", "ai first", "user first", now))
    store.add(make_record("2", "raw second", "ai second", "user second", now + timedelta(seconds=5)))

    samples = load_history_samples(db, prompts_dir=prompts)
    output = tmp_path / "samples.jsonl"
    write_samples_jsonl(samples, output)
    loaded = load_jsonl(output)

    assert len(loaded) == 2
    text = output.read_text(encoding="utf-8")
    assert '"source"' not in text
    assert '"context"' not in text
    assert loaded[1].prompt_instruction == "整理成简洁聊天消息。"
    assert "处理要求" not in loaded[1].input
    assert "最近同一上下文中已经插入的文本：\\n1. user first" in text
    assert "当前语音识别文本：\\nraw second" in text
    assert loaded[1].metadata["style"] == "chat"
    assert loaded[1].metadata["prompt_found"] == "true"


def test_load_history_samples_respects_disabled_context(tmp_path: Path) -> None:
    db = tmp_path / "history.sqlite3"
    store = HistoryStore(db)
    now = datetime(2026, 5, 29, 12, tzinfo=UTC)
    store.add(make_record("1", "raw first", "ai first", "user first", now))
    store.add(make_record("2", "raw second", "ai second", "user second", now + timedelta(seconds=5)))

    samples = load_history_samples(db, context_config=ContextConfig(enabled=False))

    assert samples[1].input == render_polish_input(raw_text="raw second", context="")


def test_samples_from_records_uses_style_prompt_when_available(tmp_path: Path) -> None:
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    (prompts / "chat.md").write_text("整理成简洁聊天消息。", encoding="utf-8")
    now = datetime(2026, 5, 29, 12, tzinfo=UTC)

    samples = samples_from_records(
        [make_record("1", "raw first", "ai first", "user first", now)],
        context_store=ContextStore(ttl_seconds=600, scope="app"),
        style_registry=StyleRegistry(prompts_dir=prompts),
    )

    assert samples[0].prompt_instruction == "整理成简洁聊天消息。"
    assert samples[0].input == "当前语音识别文本：\nraw first"


def make_record(
    record_id: str,
    raw_text: str,
    final_text: str,
    user_edited_text: str,
    ended_at: datetime,
    bundle_id: str = "com.example.chat",
) -> DictationRecord:
    return DictationRecord(
        id=record_id,
        started_at=ended_at - timedelta(seconds=2),
        ended_at=ended_at,
        raw_text=raw_text,
        final_text=final_text,
        user_edited_text=user_edited_text,
        style="chat",
        app_context=AppContext(bundle_id=bundle_id, app_name="Chat"),
    )
