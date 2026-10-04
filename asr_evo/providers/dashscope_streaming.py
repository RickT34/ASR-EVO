from __future__ import annotations

import asyncio
import base64
import json
import uuid
from collections.abc import AsyncIterator
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from asr_evo.config import RealtimeASRConfig
from asr_evo.core.ports import Transcript


class DashScopeTranscript:
    """Replace each sentence's partial text; never append revisions as new speech."""

    def __init__(self) -> None:
        self.items: dict[str, str] = {}
        self.completed: set[str] = set()

    def accept(self, event: dict) -> Transcript | None:
        kind = event.get("type", "")
        if kind in {"error", "conversation.item.input_audio_transcription.failed"}:
            error = event.get("error", {})
            raise RuntimeError(f"流式 ASR：{error.get('code', '')} {error.get('message', '')}")
        item_id = event.get("item_id", "")
        if kind == "input_audio_buffer.committed":
            self.items.setdefault(item_id, "")
            return None
        if kind == "conversation.item.created":
            self.items.setdefault(event.get("item", {}).get("id", ""), "")
            return None
        if kind == "conversation.item.input_audio_transcription.text":
            if item_id in self.completed:
                return None
            self.items[item_id] = event.get("text", "") + event.get("stash", "")
        elif kind == "conversation.item.input_audio_transcription.completed":
            self.items[item_id] = event.get("transcript", "")
            self.completed.add(item_id)
        else:
            return None
        return Transcript("\n".join(text for text in self.items.values() if text), event.get("language"))


class DashScopeTaskTranscript:
    """Qwen-Audio task protocol identifies revisable sentences by sequence ID."""

    def __init__(self) -> None:
        self.sentences: dict[int, str] = {}
        self.completed: set[int] = set()

    def accept(self, event: dict) -> Transcript | None:
        header = event.get("header", {})
        if header.get("event") == "task-failed":
            raise RuntimeError(
                f"流式 ASR：{header.get('error_code', '')} {header.get('error_message', '')}"
            )
        if header.get("event") != "result-generated":
            return None
        sentence = event.get("payload", {}).get("output", {}).get("sentence", {})
        if not sentence or sentence.get("heartbeat"):
            return None
        self._update(sentence, final=bool(sentence.get("sentence_end")))
        stash = sentence.get("stash")
        if isinstance(stash, dict) and stash.get("text"):
            self._update(stash, final=False)
        return Transcript("\n".join(self.sentences[key] for key in sorted(self.sentences)
                                    if self.sentences[key]))

    def _update(self, sentence: dict, *, final: bool) -> None:
        # Older task responses may use begin_time rather than sentence_id.
        key = int(sentence.get("sentence_id", sentence.get("begin_time", 0)))
        if key in self.completed and not final:
            return
        self.sentences[key] = str(sentence.get("text", ""))
        if final:
            self.completed.add(key)


class DashScopeStreamingASRProvider:
    def __init__(self, config: RealtimeASRConfig, api_key: str) -> None:
        self.config = config.model_copy(deep=True)
        self.api_key = api_key
        self.task_protocol = (
            config.model.startswith("qwen-audio-") and config.model.endswith(("-asr-flash-streaming", "-asr-flash-message"))
        )

    @property
    def url(self) -> str:
        parts = urlsplit(self.config.url)
        query = dict(parse_qsl(parts.query))
        path = parts.path
        if path.rstrip("/") in {"/api-ws/v1/realtime", "/api-ws/v1/inference"}:
            path = "/api-ws/v1/inference" if self.task_protocol else "/api-ws/v1/realtime"
        if self.task_protocol:
            query.pop("model", None)
        else:
            query["model"] = self.config.model
        return urlunsplit(parts._replace(path=path, query=urlencode(query)))

    async def stream(self, chunks: AsyncIterator[bytes]) -> AsyncIterator[Transcript]:
        from websockets.asyncio.client import connect

        async with connect(
            self.url,
            additional_headers={"Authorization": f"Bearer {self.api_key}"},
            open_timeout=30,
            close_timeout=5,
            max_size=4 * 1024 * 1024,
        ) as socket:
            async def send(kind, **payload):
                await socket.send(json.dumps({"event_id": uuid.uuid4().hex, "type": kind, **payload}))

            ready = asyncio.Event()
            task_id = uuid.uuid4().hex

            async def send_task(action, payload):
                await socket.send(json.dumps({
                    "header": {"action": action, "task_id": task_id, "streaming": "duplex"},
                    "payload": payload,
                }))

            async def feed():
                await asyncio.wait_for(ready.wait(), 30)
                async for chunk in chunks:
                    if self.task_protocol:
                        await socket.send(chunk)
                    else:
                        await send("input_audio_buffer.append", audio=base64.b64encode(chunk).decode("ascii"))
                if self.task_protocol:
                    await send_task("finish-task", {"input": {}})
                else:
                    await send("session.finish")

            session = {
                "modalities": ["text"],
                "input_audio_format": "pcm",
                "sample_rate": 16000,
                "turn_detection": {"type": "server_vad", "threshold": 0.2, "silence_duration_ms": 800},
            }
            if self.config.language:
                session["input_audio_transcription"] = {"language": self.config.language}
            if self.task_protocol:
                parameters = {"format": "pcm", "sample_rate": 16000, "heartbeat": True}
                if self.config.model.endswith("-asr-flash-message"):
                    parameters["intermediate_result_enabled"] = True
                    parameters["disfluency_removal_enabled"] = False
                elif self.config.language:
                    parameters["language_hints"] = [self.config.language]
                await send_task("run-task", {
                    "task_group": "audio", "task": "asr", "function": "recognition",
                    "model": self.config.model, "parameters": parameters, "input": {},
                })
            else:
                await send("session.update", session=session)
            feeding = asyncio.create_task(feed())
            transcript = DashScopeTaskTranscript() if self.task_protocol else DashScopeTranscript()
            try:
                while True:
                    receiving = asyncio.create_task(socket.recv())
                    try:
                        # A sender error must surface even when the server is silent.
                        watched = {receiving} if feeding.done() else {receiving, feeding}
                        done, _ = await asyncio.wait(watched, timeout=self.config.timeout_seconds,
                                                     return_when=asyncio.FIRST_COMPLETED)
                        if not done:
                            raise TimeoutError("流式 ASR 响应超时")
                        if feeding.done():
                            feeding.result()
                        event = json.loads(await asyncio.wait_for(receiving, self.config.timeout_seconds))
                    finally:
                        receiving.cancel()
                        await asyncio.gather(receiving, return_exceptions=True)
                    kind = event.get("type")
                    if self.task_protocol:
                        header = event.get("header", {})
                        if header.get("task_id") != task_id:
                            raise RuntimeError("流式 ASR 返回了不匹配的 task_id")
                        kind = header.get("event")
                    if kind == ("task-started" if self.task_protocol else "session.updated"):
                        ready.set()
                    if kind == ("task-finished" if self.task_protocol else "session.finished"):
                        await feeding
                        return
                    update = transcript.accept(event)
                    if update is not None:
                        yield update
            finally:
                feeding.cancel()
                await asyncio.gather(feeding, return_exceptions=True)
