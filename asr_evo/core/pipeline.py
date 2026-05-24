from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from .context import ContextStore, DictationRecord
from .ports import ASRProvider, FrontmostAppProvider, LLMProvider, Recorder, TextInserter, TrayUI
from .state import DictationState


@dataclass(frozen=True)
class DictationResult:
    raw_text: str
    final_text: str


class DictationPipeline:
    def __init__(
        self,
        *,
        recorder: Recorder,
        asr: ASRProvider,
        llm: LLMProvider,
        inserter: TextInserter,
        app_provider: FrontmostAppProvider,
        context_store: ContextStore,
        tray: TrayUI,
        style: str,
        custom_prompt: str = "",
    ) -> None:
        self.recorder = recorder
        self.asr = asr
        self.llm = llm
        self.inserter = inserter
        self.app_provider = app_provider
        self.context_store = context_store
        self.tray = tray
        self.style = style
        self.custom_prompt = custom_prompt

    async def run_once(self) -> DictationResult:
        started_at = datetime.now(UTC)
        app_context = self.app_provider.current_app()

        self.tray.set_state(DictationState.RECORDING.value)
        audio = await self.recorder.record_until_stopped()

        self.tray.set_state(DictationState.TRANSCRIBING.value)
        transcript = await self.asr.transcribe(audio)

        self.tray.set_state(DictationState.POLISHING.value)
        context = self.context_store.render_for_prompt(app_context=app_context)
        final_text = await self.llm.polish(
            transcript.text,
            context,
            self.style,
            custom_prompt=self.custom_prompt,
        )

        self.tray.set_state(DictationState.INSERTING.value)
        await self.inserter.insert(final_text)

        record = DictationRecord.create(
            started_at=started_at,
            raw_text=transcript.text,
            final_text=final_text,
            style=self.style,
            app_context=app_context,
        )
        self.context_store.add(record)
        self.tray.set_state(DictationState.IDLE.value)
        return DictationResult(raw_text=transcript.text, final_text=final_text)
