from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from asr_evo.core.context import DictationRecord
from asr_evo.core.ports import AppContext
from asr_evo.storage.history import HistoryStore


def test_history_store_records_and_summarizes(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "history.sqlite3")
    record = DictationRecord.create(
        started_at=datetime.now(UTC),
        raw_text="原始文本",
        final_text="最终文本",
        style="polished",
        app_context=AppContext(bundle_id="com.example", app_name="示例应用"),
    )

    store.add(record, audio_seconds=2.5)

    totals = store.totals()
    stats = store.stats_by_app()
    recent = store.recent()
    assert totals["count"] == 1
    assert totals["total_chars"] == 4
    assert stats[0].app_name == "示例应用"
    assert stats[0].total_audio_seconds == 2.5
    assert recent[0]["final_text"] == "最终文本"
