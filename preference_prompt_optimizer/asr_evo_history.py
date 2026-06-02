from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from asr_evo.config import ContextConfig
from asr_evo.core.context import ContextStore, DictationRecord
from asr_evo.postprocess.prompts import render_polish_input
from asr_evo.postprocess.styles import StyleRegistry
from asr_evo.storage.history import HistoryStore
from preference_prompt_optimizer.core import EditSample


def load_history_samples(
    database_path: str | Path,
    *,
    context_config: ContextConfig | None = None,
    prompts_dir: str | Path = "prompts",
    limit: int | None = None,
    segment: str = "style",
) -> list[EditSample]:
    records = all_history_records(database_path)
    if limit is not None:
        records = records[-limit:]
    context_config = context_config or ContextConfig()
    context_store = context_config.store()
    style_registry = StyleRegistry(prompts_dir=prompts_dir)
    return samples_from_records(
        records,
        context_store=context_store,
        style_registry=style_registry,
        segment=segment,
        context_enabled=context_config.enabled,
    )


def samples_from_records(
    records: list[DictationRecord],
    *,
    context_store: ContextStore,
    style_registry: StyleRegistry | None = None,
    segment: str = "style",
    context_enabled: bool = True,
) -> list[EditSample]:
    samples = []
    for index, record in enumerate(records):
        if not record.final_text.strip() or not record.user_edited_text.strip():
            continue
        if record.final_text.strip() == record.user_edited_text.strip():
            continue
        prior_records = records[:index]
        context = ""
        if context_enabled:
            context = context_store.render_for_prompt(
                app_context=record.app_context,
                records=prior_records,
                now=record.ended_at,
            )
        prompt_instruction, prompt_found = prompt_for_record(record, style_registry)
        samples.append(
            EditSample(
                sample_id=record.id,
                segment=sample_segment(record, segment),
                input=render_polish_input(raw_text=record.raw_text, context=context),
                model_output=record.final_text,
                user_edit=record.user_edited_text,
                prompt_instruction=prompt_instruction,
                metadata={
                    "style": record.style,
                    "prompt_found": str(prompt_found).lower(),
                    "bundle_id": record.app_context.bundle_id or "",
                    "app_name": record.app_context.app_name or "",
                    "window_title": record.app_context.window_title or "",
                    "ended_at": record.ended_at.isoformat(),
                },
            )
        )
    return samples


def write_samples_jsonl(samples: Iterable[EditSample], path: str | Path) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        for sample in samples:
            handle.write(
                json.dumps(
                    {
                        "sample_id": sample.sample_id,
                        "segment": sample.segment,
                        "input": sample.input,
                        "prompt_instruction": sample.prompt_instruction,
                        "model_output": sample.model_output,
                        "user_edit": sample.user_edit,
                        "metadata": sample.metadata,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )


def prompt_for_record(
    record: DictationRecord,
    style_registry: StyleRegistry | None,
) -> tuple[str, bool]:
    if style_registry is None:
        return "", False
    if style_registry.has(record.style):
        return style_registry.get(record.style).prompt, True
    return "", False


def all_history_records(database_path: str | Path) -> list[DictationRecord]:
    store = HistoryStore(database_path)
    return store.all_records()


def sample_segment(record: DictationRecord, segment: str) -> str:
    if segment == "app":
        return record.app_context.bundle_id or record.app_context.app_name or "unknown-app"
    if segment == "app-style":
        app = record.app_context.bundle_id or record.app_context.app_name or "unknown-app"
        return f"{app}/{record.style}"
    return record.style
