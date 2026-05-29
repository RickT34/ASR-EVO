from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from .ports import AppContext


@dataclass(frozen=True)
class DictationRecord:
    id: str
    started_at: datetime
    ended_at: datetime
    raw_text: str
    final_text: str
    style: str
    app_context: AppContext

    @classmethod
    def create(
        cls,
        *,
        started_at: datetime,
        raw_text: str,
        final_text: str,
        style: str,
        app_context: AppContext,
        ended_at: datetime | None = None,
    ) -> "DictationRecord":
        return cls(
            id=str(uuid4()),
            started_at=started_at,
            ended_at=ended_at or datetime.now(UTC),
            raw_text=raw_text,
            final_text=final_text,
            style=style,
            app_context=app_context,
        )


class ContextStore:
    def __init__(
        self,
        *,
        ttl_seconds: int = 600,
        max_items: int = 20,
        max_chars: int = 6000,
        scope: str = "app",
    ) -> None:
        self.ttl = timedelta(seconds=ttl_seconds)
        self.max_items = max_items
        self.max_chars = max_chars
        self.scope = scope

    def recent(
        self,
        *,
        app_context: AppContext,
        records: Iterable[DictationRecord],
        now: datetime | None = None,
    ) -> list[DictationRecord]:
        now = now or datetime.now(UTC)
        recent_records = [
            record
            for record in records
            if record.final_text.strip()
            and now - record.ended_at <= self.ttl
            and self._same_scope(record.app_context, app_context)
        ]
        recent_records.sort(key=lambda record: record.ended_at)
        return self._trim_to_char_budget(recent_records[-self.max_items :])

    def render_for_prompt(
        self,
        *,
        app_context: AppContext,
        records: Iterable[DictationRecord],
        now: datetime | None = None,
    ) -> str:
        prompt_records = self.recent(
            app_context=app_context,
            records=records,
            now=now,
        )
        if not prompt_records:
            return ""
        lines = ["最近同一上下文中已经插入的文本："]
        for index, record in enumerate(prompt_records, start=1):
            lines.append(f"{index}. {record.final_text}")
        return "\n".join(lines)

    def _same_scope(self, left: AppContext, right: AppContext) -> bool:
        if self.scope == "time":
            return True
        if self.scope == "window":
            return bool(
                left.bundle_id == right.bundle_id
                and left.window_title
                and left.window_title == right.window_title
            )
        return left.bundle_id == right.bundle_id

    def _trim_to_char_budget(self, records: list[DictationRecord]) -> list[DictationRecord]:
        selected: list[DictationRecord] = []
        total = 0
        for record in reversed(records):
            text_len = len(record.final_text)
            if selected and total + text_len > self.max_chars:
                break
            if text_len > self.max_chars:
                continue
            selected.append(record)
            total += text_len
        return list(reversed(selected))
