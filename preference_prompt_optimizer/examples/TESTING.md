# Preference Prompt Optimizer Test Method

This folder contains a synthetic test set for the project-independent optimizer.
It is designed to test whether the optimizer can infer stable preferences from
accepted user edits without relying on ASR-EVO internals. Preference extraction
uses the project's existing OpenAI-compatible LLM provider; there is no local
heuristic substitute.

## Data

`synthetic_user_edits.jsonl` has 20 examples across four segments:

- `chat`: concise, casual, no unnecessary headings or bullets.
- `email`: polite and professional outward-facing wording.
- `tech-note`: preserve English technical terms and avoid over-translation.
- `meeting`: use lightweight structure for action items, owners, risks, and conclusions.

Each record has:

```json
{
  "sample_id": "chat-001",
  "segment": "chat",
  "input": "context plus current recognized text",
  "prompt_instruction": "prompt being optimized",
  "model_output": "baseline model output",
  "user_edit": "accepted user edit",
  "metadata": {"target_rules": "human-readable expected behavior"}
}
```

The `metadata.target_rules` field is only for human inspection. The optimizer
does not use it.

For real ASR-EVO history, generate the JSONL with:

```bash
.venv/bin/python -m preference_prompt_optimizer.export_asr_evo_history \
  --database data/asr_evo.sqlite3 \
  --config config.toml \
  -o /private/tmp/asr_evo_preference_train.jsonl
```

The exporter writes fixed context and current recognized text into `input` and writes the
then-current prompt into `prompt_instruction`, so the optimizer can adjust the
prompt without baking the old prompt into the input.

## Smoke Test

Run the optimizer on the full synthetic set:

```bash
.venv/bin/python -m preference_prompt_optimizer.cli \
  preference_prompt_optimizer/examples/synthetic_user_edits.jsonl \
  -o /private/tmp/preference_prompt_all.json
```

Expected outcome:

- JSON is written successfully.
- `report.sample_count` is `20`.
- `score` contains the current prompt score from the LLM evaluator.
- `rounds` contains one entry per optimization round.
- `report.notes` says the set is below the 30-sample deployment threshold.
- The rules should include a mix of concision, tone, format, and terminology.

## Segment Tests

Run one segment at a time:

```bash
.venv/bin/python -m preference_prompt_optimizer.cli \
  preference_prompt_optimizer/examples/synthetic_user_edits.jsonl \
  --segment chat \
  -o /private/tmp/preference_prompt_chat.json

.venv/bin/python -m preference_prompt_optimizer.cli \
  preference_prompt_optimizer/examples/synthetic_user_edits.jsonl \
  --segment email \
  -o /private/tmp/preference_prompt_email.json

.venv/bin/python -m preference_prompt_optimizer.cli \
  preference_prompt_optimizer/examples/synthetic_user_edits.jsonl \
  --segment tech-note \
  -o /private/tmp/preference_prompt_tech.json

.venv/bin/python -m preference_prompt_optimizer.cli \
  preference_prompt_optimizer/examples/synthetic_user_edits.jsonl \
  --segment meeting \
  -o /private/tmp/preference_prompt_meeting.json
```

Expected qualitative checks:

- `chat`: should prefer concise revisions and avoid unnecessary structure.
- `email`: should infer professional/polite tone.
- `tech-note`: should preserve technical terms such as `API timeout`, `retry`,
  `SQLite`, `pipeline`, `extractor`, `LLM judge`, and `prompt search`.
- `meeting`: should infer lightweight structure for multi-point content.

## Regression Test

Run the normal automated checks. Unit tests cover prompt construction and JSON
response parsing. They do not use a local preference extractor or fake model
response.

```bash
.venv/bin/python -m pytest tests/preference_prompt_optimizer
.venv/bin/python -m ruff check preference_prompt_optimizer tests/preference_prompt_optimizer
```

To run the real LLM API integration test:

```bash
.venv/bin/python -m pytest tests/preference_prompt_optimizer -m integration
```

The optimizer CLI and integration test use `config.toml` plus the normal
`DASHSCOPE_API_KEY` environment variable. Pass `--model` to the CLI only when
you want to temporarily override `config.llm.model`.

For repo-wide verification:

```bash
.venv/bin/python -m pytest
.venv/bin/python -m ruff check .
```

## Manual Evaluation

The most useful manual evaluation is artifact review:

1. Open the generated JSON.
2. Read `system_addendum`.
3. Check whether each rule is supported by at least one visible edit.
4. Check whether segment-specific runs are cleaner than the all-segment run.
5. Reject rules that are too broad, too specific, or contradicted by examples.

For real deployment, use at least 30 accepted edits per segment before enabling
the generated addendum by default.
