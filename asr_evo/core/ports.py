from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from asr_evo.core.errors import ErrorFeedback

if TYPE_CHECKING:
    from asr_evo.core.context import DictationRecord
    from asr_evo.postprocess.styles import StyleDefinition


@dataclass(frozen=True)
class AppContext:
    bundle_id: str | None = None
    app_name: str | None = None
    window_title: str | None = None
    process_id: int | None = None


@dataclass(frozen=True)
class AudioClip:
    path: Path
    sample_rate: int
    duration_seconds: float


@dataclass(frozen=True)
class Transcript:
    text: str
    language: str | None = None


class InputDeviceSummary(Protocol):
    id: str
    label: str
    is_default: bool


class AppStatsSummary(Protocol):
    app_name: str
    count: int
    total_chars: int


class Recorder(Protocol):
    async def record_until_stopped(self) -> AudioClip: ...


class DesktopRecorder(Recorder, Protocol):
    input_device: str

    def stop(self) -> None: ...

    def set_input_device(self, device_id: str | int | None) -> None: ...

    def input_devices(self) -> list[InputDeviceSummary]: ...

    def current_input_label(self) -> str: ...


class ASRProvider(Protocol):
    async def transcribe(self, audio: AudioClip) -> Transcript: ...


class LLMProvider(Protocol):
    async def polish(self, raw_text: str, context: str, prompt_instruction: str) -> str: ...


class TextInserter(Protocol):
    async def insert(self, text: str) -> None: ...


class TextReviewer(Protocol):
    async def review(self, text: str) -> str | None: ...


class FrontmostAppProvider(Protocol):
    def current_app(self) -> AppContext: ...


class TrayUI(Protocol):
    def set_state(self, state: str, detail: str = "") -> None: ...

    def set_error_feedback(self, feedback: ErrorFeedback | None) -> None: ...


class StatusTray(TrayUI, Protocol):
    def set_styles(self, styles: list["StyleDefinition"], selected_style_id: str) -> None: ...

    def set_app_binding_summary(self, title: str) -> None: ...

    def set_status_config(self, status_config: object) -> None: ...

    def set_review_enabled(self, enabled: bool) -> None: ...

    def set_input_devices(
        self,
        devices: list[InputDeviceSummary],
        selected_device_id: str,
    ) -> None: ...

    def set_stats(
        self,
        *,
        totals: dict[str, int | float],
        app_stats: list[AppStatsSummary],
    ) -> None: ...

    def set_history_records(self, records: list[dict]) -> None: ...

class Clipboard(Protocol):
    def copy_text(self, text: str) -> None: ...


class FileOpener(Protocol):
    def open_path(self, path: Path) -> None: ...


class PermissionChecker(Protocol):
    def accessibility_trusted(self, *, prompt: bool = False) -> bool: ...


class AppLifecycle(Protocol):
    def quit(self) -> None: ...


class HistoryRepository(Protocol):
    def add(self, record, *, audio_seconds: float = 0) -> None: ...

    def recent(self, limit: int = 100) -> list[dict]: ...

    def recent_records(self, limit: int = 100) -> list["DictationRecord"]: ...

    def get(self, record_id: str) -> dict | None: ...

    def stats_by_app(self, limit: int = 50) -> list[AppStatsSummary]: ...

    def totals(self) -> dict[str, int | float]: ...
