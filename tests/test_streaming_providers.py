from __future__ import annotations

import asyncio
import base64
import json
from types import SimpleNamespace

import numpy as np
import pytest

from asr_evo.config import AppConfig, RealtimeASRConfig
from asr_evo.providers.dashscope_streaming import DashScopeStreamingASRProvider, DashScopeTranscript
from asr_evo.providers.factory import create_streaming_asr_provider
from asr_evo.providers.qwen_stream_worker import run_session
from asr_evo.providers.qwen_streaming import QwenStreamingASRProvider


def test_dashscope_replaces_drafts_and_completed_sentences():
    state = DashScopeTranscript()
    prefix = "conversation.item.input_audio_transcription."
    assert state.accept({"type": prefix + "text", "item_id": "a", "text": "你", "stash": "号"}).text == "你号"
    assert state.accept({"type": prefix + "text", "item_id": "a", "text": "你", "stash": "好"}).text == "你好"
    assert state.accept({"type": prefix + "completed", "item_id": "a", "transcript": "你好。"}).text == "你好。"
    assert state.accept({"type": prefix + "text", "item_id": "b", "text": "再见"}).text == "你好。\n再见"
    assert state.accept({"type": prefix + "completed", "item_id": "b", "transcript": "再见。"}).text == "你好。\n再见。"
    assert state.accept({"type": prefix + "text", "item_id": "a", "stash": "stale"}) is None
    with pytest.raises(RuntimeError, match="broken"):
        state.accept({"type": prefix + "failed", "error": {"message": "broken"}})


async def test_dashscope_sends_pcm_once_and_waits_for_final_sentence(monkeypatch):
    import websockets.asyncio.client

    class Socket:
        def __init__(self):
            self.sent = []
            self.events = asyncio.Queue()

        async def send(self, payload):
            message = json.loads(payload)
            self.sent.append(message)
            if message["type"] == "session.update":
                self.events.put_nowait({"type": "session.updated"})
            elif message["type"] == "input_audio_buffer.append":
                self.events.put_nowait({"type": "conversation.item.input_audio_transcription.text", "item_id": "a", "stash": "草稿"})
            elif message["type"] == "session.finish":
                self.events.put_nowait({"type": "conversation.item.input_audio_transcription.completed", "item_id": "a", "transcript": "最终句子。"})
                self.events.put_nowait({"type": "session.finished"})

        async def recv(self):
            return json.dumps(await self.events.get())

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            self.closed = True

    socket = Socket()
    connections = []

    def connect(url, **kwargs):
        connections.append((url, kwargs))
        return socket

    monkeypatch.setattr(websockets.asyncio.client, "connect", connect)

    async def chunks():
        yield b"\x01\x00"
        yield b"\x02\x00"

    provider = DashScopeStreamingASRProvider(RealtimeASRConfig(backend="dashscope", language="zh"), "test-key")
    results = [result.text async for result in provider.stream(chunks())]
    assert results[-1] == "最终句子。"
    assert "草稿" in results
    assert socket.closed
    assert "model=qwen3-asr-flash-realtime" in connections[0][0]
    assert connections[0][1]["additional_headers"] == {"Authorization": "Bearer test-key"}
    assert socket.sent[0]["session"]["sample_rate"] == 16000
    audio = [base64.b64decode(msg["audio"]) for msg in socket.sent if msg["type"] == "input_audio_buffer.append"]
    assert audio == [b"\x01\x00", b"\x02\x00"]
    assert socket.sent[-1]["type"] == "session.finish"


def test_qwen_worker_uses_native_streaming_state_and_flushes_tail():
    calls = []

    class Model:
        def init_streaming_state(self, **kwargs):
            calls.append(("init", kwargs))
            return SimpleNamespace(text="", language="Chinese")

        def streaming_transcribe(self, pcm, state):
            calls.append(("audio", pcm.copy()))
            state.text += "你好"

        def finish_streaming_transcribe(self, state):
            calls.append(("finish",))
            state.text += "。"

    def factory(**kwargs):
        calls.append(("model", kwargs))
        return Model()

    messages = [json.dumps({"type": "audio", "audio": base64.b64encode(np.array([0, 16384], dtype="<i2").tobytes()).decode()}), json.dumps({"type": "finish"})]
    events = []
    run_session(RealtimeASRConfig(model="Qwen/Qwen3-ASR-0.6B").model_dump(), messages, events.append, factory)
    assert [c[0] for c in calls] == ["model", "init", "audio", "finish"]
    np.testing.assert_array_equal(calls[2][1], [0, 0.5])
    assert events[-2]["text"] == "你好。"
    assert events[-1]["type"] == "done"


async def test_local_stream_worker_is_reaped_when_cancelled(tmp_path, monkeypatch):
    import asr_evo.providers.qwen_streaming as module

    worker = tmp_path / "worker.py"
    worker.write_text('import json,sys,time\njson.loads(sys.stdin.readline())\nprint(json.dumps({"type":"ready"}),flush=True)\nfor line in sys.stdin:\n print(json.dumps({"type":"transcript","text":"partial"}),flush=True)\n time.sleep(60)\n')
    original_spawn = asyncio.create_subprocess_exec
    processes = []

    async def spawn(executable, path, **kwargs):
        process = await original_spawn(executable, str(worker), **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(module.asyncio, "create_subprocess_exec", spawn)

    async def chunks():
        yield b"\0\0"
        await asyncio.Event().wait()

    provider = QwenStreamingASRProvider(RealtimeASRConfig(timeout_seconds=2))
    stream = provider.stream(chunks())
    assert (await asyncio.wait_for(anext(stream), 2)).text == "partial"
    await stream.aclose()
    assert processes[0].returncode is not None


def test_streaming_config_requires_explicit_backend_and_separate_key(monkeypatch):
    config = AppConfig()
    with pytest.raises(RuntimeError, match="realtime_asr"):
        create_streaming_asr_provider(config)
    config.realtime_asr.backend = "dashscope"
    monkeypatch.delenv("ASR_REALTIME_API_KEY", raising=False)
    monkeypatch.setenv("ASR_API_KEY", "ordinary-key")
    with pytest.raises(RuntimeError, match="ASR_REALTIME_API_KEY"):
        create_streaming_asr_provider(config)
    monkeypatch.setenv("ASR_REALTIME_API_KEY", "streaming-key")
    assert create_streaming_asr_provider(config).api_key == "streaming-key"


def test_dashscope_preserves_utterance_order_when_completion_arrives_out_of_order():
    state = DashScopeTranscript()
    for item in ("a", "b"):
        state.accept({"type": "input_audio_buffer.committed", "item_id": item})
    prefix = "conversation.item.input_audio_transcription."
    state.accept({"type": prefix + "completed", "item_id": "b", "transcript": "第二句"})
    assert state.accept({"type": prefix + "completed", "item_id": "a", "transcript": "第一句"}).text == "第一句\n第二句"


def test_realtime_config_roundtrip_keeps_secret_out_of_toml(tmp_path, monkeypatch):
    monkeypatch.setenv("ASR_REALTIME_API_KEY", "private-stream-secret")
    config = AppConfig()
    config.realtime_asr.backend = "dashscope"
    config.review.realtime_enabled = True
    path = tmp_path / "config.toml"
    config.save(path)
    restored = AppConfig.load(path)
    assert restored.realtime_asr == config.realtime_asr
    assert restored.review.realtime_enabled
    assert restored.realtime_asr_api_key() == "private-stream-secret"
    assert "private-stream-secret" not in path.read_text()


@pytest.mark.parametrize("model", ["qwen-audio-3.0-asr-flash-streaming", "qwen-audio-3.1-asr-flash-streaming", "qwen-audio-3.1-asr-flash-message"])
async def test_qwen_audio_task_protocol_uploads_binary_and_flushes_tail(monkeypatch, model):
    import websockets.asyncio.client

    sent = []
    events = asyncio.Queue()
    connections = []
    task_id = None

    def event(kind, payload=None):
        return {"header": {"event": kind, "task_id": task_id}, "payload": payload or {}}

    def sentence(text, final=False):
        return {"output": {"sentence": {"sentence_id": 1, "text": text, "sentence_end": final}}}

    class Socket:
        async def send(self, data):
            nonlocal task_id
            if isinstance(data, bytes):
                assert task_id is not None
                sent.append(data)
                events.put_nowait(event("result-generated", sentence("临时文本")))
                return
            message = json.loads(data)
            sent.append(message)
            if message["header"]["action"] == "run-task":
                task_id = message["header"]["task_id"]
                events.put_nowait(event("task-started"))
            else:
                assert message["header"]["task_id"] == task_id
                events.put_nowait(event("result-generated", sentence("最终文本。", True)))
                events.put_nowait(event("task-finished"))

        async def recv(self):
            return json.dumps(await events.get())

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    def connect(url, **kwargs):
        connections.append(url)
        return Socket()

    monkeypatch.setattr(websockets.asyncio.client, "connect", connect)

    async def chunks():
        yield b"\x01\x00"
        yield b"\x02\x00"

    config = RealtimeASRConfig(backend="dashscope", model=model, language="zh")
    provider = DashScopeStreamingASRProvider(config, "test-key")
    results = [result.text async for result in provider.stream(chunks())]
    assert connections == ["wss://dashscope.aliyuncs.com/api-ws/v1/inference"]
    assert results[-1] == "最终文本。"
    assert sent[0]["payload"]["model"] == model
    parameters = sent[0]["payload"]["parameters"]
    if model.endswith("-message"):
        assert parameters["intermediate_result_enabled"] is True
        assert parameters["disfluency_removal_enabled"] is False
        assert "language_hints" not in parameters
    else:
        assert parameters["language_hints"] == ["zh"]
    assert sent[1:3] == [b"\x01\x00", b"\x02\x00"]
    assert sent[-1]["header"]["action"] == "finish-task"
    assert sent[-1]["payload"] == {"input": {}}


def test_task_transcript_revisions_stash_heartbeats_and_errors():
    from asr_evo.providers.dashscope_streaming import DashScopeTaskTranscript

    transcript = DashScopeTaskTranscript()

    def result(**sentence):
        return transcript.accept({"header": {"event": "result-generated"},
                                  "payload": {"output": {"sentence": sentence}}})

    assert result(sentence_id=1, text="你号").text == "你号"
    assert result(sentence_id=1, text="你好。", sentence_end=True,
                  stash={"sentence_id": 2, "text": "下句草稿"}).text == "你好。\n下句草稿"
    assert result(sentence_id=0, heartbeat=True) is None
    assert result(sentence_id=2, text="第二句。", sentence_end=True).text == "你好。\n第二句。"
    assert result(sentence_id=1, text="迟到草稿").text == "你好。\n第二句。"
    with pytest.raises(RuntimeError, match="ModelNotFound.*missing"):
        transcript.accept({"header": {"event": "task-failed", "error_code": "ModelNotFound", "error_message": "missing"}})


def test_task_protocol_keeps_region_workspace_and_other_query_parameters():
    config = RealtimeASRConfig(model="qwen-audio-3.0-asr-flash-streaming",
        url="wss://workspace.ap-southeast-1.maas.aliyuncs.com/api-ws/v1/realtime?model=old&other=value")
    assert DashScopeStreamingASRProvider(config, "key").url == (
        "wss://workspace.ap-southeast-1.maas.aliyuncs.com/api-ws/v1/inference?other=value"
    )


def test_websocket_model_not_found_reports_configuration_error():
    from asr_evo.core.errors import feedback_from_exception

    error = RuntimeError("received 1007 (invalid frame payload data) Model not found (example)!")
    feedback = feedback_from_exception(error)
    assert feedback.title == "模型或接口配置有误"
    assert "realtime_asr.model" in feedback.suggestion
