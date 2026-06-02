from __future__ import annotations

import json

from preference_prompt_optimizer import cli


async def test_cli_uses_project_config_and_provider_factory(tmp_path, monkeypatch) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        '[llm]\nbase_url = "https://example.test/v1"\nmodel = "configured-model"\n',
        encoding="utf-8",
    )
    data_path = tmp_path / "samples.jsonl"
    data_path.write_text(
        json.dumps(
            {
                "sample_id": "sample-1",
                "segment": "chat",
                "input": "当前语音识别文本：\n继续写",
                "prompt_instruction": "整理成聊天消息。",
                "model_output": "我们继续写。",
                "user_edit": "继续写。",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    output_path = tmp_path / "optimized.json"
    created = {}

    def fake_create_llm_provider(config):
        created["base_url"] = config.llm.base_url
        created["model"] = config.llm.model
        return ScriptedJSONClient()

    monkeypatch.setattr(cli, "create_llm_provider", fake_create_llm_provider)

    result = await cli.async_main(
        [
            str(data_path),
            "--config",
            str(config_path),
            "--model",
            "override-model",
            "--rounds",
            "1",
            "-o",
            str(output_path),
        ]
    )

    assert result == 0
    assert created == {"base_url": "https://example.test/v1", "model": "override-model"}
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["score"] == 0.7


class ScriptedJSONClient:
    async def complete_json(self, messages, *, temperature=0):
        if "Score the candidate" in messages[1]["content"]:
            return {"score": 0.7, "sample_scores": {"sample-1": 0.7}, "rationale": "ok"}
        return {
            "rules": [
                {
                    "category": "concision",
                    "instruction": "Keep accepted edits concise.",
                    "evidence": ["sample-1"],
                    "support": 1,
                    "confidence": 0.8,
                }
            ]
        }

    async def aclose(self) -> None:
        pass
