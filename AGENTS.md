# Agent Development Guide

This project is small enough that extra abstraction can become debt quickly. When editing it, prefer clear ownership, small modules, and deletion of unused code over speculative extension points.

## Architecture Boundaries

- `asr_evo/core/` owns platform-independent behavior: dictation flow, ports, context, errors, state, and pure application services.
- `asr_evo/providers/` owns external ASR/LLM adapters and HTTP retry/error normalization.
- `asr_evo/platforms/macos/` owns AppKit/Quartz/sounddevice integration only.
- `asr_evo/storage/` owns SQLite history persistence.
- `asr_evo/postprocess/` owns prompt loading and LLM message construction.
- `asr_evo/cli/` may compose existing services, but must not duplicate business rules from runtime/core.

If logic can be tested without macOS, keep it out of `platforms/macos/`.

## Refactoring Rules

- Do not introduce a new abstraction unless it removes real duplication or isolates a concrete external boundary.
- Delete unused code instead of keeping "future-ready" placeholders.
- Do not add optional feature flags that are always true or always false.
- Do not keep empty base packages, unused Protocol methods, or stand-in classes after the real implementation exists.
- Prefer one canonical implementation of a rule. For example, default style selection belongs in `StyleBindingService`, not separately in CLI/runtime code.
- Keep `MacOSDictationRuntime` as an orchestrator. It may wire services together, but should not accumulate prompt selection, config mutation, menu formatting, or persistence policy.
- Keep `MacOSStatusTray` focused on AppKit menu rendering. Pure menu text, tree building, or state formatting should be helper functions that can be unit-tested.

## Implementation Expectations

- Read nearby code before changing interfaces.
- Use existing ports and dataclasses before inventing new ones.
- Keep constructor argument lists short by grouping stable dependencies/options when the list starts to sprawl.
- Preserve local user files such as `.env`, `config.toml`, and `data/`.
- Do not modify generated caches, `__pycache__`, local databases, or build artifacts.
- When deleting code, search for all references with `rg` and remove stale docs/tests at the same time.

## Tests And Verification

Before handing off code changes, run:

```bash
.venv/bin/python -m pytest
.venv/bin/python -m ruff check .
```

If a change touches macOS runtime, tray, hotkey, recorder, or inserter behavior, also do a manual smoke test of the tray app on macOS.

## Review Checklist

- Is there duplicated business logic in CLI, runtime, and core?
- Is any branch impossible because a constant never changes?
- Is any Protocol method unused by callers?
- Is any "base" or "console" implementation now just historical scaffolding?
- Is the new code testable without AppKit when it does not strictly need AppKit?
- Did the docs still describe the code after the change?
