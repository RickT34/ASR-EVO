from __future__ import annotations

import asyncio
import mimetypes
import re
import uuid
from urllib.parse import quote, urlsplit, urlunsplit

import httpx

from asr_evo.config import ASRConfig
from asr_evo.core.ports import AudioClip, Transcript


def filetrans_api_base(base_url: str) -> str:
    parts = urlsplit(base_url)
    path = parts.path.rstrip("/")
    if path in {"", "/compatible-mode/v1", "/api/v1"}:
        path = "/api/v1"
    elif path == "/api/v1/services/audio/asr/transcription":
        path = "/api/v1"
    else:
        raise ValueError("Filetrans 需要百炼原生 API 地址，例如 https://dashscope.aliyuncs.com/api/v1")
    if parts.scheme != "https":
        raise ValueError("Filetrans API 地址必须使用 https://")
    return urlunsplit(parts._replace(path=path, query="", fragment=""))


class DashScopeFileTransASRProvider:
    """Local file -> temporary OSS upload -> asynchronous native ASR task."""

    def __init__(self, config: ASRConfig, api_key: str) -> None:
        self.config = config.model_copy(deep=True)
        self.base_url = filetrans_api_base(config.base_url)
        # Never set default Authorization: upload/result URLs are different services.
        self.client = httpx.AsyncClient(timeout=config.timeout_seconds)
        self._auth = {"Authorization": f"Bearer {api_key}"}

    async def transcribe(self, audio: AudioClip) -> Transcript:
        if self.config.model.endswith("-asr-flash-message"):
            raise ValueError("Message 模型不能使用 Filetrans 接口，请将 asr.backend 改为 dashscope_message")
        if not audio.path.is_file():
            raise FileNotFoundError(audio.path)
        if audio.path.stat().st_size > 2 * 1024**3 or audio.duration_seconds > 12 * 3600:
            raise ValueError("Filetrans 音频不得超过 2 GB / 12 小时")
        try:
            async with asyncio.timeout(self.config.timeout_seconds):
                file_url = await self._upload(audio)
                parameters = {}
                if self.config.language:
                    parameters["language_hints"] = [self.config.language]
                response = await self.client.post(
                    f"{self.base_url}/services/audio/asr/transcription",
                    headers={**self._auth, "X-DashScope-Async": "enable",
                             "X-DashScope-OssResourceResolve": "enable"},
                    json={"model": self.config.model, "input": {"file_urls": [file_url]},
                          "parameters": parameters},
                )
                output = _json(response, "提交转写任务").get("output", {})
                task_id = output.get("task_id")
                if not task_id:
                    raise RuntimeError("Filetrans 提交任务未返回 task_id")
                while True:
                    response = await self.client.get(
                        f"{self.base_url}/tasks/{quote(str(task_id), safe='')}", headers=self._auth,
                    )
                    output = _json(response, "查询转写任务").get("output", {})
                    status = output.get("task_status")
                    if status == "SUCCEEDED":
                        return await self._result(output)
                    if status not in {"PENDING", "RUNNING"}:
                        raise RuntimeError(
                            f"Filetrans 任务失败 ({status})：{output.get('code', '')} {output.get('message', '')}"
                        )
                    await asyncio.sleep(1)
        except TimeoutError as exc:
            raise RuntimeError("Filetrans 转写超时 (timeout)，请检查 asr.timeout_seconds 或服务任务状态") from exc

    async def _upload(self, audio: AudioClip) -> str:
        response = await self.client.get(
            f"{self.base_url}/uploads", headers=self._auth,
            params={"action": "getPolicy", "model": self.config.model},
        )
        policy = _json(response, "获取临时上传凭证").get("data", {})
        host = _https_resource(policy.get("upload_host", ""))
        filename = uuid.uuid4().hex + audio.path.suffix
        key = policy["upload_dir"].rstrip("/") + "/" + filename
        mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        form = {
            "OSSAccessKeyId": policy["oss_access_key_id"], "Signature": policy["signature"],
            "policy": policy["policy"], "key": key,
            "x-oss-object-acl": policy["x_oss_object_acl"],
            "x-oss-forbid-overwrite": policy["x_oss_forbid_overwrite"],
            "success_action_status": "200", "x-oss-content-type": mime,
        }
        with audio.path.open("rb") as source:
            response = await self.client.post(host, data=form, files={"file": (filename, source, mime)})
        _check_status(response, "上传录音")
        return "oss://" + key

    async def _result(self, output: dict) -> Transcript:
        results = output.get("results", [])
        if len(results) != 1:
            raise RuntimeError("Filetrans 未返回唯一的文件转写结果")
        result = results[0]
        if result.get("subtask_status") != "SUCCEEDED":
            raise RuntimeError(f"Filetrans 文件识别失败：{result.get('code', '')} {result.get('message', '')}")
        response = await self.client.get(_https_resource(result.get("transcription_url", "")))
        document = _json(response, "下载转写结果")
        transcripts = document.get("transcripts")
        if not isinstance(transcripts, list):
            raise RuntimeError("Filetrans 结果缺少 transcripts 字段")
        return Transcript("\n".join(str(item.get("text", "")) for item in transcripts).strip())

    async def aclose(self) -> None:
        await self.client.aclose()


def _https_resource(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
        raise RuntimeError("Filetrans 服务返回了无效的 HTTPS 资源地址")
    return url


def _check_status(response: httpx.Response, stage: str) -> None:
    if response.is_success:
        return
    # Include selected diagnostics, not the complete body or signed resource URLs.
    detail = ""
    try:
        payload = response.json()
        error = payload.get("error", payload)
        if isinstance(error, dict):
            detail = " ".join(str(value) for value in (
                error.get("code", ""), error.get("message", ""), payload.get("request_id", ""),
            ) if value)
            detail = re.sub(r"(?:https?|oss)://[^\s<>]+|data:[^\s]+", "[资源地址已隐藏]", detail)
            detail = re.sub(r"Bearer\s+\S+|sk-[A-Za-z0-9_-]+", "[密钥已隐藏]", detail)
    except (ValueError, AttributeError):
        pass
    raise RuntimeError(f"Provider HTTP {response.status_code}: Filetrans {stage}失败 {detail[:1000]}".strip())


def _json(response: httpx.Response, stage: str) -> dict:
    _check_status(response, stage)
    data = response.json()
    if data.get("code"):
        raise RuntimeError(f"Filetrans {stage}失败：{data['code']} {data.get('message', '')}")
    return data
