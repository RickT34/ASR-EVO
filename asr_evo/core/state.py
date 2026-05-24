from __future__ import annotations

from enum import StrEnum


class DictationState(StrEnum):
    IDLE = "idle"
    RECORDING = "recording"
    TRANSCRIBING = "transcribing"
    POLISHING = "polishing"
    INSERTING = "inserting"
    ERROR = "error"
