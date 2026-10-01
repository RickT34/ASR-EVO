from __future__ import annotations

import asyncio
import json
import sys
from types import SimpleNamespace

import httpx
import pytest

from asr_evo.config import ASRConfig, AppConfig, LLMProfileConfig
from asr_evo.core.ports import AudioClip
from asr_evo.providers.factory import create_providers
from asr_evo.providers.local_asr import QwenLocalASRProvider
from asr_evo.providers.ollama_provider import OllamaLLMProvider
from asr_evo.providers.qwen_worker import transcribe


def test_worker_passes_device_language_and_audio_to_qwen(monkeypatch):
    calls = []

    class Model:
        @classmethod
        def from_pretrained(cls, model, **kwargs):
            calls.append((model, kwargs))
            return cls()

        def transcribe(self, **kwargs):
            calls.append(kwargs)
            return [SimpleNamespace(text="你好", language="Chinese")]

    monkeypatch.setitem(sys.modules, "qwen_asr", SimpleNamespace(Qwen3ASRModel=Model))
    monkeypatch.setitem(
        sys.modules,
        "torch",
        SimpleNamespace(
            cuda=SimpleNamespace(is_available=lambda: False),
            float32="fp32",
        ),
    )
    result = transcribe(
        {
            "model": "Qwen/Qwen3-ASR-0.6B",
            "device": "auto",
            "dtype": "auto",
            "audio": "/tmp/audio.wav",
            "language": "",
        }
    )
    assert result == {"text": "你好", "language": "Chinese"}
    assert calls[0][1]["device_map"] == "cpu"
    assert calls[0][1]["dtype"] == "fp32"
    assert calls[1] == {"audio": "/tmp/audio.wav", "language": None}


async def test_local_factory_requires_no_api_keys_and_does_not_start_workers(monkeypatch):
    monkeypatch.delenv("ASR_API_KEY", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    config = AppConfig.model_validate(
        {
            "asr": {"backend": "qwen_local", "model": "Qwen/Qwen3-ASR-0.6B"},
            "llm": {
                "default_profile": "local",
                "profiles": {
                    "local": {
                        "backend": "ollama",
                        "base_url": "http://localhost:11434",
                        "model": "qwen3:4b",
                    },
                },
            },
        }
    )
    asr, llm = create_providers(config)
    assert isinstance(asr, QwenLocalASRProvider)
    assert asr._process is None
    assert isinstance(llm.default_provider, OllamaLLMProvider)
    assert not llm.default_provider._used
    await asr.aclose()
    await llm.aclose()


@pytest.fixture
def worker(monkeypatch, tmp_path):
    script = tmp_path / "worker.py"
    processes = []
    create = asyncio.create_subprocess_exec

    async def spawn(*args, **kwargs):
        process = await create(sys.executable, str(script), **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"audio")
    return script, processes, AudioClip(audio, 16000, 1)


async def test_asr_uses_new_worker_and_reaps_it_after_every_request(worker):
    script, processes, audio = worker
    script.write_text(
        'import sys, json\njson.load(sys.stdin)\nprint(json.dumps({"text":"hello", "language":"English"}))'
    )
    provider = QwenLocalASRProvider(ASRConfig())
    for _ in range(2):
        assert (await provider.transcribe(audio)).text == "hello"
    assert len(processes) == 2
    assert processes[0].pid != processes[1].pid
    assert all(p.returncode == 0 for p in processes)
    assert provider._process is None
    await provider.aclose()
    with pytest.raises(RuntimeError, match="closed"):
        await provider.transcribe(audio)


async def test_asr_worker_error_is_reported_and_reaped(worker):
    script, processes, audio = worker
    script.write_text('import sys\nsys.stderr.write("no GPU memory")\nsys.exit(1)')
    provider = QwenLocalASRProvider(ASRConfig())
    with pytest.raises(RuntimeError, match="no GPU memory"):
        await provider.transcribe(audio)
    assert processes[0].returncode == 1
    assert provider._process is None


async def test_asr_timeout_kills_worker(worker):
    script, processes, audio = worker
    script.write_text("import time; time.sleep(30)")
    provider = QwenLocalASRProvider(ASRConfig(timeout_seconds=0.1))
    with pytest.raises(RuntimeError, match="timeout_seconds"):
        await provider.transcribe(audio)
    assert processes[0].returncode is not None


async def test_asr_cancellation_kills_worker(worker):
    script, processes, audio = worker
    script.write_text("import time; time.sleep(30)")
    provider = QwenLocalASRProvider(ASRConfig())
    task = asyncio.create_task(provider.transcribe(audio))
    async with asyncio.timeout(3):
        while provider._process is None:
            await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert processes[0].returncode is not None


async def test_ollama_uses_native_unload_and_json_protocol():
    requests = []

    def handler(request):
        payload = json.loads(request.content)
        requests.append((request.url.path, payload))
        if request.url.path == "/api/generate":
            return httpx.Response(200, json={"done": True})
        return httpx.Response(200, json={"message": {"content": '{"ok":true}'}})

    provider = OllamaLLMProvider(
        LLMProfileConfig(
            backend="ollama",
            base_url="http://localhost:11434",
            model="qwen3:4b",
            enable_thinking=False,
        )
    )
    await provider.client.aclose()
    provider.client = httpx.AsyncClient(
        base_url="http://localhost:11434/",
        transport=httpx.MockTransport(handler),
    )
    assert await provider.complete_json([{"role": "user", "content": "JSON"}]) == {"ok": True}
    assert requests[0][1]["keep_alive"] == 0
    assert requests[0][1]["think"] is False
    assert requests[0][1]["stream"] is False
    assert requests[0][1]["format"] == "json"
    await provider.aclose()
    await provider.aclose()
    assert requests[-1] == ("/api/generate", {"model": "qwen3:4b", "keep_alive": 0})
    assert len(requests) == 2
    assert provider.client.is_closed


async def test_ollama_close_closes_http_client_even_when_unload_fails():
    provider = OllamaLLMProvider(
        LLMProfileConfig(
            backend="ollama",
            base_url="http://localhost:11434",
            model="qwen3:4b",
        )
    )
    await provider.client.aclose()
    provider.client = httpx.AsyncClient(
        base_url="http://localhost:11434/",
        transport=httpx.MockTransport(lambda r: httpx.Response(500)),
    )
    provider._used = True
    with pytest.raises(httpx.HTTPStatusError):
        await provider.aclose()
    assert provider.client.is_closed


async def test_asr_shutdown_reaps_an_active_verbose_worker(worker):
    script, processes, audio = worker
    script.write_text(
        "import sys, time\n"
        "sys.stdin.read()\n"
        "while True:\n"
        '    sys.stderr.write("x" * 65536)\n'
        "    sys.stderr.flush()\n"
        "    time.sleep(0.001)\n"
    )
    provider = QwenLocalASRProvider(ASRConfig())
    task = asyncio.create_task(provider.transcribe(audio))
    async with asyncio.timeout(3):
        while provider._process is None:
            await asyncio.sleep(0.01)
        await provider.aclose()
        with pytest.raises(RuntimeError, match="Local Qwen ASR failed"):
            await task
    assert processes[0].returncode is not None
    assert provider._process is None
