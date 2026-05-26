from __future__ import annotations

import httpx

from asr_evo.postprocess.prompts import build_polish_messages
from asr_evo.providers.http_retry import raise_provider_status, with_http_retries
from asr_evo.providers.request_debug import RemoteRequestDebugOptions, dump_remote_request


class OpenAICompatibleLLMProvider:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: float = 30,
        request_debug: RemoteRequestDebugOptions | None = None,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.request_debug = request_debug or RemoteRequestDebugOptions()
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=timeout_seconds,
            headers={"Authorization": f"Bearer {api_key}"},
        )

    async def polish(self, raw_text: str, context: str, prompt_instruction: str) -> str:
        messages = build_polish_messages(
            raw_text=raw_text,
            context=context,
            prompt_instruction=prompt_instruction,
        )
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.2,
        }
        dump_remote_request(
            provider="openai-compatible-llm",
            method="POST",
            url=f"{self.base_url}/chat/completions",
            headers=dict(self.client.headers),
            json_payload=payload,
            options=self.request_debug,
        )
        response = await with_http_retries(
            lambda: self.client.post("/chat/completions", json=payload)
        )
        raise_provider_status(response)
        data = response.json()
        return data["choices"][0]["message"]["content"].strip()

    async def aclose(self) -> None:
        await self.client.aclose()
