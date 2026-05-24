from __future__ import annotations

from datetime import UTC, datetime, timedelta

from asr_evo.core.context import ContextStore, DictationRecord
from asr_evo.core.ports import AppContext


def make_record(text: str, ended_at: datetime, bundle_id: str = "com.apple.TextEdit"):
    return DictationRecord.create(
        started_at=ended_at - timedelta(seconds=2),
        ended_at=ended_at,
        raw_text=text,
        final_text=text,
        style="polished",
        app_context=AppContext(bundle_id=bundle_id, app_name="TextEdit"),
    )


def test_context_filters_by_time_and_app() -> None:
    now = datetime(2026, 5, 24, 12, tzinfo=UTC)
    store = ContextStore(ttl_seconds=600, scope="app")
    store.add(make_record("old text", now - timedelta(minutes=11)))
    store.add(make_record("same app", now - timedelta(minutes=1)))
    store.add(make_record("other app", now - timedelta(minutes=1), "com.apple.Notes"))

    recent = store.recent(app_context=AppContext(bundle_id="com.apple.TextEdit"), now=now)

    assert [record.final_text for record in recent] == ["same app"]


def test_context_scope_time_keeps_different_apps() -> None:
    now = datetime(2026, 5, 24, 12, tzinfo=UTC)
    store = ContextStore(ttl_seconds=600, scope="time")
    store.add(make_record("same app", now - timedelta(minutes=1)))
    store.add(make_record("other app", now - timedelta(minutes=1), "com.apple.Notes"))

    recent = store.recent(app_context=AppContext(bundle_id="com.apple.TextEdit"), now=now)

    assert [record.final_text for record in recent] == ["same app", "other app"]


def test_context_respects_char_budget_from_most_recent() -> None:
    now = datetime(2026, 5, 24, 12, tzinfo=UTC)
    store = ContextStore(ttl_seconds=600, max_chars=8, scope="app")
    store.add(make_record("1111", now - timedelta(minutes=3)))
    store.add(make_record("2222", now - timedelta(minutes=2)))
    store.add(make_record("3333", now - timedelta(minutes=1)))

    recent = store.recent(app_context=AppContext(bundle_id="com.apple.TextEdit"), now=now)

    assert [record.final_text for record in recent] == ["2222", "3333"]
