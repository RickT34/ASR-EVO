# Preference Prompt Optimizer

This is a project-independent optimizer for learning lightweight prompt
preferences from accepted user edits through an OpenAI-compatible LLM API.

## Why This Design

The most deployable approach is not full fine-tuning and not opaque global prompt
search. It is a CIPHER/PRELUDE-style loop:

1. collect `(input, prompt_instruction, model_output, user_edit)` examples;
2. infer explicit preference rules from the user edits;
3. aggregate and rank stable rules;
4. render a short prompt addendum plus representative accepted edits;
5. keep the artifact editable, auditable, and reversible.

This keeps cost low, preserves privacy better than training pipelines, and works
with the same OpenAI-compatible chat-completions provider used by the main
project. The optimizer does not include a local heuristic fallback: preference
extraction is always performed through the LLM API path.

## Input

JSONL uses this schema:

```json
{
  "input": "context plus current recognized text",
  "prompt_instruction": "prompt being optimized",
  "model_output": "...",
  "user_edit": "...",
  "segment": "work-chat"
}
```

`input` should contain the fixed part of the polishing input: local context plus
the current recognized text. `prompt_instruction` is separated because it is the
part we expect to optimize repeatedly.

## CLI

```bash
python -m preference_prompt_optimizer.cli edits.jsonl \
  -o optimized_prompt.json

python -m preference_prompt_optimizer.cli edits.jsonl \
  --segment work-chat
```

The JSON output contains:

- `system_addendum`: concise rules for a system/developer prompt;
- `user_addendum`: rules plus representative accepted edits;
- `rules`: structured, scored preference rules;
- `exemplars`: selected examples;
- `score`: current prompt score from the LLM evaluator;
- `rounds`: score and prompt snapshot for each refinement round;
- `report`: sample count, observed edit similarity, and deployment notes.

The CLI loads `config.toml` by default and uses the same LLM configuration and
`DASHSCOPE_API_KEY` environment variable as normal polishing. Use `--config` for
another config file or `--model` to temporarily override `config.llm.model`.
It reuses the project LLM provider factory, so OpenAI SDK behavior, request
debugging, and API shape stay aligned with the normal polishing path.

By default the optimizer runs three refinement rounds. Use `--rounds N` to trade
cost for additional attempts to improve the score.

For ASR-EVO data, export training JSONL from local history first:

```bash
python -m preference_prompt_optimizer.export_asr_evo_history \
  --database data/asr_evo.sqlite3 \
  --config config.toml \
  -o /private/tmp/asr_evo_preference_train.jsonl
```

The exporter reconstructs each record's fixed polishing input from local history
and writes the then-current style prompt separately as `prompt_instruction`.

## Sample Size

- 10-20 samples: smoke test only.
- 30-50 samples: useful MVP for one segment/style.
- 100-200 samples: enough to split by segment and compare variants.
- 500+ samples: consider learned rankers or fine-tuning, but keep this prompt
  artifact as the inspectable baseline.

## Example Test Data

See `examples/synthetic_user_edits.jsonl` for a 20-example synthetic dataset and
`examples/TESTING.md` for the recommended API smoke, segment, regression, and
manual evaluation workflow.
