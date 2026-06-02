from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from asr_evo.config import AppConfig
from asr_evo.providers.factory import create_llm_provider
from preference_prompt_optimizer.core import (
    LLMPreferenceExtractor,
    LLMPreferenceScorer,
    PreferencePromptOptimizer,
)
from preference_prompt_optimizer.io import load_jsonl, prompt_to_dict, write_json


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(async_main(argv))


async def async_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Optimize a reusable preference prompt from accepted user edits."
    )
    parser.add_argument("input", type=Path, help="JSONL file with input/model_output/user_edit fields.")
    parser.add_argument("-o", "--output", type=Path, help="Write JSON artifact to this path.")
    parser.add_argument("--config", default="config.toml", help="ASR-EVO config path.")
    parser.add_argument("--segment", default="", help="Only optimize samples from this segment/style/app.")
    parser.add_argument("--max-rules", type=int, default=8)
    parser.add_argument("--max-exemplars", type=int, default=3)
    parser.add_argument("--rounds", type=int, default=3, help="Number of optimize/score refinement rounds.")
    parser.add_argument("--model", default="", help="Override config.llm.model for preference optimization.")
    parser.add_argument("--batch-size", type=int, default=12)
    args = parser.parse_args(argv)

    config = AppConfig.load(args.config)
    if args.model:
        config = config.model_copy(update={"llm": config.llm.model_copy(update={"model": args.model})})

    samples = load_jsonl(args.input)
    client = create_llm_provider(config)
    try:
        optimizer = PreferencePromptOptimizer(
            LLMPreferenceExtractor(client, batch_size=args.batch_size),
            scorer=LLMPreferenceScorer(client),
        )
        prompt = await optimizer.optimize(
            samples,
            segment=args.segment or None,
            max_rules=args.max_rules,
            max_exemplars=args.max_exemplars,
            rounds=args.rounds,
        )
        report = optimizer.report(samples, prompt, segment=args.segment)
        payload = prompt_to_dict(prompt, report)
        if args.output:
            write_json(args.output, payload)
        else:
            print(prompt.user_addendum)
    finally:
        await client.aclose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
