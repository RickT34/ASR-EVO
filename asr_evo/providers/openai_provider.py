from __future__ import annotations

import base64
import json
import mimetypes
from pathlib import Path
from typing import Any

from openai import AsyncOpenAI

from asr_evo.core.ports import AudioClip, Transcript
from asr_evo.postprocess.prompts import build_polish_messages
from asr_evo.providers.request_debug import RemoteRequestDebugOptions, dump_remote_request


class OpenAIChatCompletionsLLMProvider:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        enable_thinking: bool = False,
        timeout_seconds: float = 30,
        request_debug: RemoteRequestDebugOptions | None = None,
    ) -> None:
        self.model = model
        self.enable_thinking = enable_thinking
        self.base_url = base_url.rstrip("/")
        self.request_debug = request_debug or RemoteRequestDebugOptions()
        self._debug_headers = {"Authorization": f"Bearer {api_key}"}
        self.client = AsyncOpenAI(
            api_key=api_key,
            base_url=self.base_url,
            timeout=timeout_seconds,
        )

    async def polish(self, raw_text: str, context: str, prompt_instruction: str) -> str:
        messages = build_polish_messages(
            raw_text=raw_text,
            context=context,
            prompt_instruction=prompt_instruction,
        )
        return await self.complete_messages(messages, temperature=0.2)

    async def complete_messages(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.2,
        response_format: dict[str, str] | None = None,
    ) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "enable_thinking": self.enable_thinking,
        }
        if response_format is not None:
            payload["response_format"] = response_format
        dump_remote_request(
            provider="openai-llm",
            method="POST",
            url=f"{self.base_url}/chat/completions",
            headers=self._debug_headers,
            json_payload=payload,
            options=self.request_debug,
        )
        sdk_payload = dict(payload)
        sdk_payload.pop("enable_thinking")
        response = await self.client.chat.completions.create(
            **sdk_payload,
            extra_body={"enable_thinking": self.enable_thinking},
        )
        content = response.choices[0].message.content or ""
        return content.strip()

    async def complete_json(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0,
    ) -> dict[str, Any]:
        content = await self.complete_messages(
            messages,
            temperature=temperature,
            response_format={"type": "json_object"},
        )
        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            raise ValueError("LLM response was not valid JSON") from exc

    async def aclose(self) -> None:
        await self.client.close()


class OpenAIChatCompletionsASRProvider:
    def __init__(
        self,
        *,
        api_key: str,
        model: str = "qwen3-asr-flash",
        base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
        language: str | None = "zh",
        enable_itn: bool = True,
        max_audio_mb: int = 10,
        timeout_seconds: float = 60,
        request_debug: RemoteRequestDebugOptions | None = None,
    ) -> None:
        self.model = model
        self.language = language
        self.enable_itn = enable_itn
        self.max_audio_bytes = max_audio_mb * 1024 * 1024
        self.base_url = base_url.rstrip("/")
        self.request_debug = request_debug or RemoteRequestDebugOptions()
        self._debug_headers = {"Authorization": f"Bearer {api_key}"}
        self.client = AsyncOpenAI(
            api_key=api_key,
            base_url=self.base_url,
            timeout=timeout_seconds,
        )

    async def transcribe(self, audio: AudioClip) -> Transcript:
        audio_path = Path(audio.path)
        if not audio_path.exists():
            raise FileNotFoundError(audio_path)
        size = audio_path.stat().st_size
        if size > self.max_audio_bytes:
            raise ValueError(f"Audio file is {size} bytes, exceeding configured ASR limit")

        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_audio",
                        "input_audio": {
                            "data": self._audio_data_url(audio_path),
                        },
                    }
                ],
            }
        ]
        asr_options = self._asr_options()
        debug_payload = {
            "model": self.model,
            "messages": messages,
            "asr_options": asr_options,
            "stream": False,
        }
        dump_remote_request(
            provider="openai-asr",
            method="POST",
            url=f"{self.base_url}/chat/completions",
            headers=self._debug_headers,
            json_payload=debug_payload,
            options=self.request_debug,
        )
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            stream=False,
            extra_body={"asr_options": asr_options},
        )
        message = response.choices[0].message
        return Transcript(text=_message_content(message).strip(), language=_message_language(message))

    def _asr_options(self) -> dict[str, object]:
        options: dict[str, object] = {"enable_itn": self.enable_itn}
        if self.language:
            options["language"] = self.language
        return options

    def _audio_data_url(self, path: Path) -> str:
        mime_type = mimetypes.guess_type(path.name)[0] or "audio/wav"
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        return f"data:{mime_type};base64,{encoded}"

    async def aclose(self) -> None:
        await self.client.close()


def _message_content(message: object) -> str:
    content = getattr(message, "content", "")
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    return str(content)


def _message_language(message: object) -> str | None:
    annotations = _message_annotations(message)
    for annotation in annotations:
        if hasattr(annotation, "model_dump"):
            annotation = annotation.model_dump()
        if isinstance(annotation, dict) and annotation.get("type") == "audio_info":
            language = annotation.get("language")
            return language if isinstance(language, str) else None
    return None


def _message_annotations(message: object) -> list[object]:
    annotations = getattr(message, "annotations", None)
    if annotations is None and hasattr(message, "model_dump"):
        annotations = message.model_dump().get("annotations")
    if isinstance(annotations, list):
        return annotations
    return []
