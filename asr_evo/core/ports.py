from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class AppContext:
    bundle_id: str | None = None
    app_name: str | None = None
    window_title: str | None = None


@dataclass(frozen=True)
class AudioClip:
    path: Path
    sample_rate: int
    duration_seconds: float


@dataclass(frozen=True)
class Transcript:
    text: str
    language: str | None = None


@dataclass(frozen=True)
class PolishedText:
    text: str
    style: str


class Recorder(Protocol):
    async def record_until_stopped(self) -> AudioClip: ...


class ASRProvider(Protocol):
    async def transcribe(self, audio: AudioClip) -> Transcript: ...


class LLMProvider(Protocol):
    async def polish(self, raw_text: str, context: str, style: str, custom_prompt: str = "") -> str: ...


class TextInserter(Protocol):
    def can_insert(self) -> bool: ...

    async def insert(self, text: str) -> None: ...


class FrontmostAppProvider(Protocol):
    def current_app(self) -> AppContext: ...


class TrayUI(Protocol):
    def set_state(self, state: str, detail: str = "") -> None: ...
