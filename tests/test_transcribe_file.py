from types import SimpleNamespace

import pytest

from asr_evo.cli import transcribe_file
from asr_evo.config import AppConfig
from asr_evo.core.ports import Transcript


@pytest.mark.parametrize("auto_polish", [True, False])
async def test_file_cli_routes_the_selected_prompt_profile_and_closes_providers(
    tmp_path,
    monkeypatch,
    capsys,
    auto_polish,
):
    prompt = tmp_path / "test.md"
    prompt.write_text('+++\nllm_profile = "local"\n+++\n润色文本。\n')
    config = AppConfig.model_validate(
        {
            "style": {"prompts_dir": str(tmp_path), "mode": "test"},
            "llm": {
                "default_profile": "local",
                "profiles": {
                    "local": {
                        "backend": "ollama",
                        "base_url": "http://localhost:11434",
                        "model": "test",
                    },
                },
            },
        }
    )
    config.llm.auto_polish = auto_polish
    calls = []

    class ASR:
        async def transcribe(self, audio):
            return Transcript("原文")

        async def aclose(self):
            calls.append("asr closed")

    class LLM:
        async def polish(self, text, **kwargs):
            calls.append(kwargs["profile"])
            return "润色"

        async def aclose(self):
            calls.append("llm closed")

    monkeypatch.setattr(
        transcribe_file.sf,
        "info",
        lambda path: SimpleNamespace(
            samplerate=16000,
            duration=1,
        ),
    )
    monkeypatch.setattr(transcribe_file, "create_asr_provider", lambda config: ASR())
    def create_llm(config):
        assert auto_polish, "Direct transcription must not instantiate an LLM"
        return LLM()
    monkeypatch.setattr(transcribe_file, "create_llm_provider", create_llm)
    await transcribe_file._run(tmp_path / "audio.wav", config)
    assert calls == (["local", "asr closed", "llm closed"] if auto_polish else ["asr closed"])
    assert ("润色" if auto_polish else "原文") in capsys.readouterr().out
