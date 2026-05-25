from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from asr_evo.core.context import ContextStore, DictationRecord
from asr_evo.core.pipeline import (
    DictationDependencies,
    DictationOptions,
    DictationPipeline,
    DictationPipelineError,
)
from asr_evo.core.ports import AppContext, AudioClip, Transcript


class FakeRecorder:
    def __init__(self, path: Path) -> None:
        self.path = path

    async def record_until_stopped(self) -> AudioClip:
        return AudioClip(path=self.path, sample_rate=16000, duration_seconds=1)


class FakeASR:
    async def transcribe(self, audio: AudioClip) -> Transcript:
        return Transcript(text="raw")


class FakeLLM:
    def __init__(self) -> None:
        self.context = None

    async def polish(self, raw_text: str, context: str, prompt_instruction: str) -> str:
        self.context = context
        return f"final:{raw_text}"


class FailingLLM:
    async def polish(self, raw_text: str, context: str, prompt_instruction: str) -> str:
        raise RuntimeError("remote failed")


class FakeInserter:
    def __init__(self) -> None:
        self.text = None

    async def insert(self, text: str) -> None:
        self.text = text


class FakeAppProvider:
    def current_app(self) -> AppContext:
        return AppContext(bundle_id="com.example.App")


class FakeTray:
    def __init__(self) -> None:
        self.states: list[str] = []

    def set_state(self, state: str, detail: str = "") -> None:
        self.states.append(state)


async def test_pipeline_disables_context_and_deletes_audio(tmp_path: Path) -> None:
    audio = tmp_path / "recording.wav"
    audio.write_bytes(b"audio")
    store = ContextStore(scope="app")
    store.add(
        DictationRecord.create(
            started_at=datetime.now(UTC),
            raw_text="old raw",
            final_text="old final",
            style="polished",
            app_context=AppContext(bundle_id="com.example.App"),
        )
    )
    llm = FakeLLM()

    result = await DictationPipeline(
        dependencies=DictationDependencies(
            recorder=FakeRecorder(audio),
            asr=FakeASR(),
            llm=llm,
            inserter=FakeInserter(),
            app_provider=FakeAppProvider(),
            context_store=store,
            tray=FakeTray(),
        ),
        options=DictationOptions(
            style="polished",
            prompt_instruction="整理为自然清楚的中文。",
            context_enabled=False,
        ),
    ).run_once()

    assert result.final_text == "final:raw"
    assert llm.context == ""
    assert not audio.exists()
    assert len(store.recent(app_context=AppContext(bundle_id="com.example.App"))) == 1


async def test_pipeline_error_preserves_raw_transcript(tmp_path: Path) -> None:
    audio = tmp_path / "recording.wav"
    audio.write_bytes(b"audio")

    try:
        await DictationPipeline(
            dependencies=DictationDependencies(
                recorder=FakeRecorder(audio),
                asr=FakeASR(),
                llm=FailingLLM(),
                inserter=FakeInserter(),
                app_provider=FakeAppProvider(),
                context_store=ContextStore(scope="app"),
                tray=FakeTray(),
            ),
            options=DictationOptions(
                style="polished",
                prompt_instruction="整理为自然清楚的中文。",
            ),
        ).run_once()
    except DictationPipelineError as exc:
        assert exc.raw_text == "raw"
        assert exc.record is not None
        assert exc.record.raw_text == "raw"
        assert exc.record.final_text == ""
    else:
        raise AssertionError("expected pipeline error")

    assert not audio.exists()
