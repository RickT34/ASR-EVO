from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from asr_evo.config import ASRConfig, AppConfig
from asr_evo.core.ports import AudioClip
from asr_evo.providers.dashscope_filetrans import DashScopeFileTransASRProvider, filetrans_api_base
from asr_evo.providers.factory import create_asr_provider
from asr_evo.providers.openai_provider import OpenAIChatCompletionsASRProvider


async def test_filetrans_upload_poll_and_download_do_not_leak_api_key(tmp_path):
    path = tmp_path / 'private-name.wav'
    path.write_bytes(b'audio contents')
    calls = []

    async def handler(request):
        calls.append(request)
        if request.url.host == 'upload.example':
            assert 'authorization' not in request.headers
            body = await request.aread()
            assert b'audio contents' in body
            assert b'private-name' not in body
            assert b'upload-signature' in body
            return httpx.Response(200)
        if request.url.host == 'result.example':
            assert 'authorization' not in request.headers
            return httpx.Response(200, json={'transcripts': [{'text': '识别结果。'}]})
        assert request.headers['authorization'] == 'Bearer test-key'
        if request.url.path.endswith('/uploads'):
            assert request.url.params['model'] == 'qwen-audio-3.0-asr-flash-filetrans'
            return httpx.Response(200, json={'data': {
                'upload_host': 'https://upload.example', 'upload_dir': 'temporary',
                'oss_access_key_id': 'upload-key', 'signature': 'upload-signature',
                'policy': 'policy-value', 'x_oss_object_acl': 'private', 'x_oss_forbid_overwrite': 'true',
            }})
        if request.method == 'POST':
            assert request.url.path == '/api/v1/services/audio/asr/transcription'
            assert request.headers['X-DashScope-Async'] == 'enable'
            assert request.headers['X-DashScope-OssResourceResolve'] == 'enable'
            payload = json.loads(request.content)
            assert payload['parameters'] == {}
            assert payload['input']['file_urls'][0].startswith('oss://temporary/')
            return httpx.Response(200, json={'output': {'task_id': 'task-1', 'task_status': 'PENDING'}})
        assert request.url.path == '/api/v1/tasks/task-1'
        return httpx.Response(200, json={'output': {'task_status': 'SUCCEEDED', 'results': [
            {'subtask_status': 'SUCCEEDED', 'transcription_url': 'https://result.example/transcript.json'},
        ]}})

    provider = DashScopeFileTransASRProvider(ASRConfig(model='qwen-audio-3.0-asr-flash-filetrans'), 'test-key')
    await provider.client.aclose()
    provider.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        assert (await provider.transcribe(AudioClip(path, 16000, 1))).text == '识别结果。'
        assert len(calls) == 5
    finally:
        await provider.aclose()
    assert path.exists()


@pytest.mark.parametrize('state', ['FAILED', 'CANCELED', 'UNKNOWN'])
async def test_filetrans_task_failure_is_not_empty_success(tmp_path, monkeypatch, state):
    path = tmp_path / 'audio.wav'
    path.write_bytes(b'audio')
    provider = DashScopeFileTransASRProvider(ASRConfig(), 'test-key')
    async def upload(audio):
        return 'oss://temporary/audio.wav'
    monkeypatch.setattr(provider, '_upload', upload)
    def handler(request):
        output = {'task_id': 'one'} if request.method == 'POST' else {'task_status': state, 'code': 'TEST_FAILURE'}
        return httpx.Response(200, json={'output': output})
    await provider.client.aclose()
    provider.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(RuntimeError, match='TEST_FAILURE'):
            await provider.transcribe(AudioClip(path, 16000, 1))
    finally:
        await provider.aclose()


async def test_filetrans_subtask_failure_and_poll_timeout(tmp_path, monkeypatch):
    provider = DashScopeFileTransASRProvider(ASRConfig(timeout_seconds=0.01), 'key')
    with pytest.raises(RuntimeError, match='FILE_DOWNLOAD_FAILED'):
        await provider._result({'results': [{'subtask_status': 'FAILED', 'code': 'FILE_DOWNLOAD_FAILED'}]})
    path = tmp_path / 'audio.wav'
    path.write_bytes(b'audio')
    async def upload(audio):
        return 'oss://temporary/audio.wav'
    monkeypatch.setattr(provider, '_upload', upload)
    def handler(request):
        return httpx.Response(200, json={'output': {'task_id': 'one', 'task_status': 'RUNNING'}})
    await provider.client.aclose()
    provider.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(RuntimeError, match='timeout'):
            await provider.transcribe(AudioClip(path, 16000, 1))
    finally:
        await provider.aclose()


async def test_backend_selection_is_explicit_and_does_not_change_openai(monkeypatch):
    monkeypatch.setenv('ASR_API_KEY', 'test-key')
    config = AppConfig()
    config.asr.model = 'qwen-audio-3.0-asr-flash-filetrans'
    openai = create_asr_provider(config)
    assert isinstance(openai, OpenAIChatCompletionsASRProvider)
    config.asr.backend = 'dashscope_filetrans'
    native = create_asr_provider(config)
    assert isinstance(native, DashScopeFileTransASRProvider)
    await asyncio.gather(openai.aclose(), native.aclose())


def test_native_base_preserves_region_and_workspace():
    assert filetrans_api_base('https://workspace.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1') == (
        'https://workspace.ap-southeast-1.maas.aliyuncs.com/api/v1'
    )
