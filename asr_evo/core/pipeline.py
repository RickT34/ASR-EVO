from __future__ import annotations

import contextlib
from dataclasses import dataclass
from datetime import UTC, datetime

from .context import ContextStore, DictationRecord
from .ports import ASRProvider, FrontmostAppProvider, LLMProvider, Recorder, TextInserter, TrayUI
from .state import DictationState


@dataclass(frozen=True)
class DictationResult:
    raw_text: str
    final_text: str
    record: DictationRecord
    audio_seconds: float


@dataclass(frozen=True)
class DictationDependencies:
    recorder: Recorder
    asr: ASRProvider
    llm: LLMProvider
    inserter: TextInserter
    app_provider: FrontmostAppProvider
    context_store: ContextStore
    tray: TrayUI


@dataclass(frozen=True)
class DictationOptions:
    style: str
    prompt_instruction: str
    context_enabled: bool = True
    cleanup_audio: bool = True


class DictationPipelineError(Exception):
    def __init__(
        self,
        message: str,
        *,
        raw_text: str = "",
        record: DictationRecord | None = None,
        audio_seconds: float = 0,
    ) -> None:
        super().__init__(message)
        self.raw_text = raw_text
        self.record = record
        self.audio_seconds = audio_seconds


class DictationPipeline:
    def __init__(
        self,
        *,
        dependencies: DictationDependencies,
        options: DictationOptions,
    ) -> None:
        self.dependencies = dependencies
        self.options = options

    async def run_once(self) -> DictationResult:
        started_at = datetime.now(UTC)
        app_context = self.dependencies.app_provider.current_app()
        audio = None
        transcript_text = ""

        try:
            self.dependencies.tray.set_state(DictationState.RECORDING.value)
            audio = await self.dependencies.recorder.record_until_stopped()

            self.dependencies.tray.set_state(DictationState.TRANSCRIBING.value)
            transcript = await self.dependencies.asr.transcribe(audio)
            transcript_text = transcript.text

            self.dependencies.tray.set_state(DictationState.POLISHING.value)
            context = (
                self.dependencies.context_store.render_for_prompt(app_context=app_context)
                if self.options.context_enabled
                else ""
            )
            final_text = await self.dependencies.llm.polish(
                transcript_text,
                context,
                self.options.prompt_instruction,
            )

            self.dependencies.tray.set_state(DictationState.INSERTING.value)
            await self.dependencies.inserter.insert(final_text)

            record = DictationRecord.create(
                started_at=started_at,
                raw_text=transcript_text,
                final_text=final_text,
                style=self.options.style,
                app_context=app_context,
            )
            if self.options.context_enabled:
                self.dependencies.context_store.add(record)
            self.dependencies.tray.set_state(DictationState.IDLE.value)
            return DictationResult(
                raw_text=transcript_text,
                final_text=final_text,
                record=record,
                audio_seconds=audio.duration_seconds,
            )
        except Exception as exc:
            if transcript_text:
                record = DictationRecord.create(
                    started_at=started_at,
                    raw_text=transcript_text,
                    final_text="",
                    style=self.options.style,
                    app_context=app_context,
                )
                raise DictationPipelineError(
                    str(exc),
                    raw_text=transcript_text,
                    record=record,
                    audio_seconds=audio.duration_seconds if audio is not None else 0,
                ) from exc
            raise
        finally:
            if self.options.cleanup_audio and audio is not None:
                with contextlib.suppress(FileNotFoundError):
                    audio.path.unlink()
