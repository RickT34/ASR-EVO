from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx

from asr_evo.config import LLMProfileConfig
from asr_evo.postprocess.prompts import build_polish_messages


class OllamaLLMProvider:
    def __init__(self, config: LLMProfileConfig) -> None:
        self.config = config.model_copy(deep=True)
        self.client = httpx.AsyncClient(
            base_url=config.base_url.rstrip("/") + "/",
            timeout=config.timeout_seconds,
            trust_env=False,
        )
        self._used = False
        self._lock = asyncio.Lock()
        self._closed = False

    async def polish(self, raw_text: str, context: str, prompt_instruction: str) -> str:
        return await self._complete(
            build_polish_messages(
                raw_text=raw_text,
                context=context,
                prompt_instruction=prompt_instruction,
            ),
            temperature=0.2,
        )

    async def complete_json(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0,
    ) -> dict[str, Any]:
        content = await self._complete(messages, temperature=temperature, json_format=True)
        result = json.loads(content)
        if not isinstance(result, dict):
            raise ValueError("LLM response was not a JSON object")
        return result

    async def _complete(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float,
        json_format: bool = False,
    ) -> str:
        async with self._lock:
            if self._closed:
                raise RuntimeError("Ollama provider is closed")
            self._used = True
            payload = {
                "model": self.config.model,
                "messages": messages,
                "stream": False,
                "keep_alive": self.config.keep_alive_seconds,
                "options": {"temperature": temperature},
            }
            if self.config.enable_thinking is not None:
                payload["think"] = self.config.enable_thinking
            if json_format:
                payload["format"] = "json"
            try:
                response = await self.client.post("api/chat", json=payload)
                response.raise_for_status()
                result = response.json()
                if result.get("error"):
                    raise RuntimeError(f"Ollama: {result['error']}")
                return result["message"]["content"].strip()
            except (httpx.HTTPError, KeyError) as exc:
                raise RuntimeError(f"Ollama request failed: {exc}") from exc

    async def aclose(self) -> None:
        async with self._lock:
            if self._closed:
                return
            self._closed = True
            try:
                if self._used:
                    response = await self.client.post(
                        "api/generate",
                        json={"model": self.config.model, "keep_alive": 0},
                        timeout=5,
                    )
                    response.raise_for_status()
            finally:
                await self.client.aclose()
