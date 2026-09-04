from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import sqlite3

import pytest

from asr_evo.core.context import DictationRecord
from asr_evo.core.ports import AppContext, AudioClip
from asr_evo.storage.history import HistoryStore


def test_history_store_records_and_summarizes(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "history.sqlite3")
    source_audio = tmp_path / "source.wav"
    source_audio.write_bytes(b"wave data")
    record = DictationRecord.create(
        started_at=datetime.now(UTC),
        raw_text="原始文本",
        final_text="最终文本",
        style="polished",
        app_context=AppContext(bundle_id="com.example", app_name="示例应用"),
    )

    store.add(
        record,
        audio=AudioClip(path=source_audio, sample_rate=24000, duration_seconds=2.5),
    )

    totals = store.totals()
    stats = store.stats_by_app()
    recent = store.recent()
    recent_records = store.recent_records()
    assert totals["count"] == 1
    assert totals["total_chars"] == 4
    assert stats[0].app_name == "示例应用"
    assert stats[0].total_audio_seconds == 2.5
    assert recent[0]["final_text"] == "最终文本"
    assert recent[0]["user_edited_text"] == "最终文本"
    assert recent[0]["user_edited_chars"] == 4
    assert recent[0]["audio_sample_rate"] == 24000
    assert recent[0]["has_audio"] is True
    assert Path(recent[0]["audio_path"]).read_bytes() == b"wave data"
    assert not source_audio.exists()
    assert recent_records[0].id == record.id
    assert recent_records[0].final_text == "最终文本"
    assert recent_records[0].user_edited_text == "最终文本"
    assert recent_records[0].app_context.app_name == "示例应用"
    assert store.all_records()[0].id == record.id

    updated = DictationRecord(
        **{
            **record.__dict__,
            "raw_text": "重新转写",
            "final_text": "重新润色",
            "user_edited_text": "最终采用",
        }
    )
    store.update(updated)
    assert store.get_record(record.id) == updated
    assert store.get(record.id)["user_edited_text"] == "最终采用"


def test_history_store_backfills_user_edit_for_existing_rows(tmp_path: Path) -> None:
    path = tmp_path / "history.sqlite3"
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            create table dictations (
                id text primary key,
                started_at text not null,
                ended_at text not null,
                raw_text text not null,
                final_text text not null,
                style text not null,
                bundle_id text,
                app_name text,
                window_title text,
                audio_seconds real not null default 0,
                final_chars integer not null default 0,
                created_at text not null default current_timestamp
            )
            """
        )
        now = datetime.now(UTC).isoformat()
        conn.execute(
            """
            insert into dictations (
                id, started_at, ended_at, raw_text, final_text, style,
                bundle_id, app_name, window_title, audio_seconds, final_chars
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "old",
                now,
                now,
                "旧原文",
                "旧润色",
                "polished",
                "com.example",
                "Example",
                "",
                1,
                3,
            ),
        )

    store = HistoryStore(path)

    recent = store.recent()
    recent_records = store.recent_records()
    assert recent[0]["user_edited_text"] == "旧润色"
    assert recent[0]["user_edited_chars"] == 3
    assert recent[0]["audio_path"] == ""
    assert recent[0]["has_audio"] is False
    assert recent[0]["audio_sample_rate"] == 0
    assert recent_records[0].user_edited_text == "旧润色"


def test_history_store_preserves_empty_user_edit_for_cancelled_record(tmp_path: Path) -> None:
    path = tmp_path / "history.sqlite3"
    store = HistoryStore(path)
    record = DictationRecord.create(
        started_at=datetime.now(UTC),
        raw_text="原始文本",
        final_text="未采用文本",
        user_edited_text="",
        style="polished",
        app_context=AppContext(),
    )
    store.add(record)

    reopened = HistoryStore(path)

    assert reopened.get_record(record.id).user_edited_text == ""


def test_history_store_does_not_overwrite_existing_audio_on_duplicate_add(
    tmp_path: Path,
) -> None:
    store = HistoryStore(tmp_path / "history.sqlite3")
    record = DictationRecord.create(
        started_at=datetime.now(UTC),
        raw_text="原始文本",
        final_text="最终文本",
        style="polished",
        app_context=AppContext(),
    )
    first = tmp_path / "first.wav"
    first.write_bytes(b"first")
    store.add(record, audio=AudioClip(path=first, sample_rate=16000, duration_seconds=1))
    second = tmp_path / "second.wav"
    second.write_bytes(b"second")

    with pytest.raises(FileExistsError, match="audio archive already exists"):
        store.add(record, audio=AudioClip(path=second, sample_rate=16000, duration_seconds=1))

    assert Path(store.get(record.id)["audio_path"]).read_bytes() == b"first"
    assert second.read_bytes() == b"second"
