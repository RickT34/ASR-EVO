from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from enum import StrEnum
from typing import Any, Protocol


class RuleCategory(StrEnum):
    CONSERVATIVE_EDITING = "conservative_editing"
    CONCISION = "concision"
    FLUENCY = "fluency"
    TONE = "tone"
    FORMAT = "format"
    TERMINOLOGY = "terminology"
    LANGUAGE = "language"
    CONTENT_SAFETY = "content_safety"


@dataclass(frozen=True)
class EditSample:
    """A project-agnostic record of one model output and the user's accepted edit."""

    input: str
    model_output: str
    user_edit: str
    prompt_instruction: str = ""
    sample_id: str = ""
    segment: str = ""
    metadata: dict[str, str] = field(default_factory=dict)

    def normalized_segment(self) -> str:
        return self.segment.strip() or "default"


@dataclass(frozen=True)
class PreferenceRule:
    category: RuleCategory
    instruction: str
    evidence: tuple[str, ...] = ()
    support: int = 1
    confidence: float = 0.5

    @property
    def key(self) -> tuple[RuleCategory, str]:
        return (self.category, normalize_instruction(self.instruction))


@dataclass(frozen=True)
class PromptCandidate:
    name: str
    instruction: str
    rules: tuple[PreferenceRule, ...] = ()


@dataclass(frozen=True)
class OptimizedPrompt:
    system_addendum: str
    user_addendum: str
    rules: tuple[PreferenceRule, ...]
    exemplars: tuple[EditSample, ...]
    score: float | None = None
    rounds: tuple["OptimizationRound", ...] = ()


@dataclass(frozen=True)
class PromptScore:
    score: float
    sample_scores: dict[str, float]
    rationale: str = ""


@dataclass(frozen=True)
class OptimizationRound:
    round_index: int
    score: float
    rule_count: int
    system_addendum: str
    notes: str = ""


@dataclass(frozen=True)
class OptimizationReport:
    sample_count: int
    segment: str
    rule_count: int
    avg_prompt_score: float | None
    avg_similarity_before: float
    recommended_min_samples: int
    notes: tuple[str, ...]


class PreferenceExtractor(Protocol):
    async def extract(self, samples: list[EditSample]) -> list[PreferenceRule]:
        """Extract candidate preference rules from accepted user edits."""


class JSONChatClient(Protocol):
    async def complete_json(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0,
    ) -> dict[str, Any]:
        """Return parsed JSON from an OpenAI-compatible chat-completions call."""


class LLMPreferenceExtractor:
    def __init__(self, client: JSONChatClient, *, batch_size: int = 12) -> None:
        self._client = client
        self._batch_size = batch_size

    async def extract(self, samples: list[EditSample]) -> list[PreferenceRule]:
        return await self.refine(samples, previous_rules=(), previous_score=None)

    async def refine(
        self,
        samples: list[EditSample],
        *,
        previous_rules: tuple[PreferenceRule, ...],
        previous_score: PromptScore | None,
    ) -> list[PreferenceRule]:
        rules: list[PreferenceRule] = []
        for batch in batches(samples, self._batch_size):
            try:
                payload = await self._client.complete_json(
                    build_extraction_messages(
                        batch,
                        previous_rules=previous_rules,
                        previous_score=previous_score,
                    ),
                    temperature=0,
                )
            except ValueError as exc:
                raise PreferenceOptimizerError(str(exc)) from exc
            rules.extend(parse_rule_response(payload))
        return rules


class LLMPreferenceScorer:
    def __init__(self, client: JSONChatClient) -> None:
        self._client = client

    async def score(self, samples: list[EditSample], prompt: OptimizedPrompt) -> PromptScore:
        try:
            payload = await self._client.complete_json(
                build_scoring_messages(samples, prompt),
                temperature=0,
            )
        except ValueError as exc:
            raise PreferenceOptimizerError(str(exc)) from exc
        return parse_score_response(payload)


class PreferencePromptOptimizer:
    """Optimize a reusable preference addendum from accepted user edits.

    The optimizer intentionally uses an LLM API as the preference extractor.
    There is no local heuristic fallback: production behavior and tests exercise
    the same API-shaped path.
    """

    def __init__(
        self,
        extractor: PreferenceExtractor,
        *,
        scorer: LLMPreferenceScorer | None = None,
    ) -> None:
        self._extractor = extractor
        self._scorer = scorer

    async def optimize(
        self,
        samples: list[EditSample],
        *,
        segment: str | None = None,
        max_rules: int = 8,
        max_exemplars: int = 3,
        rounds: int = 1,
    ) -> OptimizedPrompt:
        scoped = filter_samples(samples, segment)
        exemplars = tuple(select_exemplars(scoped, max_exemplars=max_exemplars))
        best_prompt: OptimizedPrompt | None = None
        previous_rules: tuple[PreferenceRule, ...] = ()
        previous_score: PromptScore | None = None
        history: list[OptimizationRound] = []

        for round_index in range(1, max(1, rounds) + 1):
            candidate_rules = await self._extract_round(scoped, previous_rules, previous_score)
            merged = merge_rules([*previous_rules, *candidate_rules])
            ranked = tuple(sorted(merged, key=rule_rank, reverse=True)[:max_rules])
            candidate = OptimizedPrompt(
                system_addendum=render_system_addendum(ranked),
                user_addendum=render_user_addendum(ranked, exemplars),
                rules=ranked,
                exemplars=exemplars,
            )
            score = await self._score(scoped, candidate)
            candidate = OptimizedPrompt(
                system_addendum=candidate.system_addendum,
                user_addendum=candidate.user_addendum,
                rules=candidate.rules,
                exemplars=candidate.exemplars,
                score=score.score,
            )
            history.append(
                OptimizationRound(
                    round_index=round_index,
                    score=score.score,
                    rule_count=len(candidate.rules),
                    system_addendum=candidate.system_addendum,
                    notes=score.rationale,
                )
            )
            if best_prompt is None or score.score >= (best_prompt.score or 0):
                best_prompt = candidate
            previous_rules = candidate.rules
            previous_score = score

        if best_prompt is None:
            best_prompt = OptimizedPrompt(
                system_addendum="",
                user_addendum="",
                rules=(),
                exemplars=exemplars,
                score=0,
            )
        return OptimizedPrompt(
            system_addendum=best_prompt.system_addendum,
            user_addendum=best_prompt.user_addendum,
            rules=best_prompt.rules,
            exemplars=best_prompt.exemplars,
            score=best_prompt.score,
            rounds=tuple(history),
        )

    def report(self, samples: list[EditSample], prompt: OptimizedPrompt, *, segment: str = "") -> OptimizationReport:
        scoped = filter_samples(samples, segment or None)
        notes = report_notes(scoped, prompt.rules)
        return OptimizationReport(
            sample_count=len(scoped),
            segment=segment or "default",
            rule_count=len(prompt.rules),
            avg_prompt_score=prompt.score,
            avg_similarity_before=mean(
                [text_similarity(sample.model_output, sample.user_edit) for sample in scoped]
            ),
            recommended_min_samples=30,
            notes=tuple(notes),
        )

    async def _extract_round(
        self,
        samples: list[EditSample],
        previous_rules: tuple[PreferenceRule, ...],
        previous_score: PromptScore | None,
    ) -> list[PreferenceRule]:
        refine = getattr(self._extractor, "refine", None)
        if callable(refine):
            return await refine(
                samples,
                previous_rules=previous_rules,
                previous_score=previous_score,
            )
        return await self._extractor.extract(samples)

    async def _score(self, samples: list[EditSample], prompt: OptimizedPrompt) -> PromptScore:
        if self._scorer is not None:
            return await self._scorer.score(samples, prompt)
        return PromptScore(
            score=mean([text_similarity(sample.model_output, sample.user_edit) for sample in samples]),
            sample_scores={
                sample.sample_id or str(index): text_similarity(sample.model_output, sample.user_edit)
                for index, sample in enumerate(samples, start=1)
            },
            rationale="No scorer configured; used baseline output/edit similarity.",
        )


def build_extraction_messages(
    samples: list[EditSample],
    *,
    previous_rules: tuple[PreferenceRule, ...] = (),
    previous_score: PromptScore | None = None,
) -> list[dict[str, str]]:
    categories = ", ".join(item.value for item in RuleCategory)
    samples_payload = [
        {
            "sample_id": sample.sample_id,
            "segment": sample.normalized_segment(),
            "input": sample.input,
            "prompt_instruction": sample.prompt_instruction,
            "model_output": sample.model_output,
            "user_edit": sample.user_edit,
        }
        for sample in samples
    ]
    return [
        {
            "role": "system",
            "content": (
                "You infer durable user writing preferences from accepted edits. "
                "Return only JSON. Do not include markdown."
            ),
        },
        {
            "role": "user",
            "content": (
                "Given triples of model input, model output, and user accepted edit, "
                "infer concise reusable preference rules. If previous rules and scores are provided, "
                "improve them instead of merely repeating them.\n"
                f"Allowed categories: {categories}.\n"
                "Return JSON with this schema: "
                '{"rules":[{"category":"concision","instruction":"...",'
                '"evidence":["sample_id"],"support":1,"confidence":0.0}]}.\n'
                "Rules must be supported by evidence sample ids and should not mention a single sample only "
                "unless the preference is clear.\n"
                f"Previous rules:\n{json.dumps(rules_payload(previous_rules), ensure_ascii=False, indent=2)}\n"
                f"Previous score:\n{score_payload(previous_score)}\n"
                f"Samples:\n{json.dumps(samples_payload, ensure_ascii=False, indent=2)}"
            ),
        },
    ]


def build_scoring_messages(samples: list[EditSample], prompt: OptimizedPrompt) -> list[dict[str, str]]:
    samples_payload = [
        {
            "sample_id": sample.sample_id,
            "segment": sample.normalized_segment(),
            "input_seen_by_model": sample.input,
            "prompt_instruction_under_optimization": sample.prompt_instruction,
            "baseline_model_output": sample.model_output,
            "user_expected_output": sample.user_edit,
        }
        for sample in samples
    ]
    prompt_payload = {
        "system_addendum": prompt.system_addendum,
        "rules": rules_payload(prompt.rules),
        "exemplars": [
            {
                "sample_id": sample.sample_id,
                "model_output": sample.model_output,
                "user_edit": sample.user_edit,
            }
            for sample in prompt.exemplars
        ],
    }
    return [
        {
            "role": "system",
            "content": (
                "You are a strict prompt evaluator. Estimate how well the preference prompt will make "
                "future model outputs match the user's accepted edits. Return only JSON."
            ),
        },
        {
            "role": "user",
            "content": (
                "Score the candidate preference prompt from 0.0 to 1.0 using input_seen_by_model. "
                "The stable input_seen_by_model contains the original local context and current recognized text. "
                "The prompt_instruction_under_optimization is the old prompt being improved. "
                "Judge whether the candidate preference prompt would improve that prompt under the same input. "
                "Use 1.0 for outputs expected to be nearly identical to user_expected_output, "
                "and 0.0 for no useful improvement over baseline_model_output. "
                "Return JSON with schema: "
                '{"score":0.0,"sample_scores":{"sample_id":0.0},"rationale":"..."}.\n'
                f"Candidate prompt:\n{json.dumps(prompt_payload, ensure_ascii=False, indent=2)}\n"
                f"Evaluation samples:\n{json.dumps(samples_payload, ensure_ascii=False, indent=2)}"
            ),
        },
    ]


def parse_rule_response(payload: dict[str, Any]) -> list[PreferenceRule]:
    raw_rules = payload.get("rules")
    if not isinstance(raw_rules, list):
        raise PreferenceOptimizerError("LLM JSON response must contain a rules list")

    rules = []
    for index, item in enumerate(raw_rules, start=1):
        if not isinstance(item, dict):
            raise PreferenceOptimizerError(f"Rule {index} is not an object")
        instruction = str(item.get("instruction") or "").strip()
        if not instruction:
            raise PreferenceOptimizerError(f"Rule {index} has no instruction")
        try:
            category = RuleCategory(str(item.get("category")))
        except ValueError as exc:
            raise PreferenceOptimizerError(f"Rule {index} has unknown category") from exc
        evidence = item.get("evidence", [])
        if not isinstance(evidence, list):
            raise PreferenceOptimizerError(f"Rule {index} evidence must be a list")
        rules.append(
            PreferenceRule(
                category=category,
                instruction=instruction,
                evidence=tuple(str(value) for value in evidence),
                support=max(1, int(item.get("support", len(evidence) or 1))),
                confidence=clamp_float(item.get("confidence", 0.5)),
            )
        )
    return rules


def parse_score_response(payload: dict[str, Any]) -> PromptScore:
    raw_sample_scores = payload.get("sample_scores", {})
    if not isinstance(raw_sample_scores, dict):
        raise PreferenceOptimizerError("LLM score response sample_scores must be an object")
    return PromptScore(
        score=clamp_float(payload.get("score", 0)),
        sample_scores={
            str(sample_id): clamp_float(score) for sample_id, score in raw_sample_scores.items()
        },
        rationale=str(payload.get("rationale") or ""),
    )


def rules_payload(rules: tuple[PreferenceRule, ...]) -> list[dict[str, Any]]:
    return [
        {
            "category": rule.category.value,
            "instruction": rule.instruction,
            "evidence": list(rule.evidence),
            "support": rule.support,
            "confidence": rule.confidence,
        }
        for rule in rules
    ]


def score_payload(score: PromptScore | None) -> str:
    if score is None:
        return "null"
    return json.dumps(
        {
            "score": score.score,
            "sample_scores": score.sample_scores,
            "rationale": score.rationale,
        },
        ensure_ascii=False,
        indent=2,
    )


def merge_rules(rules: list[PreferenceRule] | tuple[PreferenceRule, ...]) -> list[PreferenceRule]:
    grouped: dict[tuple[RuleCategory, str], list[PreferenceRule]] = defaultdict(list)
    for item in rules:
        grouped[item.key].append(item)

    merged = []
    for (_category, _instruction_key), items in grouped.items():
        support = sum(item.support for item in items)
        evidence = tuple(dict.fromkeys(example for item in items for example in item.evidence))[:5]
        confidence = min(0.95, mean([item.confidence for item in items]) + min(0.25, 0.05 * (support - 1)))
        merged.append(
            PreferenceRule(
                category=items[0].category,
                instruction=items[0].instruction,
                evidence=evidence,
                support=support,
                confidence=round(confidence, 3),
            )
        )
    return merged


def render_system_addendum(rules: tuple[PreferenceRule, ...]) -> str:
    if not rules:
        return ""
    lines = ["User preference rules inferred from accepted edits:"]
    for index, item in enumerate(rules, start=1):
        lines.append(f"{index}. {item.instruction}")
    lines.append("When rules conflict, preserve factual meaning and user intent first.")
    return "\n".join(lines)


def render_user_addendum(rules: tuple[PreferenceRule, ...], exemplars: tuple[EditSample, ...]) -> str:
    parts = []
    if rules:
        parts.append(render_system_addendum(rules))
    if exemplars:
        parts.append("Representative accepted edits:")
        for sample in exemplars:
            parts.append(
                "\n".join(
                    (
                        f"- Model output: {single_line(sample.model_output)}",
                        f"  User accepted: {single_line(sample.user_edit)}",
                    )
                )
            )
    return "\n\n".join(parts)


def filter_samples(samples: list[EditSample], segment: str | None) -> list[EditSample]:
    if not segment:
        return [sample for sample in samples if sample.model_output.strip() and sample.user_edit.strip()]
    return [
        sample
        for sample in samples
        if sample.normalized_segment() == segment and sample.model_output.strip() and sample.user_edit.strip()
    ]


def select_exemplars(samples: list[EditSample], *, max_exemplars: int) -> list[EditSample]:
    changed = [sample for sample in samples if sample.model_output.strip() != sample.user_edit.strip()]
    changed.sort(key=lambda sample: edit_distance_ratio(sample.model_output, sample.user_edit), reverse=True)
    return changed[:max_exemplars]


def rule_rank(item: PreferenceRule) -> tuple[float, int]:
    return (item.confidence, item.support)


def report_notes(samples: list[EditSample], rules: tuple[PreferenceRule, ...]) -> list[str]:
    notes = []
    if len(samples) < 10:
        notes.append("Fewer than 10 samples: use this only as a smoke test.")
    elif len(samples) < 30:
        notes.append("Fewer than 30 samples: review inferred rules manually before deployment.")
    if not rules:
        notes.append("No stable preference rules were inferred; collect more accepted edits.")
    if len({sample.normalized_segment() for sample in samples}) > 1:
        notes.append("Samples span multiple segments; optimize per segment when enough data exists.")
    return notes


def batches(samples: list[EditSample], batch_size: int) -> list[list[EditSample]]:
    if batch_size < 1:
        raise ValueError("batch_size must be >= 1")
    return [samples[index : index + batch_size] for index in range(0, len(samples), batch_size)]


def clamp_float(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.5
    return min(1.0, max(0.0, number))


def text_similarity(left: str, right: str) -> float:
    return SequenceMatcher(a=left.strip(), b=right.strip()).ratio()


def edit_distance_ratio(left: str, right: str) -> float:
    return 1.0 - text_similarity(left, right)


def normalize_instruction(value: str) -> str:
    return " ".join(value.lower().split())


def mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return round(sum(values) / len(values), 4)


def single_line(value: str, *, limit: int = 160) -> str:
    text = " ".join(value.split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "..."


class PreferenceOptimizerError(RuntimeError):
    pass
