from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from preference_prompt_optimizer.core import (
    EditSample,
    OptimizedPrompt,
    OptimizationReport,
    PreferenceRule,
    RuleCategory,
)


def load_jsonl(path: Path) -> list[EditSample]:
    samples = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            payload = json.loads(line)
            samples.append(sample_from_mapping(payload, line_number=line_number))
    return samples


def sample_from_mapping(payload: dict[str, Any], *, line_number: int = 0) -> EditSample:
    missing = [
        field
        for field in ("input", "prompt_instruction", "model_output", "user_edit")
        if field not in payload
    ]
    if missing:
        location = f" on line {line_number}" if line_number else ""
        raise ValueError(f"Missing required field(s){location}: {', '.join(missing)}")
    input_text = str(payload.get("input") or "")
    prompt_instruction = str(payload.get("prompt_instruction") or "")
    model_output = str(payload.get("model_output") or "")
    user_edit = str(payload.get("user_edit") or "")
    sample_id = str(payload.get("sample_id") or payload.get("id") or line_number or "")
    segment = str(payload.get("segment") or "")
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    return EditSample(
        input=input_text,
        model_output=model_output,
        user_edit=user_edit,
        prompt_instruction=prompt_instruction,
        sample_id=sample_id,
        segment=segment,
        metadata={str(key): str(value) for key, value in metadata.items()},
    )


def prompt_to_dict(prompt: OptimizedPrompt, report: OptimizationReport | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "system_addendum": prompt.system_addendum,
        "user_addendum": prompt.user_addendum,
        "rules": [rule_to_dict(item) for item in prompt.rules],
        "exemplars": [asdict(item) for item in prompt.exemplars],
        "score": prompt.score,
        "rounds": [asdict(item) for item in prompt.rounds],
    }
    if report is not None:
        payload["report"] = asdict(report)
    return payload


def rule_to_dict(rule: PreferenceRule) -> dict[str, Any]:
    return {
        "category": rule.category.value,
        "instruction": rule.instruction,
        "evidence": list(rule.evidence),
        "support": rule.support,
        "confidence": rule.confidence,
    }


def rule_from_dict(payload: dict[str, Any]) -> PreferenceRule:
    return PreferenceRule(
        category=RuleCategory(str(payload["category"])),
        instruction=str(payload["instruction"]),
        evidence=tuple(str(item) for item in payload.get("evidence", [])),
        support=int(payload.get("support", 1)),
        confidence=float(payload.get("confidence", 0.5)),
    )


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
