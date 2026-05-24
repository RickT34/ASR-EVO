from __future__ import annotations

import httpx

from asr_evo.postprocess.prompts import build_polish_messages
from asr_evo.providers.http_retry import raise_provider_status, with_http_retries


class OpenAICompatibleLLMProvider:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: float = 30,
    ) -> None:
        self.model = model
        self.client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
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
        response = await with_http_retries(
            lambda: self.client.post("/chat/completions", json=payload)
        )
        raise_provider_status(response)
        data = response.json()
        return data["choices"][0]["message"]["content"].strip()

    async def aclose(self) -> None:
        await self.client.aclose()
