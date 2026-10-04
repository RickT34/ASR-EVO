from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from asr_evo.core.context import DictationRecord
from asr_evo.core.pipeline import DictationPipeline, DictationPipelineError, DictationResult, render_context
from asr_evo.core.ports import LiveTextReview, StreamingASRProvider, TextReviewUpdate
from asr_evo.core.review import TextReviewService


class RealtimeDictationSession:
    """One microphone, streaming recognizer, polish loop, and review window."""

    def __init__(
        self, pipeline: DictationPipeline, review: TextReviewService,
        asr: StreamingASRProvider, *, polish_interval: float, finish_timeout: float,
    ) -> None:
        self.pipeline = pipeline
        self.review = review
        self.asr = asr
        self.polish_interval = polish_interval
        self.finish_timeout = finish_timeout
        self.live = LiveTextReview(asyncio.Queue(maxsize=1), self._stop_recording)
        self.recording_task = None
        self.raw_text = ""
        self.polished_text = ""
        self.polished_raw = ""
        self.audio = None
        self.review_task = None
        self.stopping = asyncio.Event()
        self.started_at = datetime.now(UTC)
        self.app = None
        self.context = ""

    def _stop_recording(self) -> None:
        # A late/repeated click must not arm the recorder's next recording to stop.
        if self.recording_task is not None and not self.recording_task.done():
            self.pipeline.dependencies.recorder.stop()

    def _result(self) -> DictationResult:
        return DictationResult(
            raw_text=self.raw_text, final_text=self.polished_text,
            record=DictationRecord.create(
                started_at=self.started_at, raw_text=self.raw_text,
                final_text=self.polished_text, style=self.pipeline.options.style,
                app_context=self.app,
            ),
            audio_seconds=self.audio.duration_seconds if self.audio else 0,
            audio=self.audio, app_context=self.app, context=self.context,
        )

    def _publish(self, status: str, *, finished: bool = False) -> None:
        self.live.raw_text = self.raw_text
        right = self.polished_text
        if not finished and self.raw_text != self.polished_raw:
            if not right:
                right = self.raw_text
            else:
                tail = (self.raw_text[len(self.polished_raw):]
                        if self.raw_text.startswith(self.polished_raw) else self.raw_text)
                right += "\n\n（待润色）\n" + tail
        update = TextReviewUpdate(self.raw_text, right, status, finished, not self.stopping.is_set())
        if self.live.updates.full():
            self.live.updates.get_nowait()
        self.live.updates.put_nowait(update)

    async def _polish(self) -> None:
        raw = self.raw_text
        if not raw.strip() or raw == self.polished_raw:
            return
        options = self.pipeline.options
        text = await self.pipeline.dependencies.llm.polish(
            raw, self.context, options.prompt_instruction, profile=options.llm_profile,
        )
        self.polished_raw = raw
        self.polished_text = text
        self._publish("润色已更新" if not self.stopping.is_set() else "正在完成最终润色…")

    async def _polish_loop(self) -> None:
        while not self.stopping.is_set():
            try:
                await asyncio.wait_for(self.stopping.wait(), self.polish_interval)
                return
            except TimeoutError:
                pass
            try:
                await self._polish()
            except Exception as exc:
                self._publish(f"本次润色失败，下次重试：{exc}")

    async def run(self) -> DictationResult:
        deps = self.pipeline.dependencies
        self.app = deps.app_provider.current_app()  # Capture before the review window takes focus.
        self.context = render_context(deps, self.app) if self.pipeline.options.context_enabled else ""
        loop = asyncio.get_running_loop()
        # At 100 ms per frame this bounds startup/backpressure to two minutes.
        chunks = asyncio.Queue(maxsize=1200)
        overflow = loop.create_future()
        accepting = True

        def enqueue(chunk):
            if not accepting or overflow.done():
                return
            try:
                chunks.put_nowait(chunk)
            except asyncio.QueueFull:
                overflow.set_result(True)
                deps.recorder.stop()

        def on_chunk(chunk):
            loop.call_soon_threadsafe(enqueue, chunk)

        async def record():
            self.audio = await deps.recorder.record_until_stopped(on_chunk=on_chunk)

        async def audio_stream():
            while True:
                chunk = await chunks.get()
                if chunk is None:
                    return
                yield chunk

        async def transcribe():
            async for transcript in self.asr.stream(audio_stream()):
                if transcript.text == self.raw_text:
                    continue
                self.raw_text = transcript.text
                if not self.pipeline.options.auto_polish:
                    self.polished_text = self.raw_text
                    self.polished_raw = self.raw_text
                self._publish("正在录音 · 实时转写" if not self.stopping.is_set() else "正在完成转写…")

        recording = asyncio.create_task(record())
        self.recording_task = recording
        transcribing = asyncio.create_task(transcribe())
        polishing = asyncio.create_task(self._polish_loop()) if self.pipeline.options.auto_polish else None
        self.review_task = asyncio.create_task(self.review.review(self._result(), enabled=True, live=self.live))
        finishing = None
        deps.tray.set_state("recording")
        try:
            done, _ = await asyncio.wait(
                {recording, transcribing, self.review_task, overflow},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if recording not in done:
                deps.recorder.stop()
            await recording
            accepting = False
            self.stopping.set()
            if overflow.done():
                raise RuntimeError("流式 ASR 处理过慢，音频缓冲已满；录音已停止并保留，请检查模型或网络")
            if self.review_task.done():
                self.review_task.result()  # Propagate dialog failures, retain cancellation history.
                return self._result()
            if transcribing in done:
                transcribing.result()
                raise RuntimeError("流式 ASR 在录音结束前断开")
            deps.tray.set_state("transcribing")
            self._publish("录音已停止，正在完成转写…")

            async def finish():
                await chunks.put(None)
                await asyncio.wait_for(transcribing, self.finish_timeout)
                # Let an in-flight polish finish; reuse it when the final transcript is unchanged.
                if polishing is not None:
                    await polishing
                    deps.tray.set_state("polishing")
                    await self._polish()

            finishing = asyncio.create_task(finish())
            done, _ = await asyncio.wait({finishing, self.review_task}, return_when=asyncio.FIRST_COMPLETED)
            if self.review_task in done:
                self.review_task.result()
                return self._result()
            await finishing
            self._publish("处理完成，可以编辑、手动润色或确认", finished=True)
            deps.tray.set_state("reviewing")
            return self._result()
        except Exception as exc:
            result = self._result()
            raise DictationPipelineError(
                str(exc), raw_text=self.raw_text, record=result.record,
                audio=self.audio, audio_seconds=result.audio_seconds,
            ) from exc
        finally:
            accepting = False
            self.stopping.set()
            if not recording.done():
                deps.recorder.stop()
            tasks = [recording, transcribing]
            if polishing is not None:
                tasks.append(polishing)
            if finishing is not None:
                tasks.append(finishing)
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            overflow.cancel()

    async def close(self) -> None:
        if self.review_task is not None:
            if not self.review_task.done():
                self.review_task.cancel()
            await asyncio.gather(self.review_task, return_exceptions=True)
