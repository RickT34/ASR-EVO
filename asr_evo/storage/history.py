from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from asr_evo.core.context import DictationRecord
from asr_evo.core.ports import AppContext


@dataclass(frozen=True)
class AppStats:
    app_name: str
    bundle_id: str
    count: int
    total_chars: int
    total_audio_seconds: float


class HistoryStore:
    def __init__(self, database_path: str | Path) -> None:
        self.path = Path(database_path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def add(self, record: DictationRecord, *, audio_seconds: float = 0) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                insert into dictations (
                    id, started_at, ended_at, raw_text, final_text, style,
                    bundle_id, app_name, window_title, audio_seconds, final_chars,
                    user_edited_text, user_edited_chars
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.id,
                    record.started_at.isoformat(),
                    record.ended_at.isoformat(),
                    record.raw_text,
                    record.final_text,
                    record.style,
                    record.app_context.bundle_id or "",
                    record.app_context.app_name or "",
                    record.app_context.window_title or "",
                    audio_seconds,
                    len(record.final_text),
                    record.user_edited_text,
                    len(record.user_edited_text),
                ),
            )

    def recent(self, limit: int = 100) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                select
                    id, ended_at, app_name, bundle_id, style, final_text, raw_text, final_chars,
                    user_edited_text, user_edited_chars
                from dictations
                order by ended_at desc
                limit ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def recent_records(self, limit: int = 100) -> list[DictationRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                select
                    id, started_at, ended_at, raw_text, final_text, user_edited_text, style,
                    bundle_id, app_name, window_title
                from dictations
                order by ended_at desc
                limit ?
                """,
                (limit,),
            ).fetchall()
        records = [self._record_from_row(row) for row in rows]
        return list(reversed(records))

    def all_records(self) -> list[DictationRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                select
                    id, started_at, ended_at, raw_text, final_text, user_edited_text, style,
                    bundle_id, app_name, window_title
                from dictations
                order by ended_at asc
                """
            ).fetchall()
        return [self._record_from_row(row) for row in rows]

    def get(self, record_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                select
                    id, ended_at, app_name, bundle_id, style, final_text, raw_text, final_chars,
                    user_edited_text, user_edited_chars
                from dictations
                where id = ?
                """,
                (record_id,),
            ).fetchone()
        return dict(row) if row else None

    def stats_by_app(self, limit: int = 50) -> list[AppStats]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                select
                    coalesce(nullif(app_name, ''), bundle_id, '未知应用') as app_name,
                    bundle_id,
                    count(*) as count,
                    coalesce(sum(user_edited_chars), 0) as total_chars,
                    coalesce(sum(audio_seconds), 0) as total_audio_seconds
                from dictations
                group by bundle_id, app_name
                order by total_chars desc
                limit ?
                """,
                (limit,),
            ).fetchall()
        return [
            AppStats(
                app_name=row["app_name"],
                bundle_id=row["bundle_id"],
                count=row["count"],
                total_chars=row["total_chars"],
                total_audio_seconds=row["total_audio_seconds"],
            )
            for row in rows
        ]

    def totals(self) -> dict[str, int | float]:
        with self._connect() as conn:
            row = conn.execute(
                """
                select
                    count(*) as count,
                    coalesce(sum(user_edited_chars), 0) as total_chars,
                    coalesce(sum(audio_seconds), 0) as total_audio_seconds
                from dictations
                """
            ).fetchone()
        return dict(row)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _record_from_row(self, row: sqlite3.Row) -> DictationRecord:
        return DictationRecord(
            id=row["id"],
            started_at=datetime.fromisoformat(row["started_at"]),
            ended_at=datetime.fromisoformat(row["ended_at"]),
            raw_text=row["raw_text"],
            final_text=row["final_text"],
            user_edited_text=row["user_edited_text"],
            style=row["style"],
            app_context=AppContext(
                bundle_id=row["bundle_id"] or None,
                app_name=row["app_name"] or None,
                window_title=row["window_title"] or None,
            ),
        )

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                create table if not exists dictations (
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
                    user_edited_text text,
                    user_edited_chars integer not null default 0,
                    created_at text not null default current_timestamp
                )
                """
            )
            self._ensure_column(conn, "user_edited_text", "text")
            self._ensure_column(conn, "user_edited_chars", "integer not null default 0")
            conn.execute(
                """
                update dictations
                set user_edited_text = final_text,
                    user_edited_chars = final_chars
                where user_edited_text is null
                   or length(trim(user_edited_text)) = 0
                """
            )
            conn.execute("create index if not exists idx_dictations_ended_at on dictations(ended_at)")
            conn.execute("create index if not exists idx_dictations_app on dictations(bundle_id)")

    def _ensure_column(self, conn: sqlite3.Connection, name: str, definition: str) -> None:
        columns = {
            row["name"]
            for row in conn.execute("pragma table_info(dictations)").fetchall()
        }
        if name not in columns:
            conn.execute(f"alter table dictations add column {name} {definition}")
