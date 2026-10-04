from __future__ import annotations

import asyncio

import pytest

from asr_evo.core.ports import AudioClip, TextReviewResult, Transcript
from test_controller import _make_controller


class StreamingRecorder:
    def __init__(self, path, *, tail=True):
        self.path = path
        self.tail = tail
        self.stopped = asyncio.Event()
        self.finished = False

    def stop(self):
        self.stopped.set()

    async def record_until_stopped(self, on_chunk):
        self.path.write_bytes(b"complete recording")
        on_chunk(b"first")
        await self.stopped.wait()
        if self.tail:
            on_chunk(b"tail")
        self.finished = True
        return AudioClip(self.path, 16000, 1.0)


class StreamingASR:
    def __init__(self, *, fail=False):
        self.fail = fail
        self.chunks = []
        self.closed = False

    async def stream(self, chunks):
        text = ""
        try:
            async for chunk in chunks:
                self.chunks.append(chunk)
                text += "第一句。" if chunk == b"first" else "最后一句。"
                yield Transcript(text)
                if self.fail:
                    raise RuntimeError("stream disconnected")
            # Flushing an unchanged final hypothesis must not trigger duplicate polish.
            yield Transcript(text)
        finally:
            self.closed = True


class LiveReviewer:
    def __init__(self, recorder, *, cancel=False, fail=False, preview=False):
        self.recorder = recorder
        self.cancel = cancel
        self.fail = fail
        self.preview = preview
        self.updates = []
        self.calls = 0
        self.closed = False

    async def review(self, request, previewer, saver, *, live):
        self.calls += 1
        assert request.raw_text == ""
        assert not self.recorder.finished
        try:
            if self.fail:
                raise RuntimeError("dialog failed")
            while True:
                update = await live.updates.get()
                self.updates.append(update)
                if self.cancel and update.raw_text:
                    return None
                if update.polished_text.startswith("final:") and not self.recorder.finished:
                    live.stop()
                if update.finished:
                    polished = update.polished_text
                    if self.preview:
                        from asr_evo.core.ports import TextReviewPreviewRequest
                        polished = await previewer(TextReviewPreviewRequest(request.style_id, "edited prompt"))
                    return TextReviewResult("用户修订", polished, request.style_id, request.prompt_instruction)
        finally:
            self.closed = True


def setup_live(tmp_path, *, tail=True, cancel=False, asr_fail=False, ui_fail=False, preview=False):
    controller, deps = _make_controller(tmp_path)
    recorder = StreamingRecorder(tmp_path / "stream.wav", tail=tail)
    provider = StreamingASR(fail=asr_fail)
    reviewer = LiveReviewer(recorder, cancel=cancel, fail=ui_fail, preview=preview)
    controller.config.review.realtime_enabled = True
    controller.config.review.polish_interval_seconds = 0.01
    controller.dependencies.recorder = recorder
    controller.dependencies.text_reviewer = reviewer
    controller.dependencies.streaming_asr_factory = lambda: provider
    return controller, deps, recorder, provider, reviewer


@pytest.mark.parametrize("tail", [False, True])
async def test_live_window_updates_during_recording_and_flushes_without_duplicate_polish(tmp_path, tail):
    controller, deps, recorder, provider, reviewer = setup_live(tmp_path, tail=tail)
    await asyncio.wait_for(controller.run_pipeline_once(), 2)
    assert provider.chunks == ([b"first", b"tail"] if tail else [b"first"])
    assert provider.closed and reviewer.closed and recorder.finished
    assert reviewer.calls == 1
    raw = "第一句。最后一句。" if tail else "第一句。"
    assert reviewer.updates[-1].raw_text == raw
    assert deps.llm_provider.calls == [("第一句。", "", "polish")] + ([(raw, "", "polish")] if tail else [])
    record = deps.history_store.recent()[0]
    assert record["raw_text"] == raw
    assert record["user_edited_text"] == "用户修订"
    assert record["has_audio"]
    assert deps.inserter.text == "用户修订"


async def test_cancel_live_window_stops_recording_and_preserves_history(tmp_path):
    controller, deps, recorder, provider, reviewer = setup_live(tmp_path, cancel=True)
    await asyncio.wait_for(controller.run_pipeline_once(), 2)
    assert recorder.finished and provider.closed
    assert deps.inserter.text is None
    record = deps.history_store.recent()[0]
    assert record["raw_text"].startswith("第一句。")
    assert record["has_audio"]
    assert record["user_edited_text"] == ""
    assert not deps.llm_provider.calls


@pytest.mark.parametrize("asr_fail,ui_fail", [(True, False), (False, True)])
async def test_live_failure_stops_microphone_and_cleans_up_tasks(tmp_path, asr_fail, ui_fail):
    controller, deps, recorder, provider, reviewer = setup_live(tmp_path, asr_fail=asr_fail, ui_fail=ui_fail)
    await asyncio.wait_for(controller.run_pipeline_once(), 2)
    assert recorder.finished and provider.closed and reviewer.closed
    assert controller.state.state.value == "error"
    assert deps.inserter.text is None
    assert deps.history_store.recent()[0]["has_audio"]


async def test_live_manual_preview_uses_final_transcript_not_empty_initial_text(tmp_path):
    controller, deps, *_ = setup_live(tmp_path, preview=True)
    await asyncio.wait_for(controller.run_pipeline_once(), 2)
    assert deps.llm_provider.calls[-1] == ("第一句。最后一句。", "", "edited prompt")


async def test_live_transcription_continues_during_slow_polish(tmp_path):
    controller, deps, recorder, provider, reviewer = setup_live(tmp_path)
    llm_started = asyncio.Event()
    release = asyncio.Event()
    original_polish = deps.llm_provider.polish

    async def slow_polish(*args, **kwargs):
        llm_started.set()
        await release.wait()
        return await original_polish(*args, **kwargs)

    deps.llm_provider.polish = slow_polish
    task = asyncio.create_task(controller.run_pipeline_once())
    await asyncio.wait_for(llm_started.wait(), 1)
    recorder.stop()
    for _ in range(100):
        if any("最后一句" in update.raw_text for update in reviewer.updates):
            break
        await asyncio.sleep(0.001)
    assert any("最后一句" in update.raw_text for update in reviewer.updates)
    release.set()
    await asyncio.wait_for(task, 2)
    assert len(deps.llm_provider.calls) == 2


def test_realtime_menu_switch_persists_and_cannot_change_mid_recording(tmp_path):
    from asr_evo.config import AppConfig
    from asr_evo.core.state import DictationState

    controller, deps = _make_controller(tmp_path)
    controller.dependencies.streaming_asr_factory = lambda: StreamingASR()
    actions = controller.tray_actions()
    actions.toggle_realtime()
    assert deps.tray.realtime_enabled
    assert AppConfig.load(tmp_path / "config.toml").review.realtime_enabled
    controller.state.state = DictationState.RECORDING
    actions.toggle_realtime()
    assert controller.config.review.realtime_enabled
    controller.state.state = DictationState.IDLE
    actions.toggle_realtime()
    assert not AppConfig.load(tmp_path / "config.toml").review.realtime_enabled


async def test_cancel_while_polishing_cancels_model_request(tmp_path):
    controller, deps, recorder, provider, reviewer = setup_live(tmp_path)
    started = asyncio.Event()
    closed = asyncio.Event()

    async def polish(*args, **kwargs):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            closed.set()

    async def review(*args, live, **kwargs):
        await started.wait()
        return None

    deps.llm_provider.polish = polish
    reviewer.review = review
    await asyncio.wait_for(controller.run_pipeline_once(), 2)
    assert recorder.finished and provider.closed and closed.is_set()
    assert deps.inserter.text is None
    assert deps.history_store.recent()[0]["has_audio"]


@pytest.mark.parametrize("manual", [False, True])
async def test_realtime_auto_polish_off_preserves_raw_and_allows_manual_polish(tmp_path, manual):
    controller, deps, recorder, provider, reviewer = setup_live(tmp_path)
    controller.config.llm.auto_polish = False
    updates = []

    async def review(request, previewer, saver, *, live):
        assert request.auto_polish is False
        while True:
            update = await live.updates.get()
            updates.append(update)
            assert update.raw_text == update.polished_text
            if update.raw_text and not recorder.finished:
                live.stop()
            if update.finished:
                final = update.polished_text
                if manual:
                    from asr_evo.core.ports import TextReviewPreviewRequest
                    final = await previewer(TextReviewPreviewRequest(request.style_id, "manual"))
                return TextReviewResult(final, final, request.style_id, request.prompt_instruction)

    reviewer.review = review
    await asyncio.wait_for(controller.run_pipeline_once(), 2)
    raw = "第一句。最后一句。"
    assert updates[-1].finished and updates[-1].raw_text == raw
    assert deps.llm_provider.calls == ([(raw, "", "manual")] if manual else [])
    assert deps.inserter.text == ("final:" + raw if manual else raw)
    assert not any(state == "polishing" for state, _ in deps.tray.states)
    assert provider.closed
