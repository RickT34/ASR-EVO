from __future__ import annotations

from typing import Protocol


class TextInserter(Protocol):
    def can_insert(self) -> bool: ...

    async def insert(self, text: str) -> None: ...
