from types import SimpleNamespace

from asr_evo.cli import transcribe_file
from asr_evo.config import AppConfig
from asr_evo.core.ports import Transcript


async def test_file_cli_routes_the_selected_prompt_profile_and_closes_providers(
    tmp_path,
    monkeypatch,
    capsys,
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
    monkeypatch.setattr(transcribe_file, "create_llm_provider", lambda config: LLM())
    await transcribe_file._run(tmp_path / "audio.wav", config)
    assert calls == ["local", "asr closed", "llm closed"]
    assert "润色" in capsys.readouterr().out
