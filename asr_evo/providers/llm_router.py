from __future__ import annotations

from typing import Any

from asr_evo.providers.openai_provider import OpenAIChatCompletionsLLMProvider


class LLMProfileRouter:
    def __init__(
        self,
        *,
        default_provider: OpenAIChatCompletionsLLMProvider,
        profiles: dict[str, OpenAIChatCompletionsLLMProvider],
    ) -> None:
        self.default_provider = default_provider
        self.profiles = profiles

    async def polish(
        self,
        raw_text: str,
        context: str,
        prompt_instruction: str,
        *,
        profile: str | None = None,
    ) -> str:
        return await self._provider(profile).polish(raw_text, context, prompt_instruction)

    async def complete_json(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0,
    ) -> dict[str, Any]:
        return await self.default_provider.complete_json(messages, temperature=temperature)

    async def aclose(self) -> None:
        closed: set[int] = set()
        for provider in (self.default_provider, *self.profiles.values()):
            if id(provider) in closed:
                continue
            closed.add(id(provider))
            await provider.aclose()

    def _provider(self, profile: str | None) -> OpenAIChatCompletionsLLMProvider:
        if profile is None:
            return self.default_provider
        try:
            return self.profiles[profile]
        except KeyError as exc:
            raise ValueError(f"LLM profile not found: {profile}") from exc
