from __future__ import annotations

import asyncio
import csv
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from mistralai.client import Mistral

from config import settings


DEFAULT_AXES = ("correctness", "hallucination", "helpfulness", "tone")
DEFAULT_THRESHOLDS = {
    "correctness": 4,
    "hallucination": 4,
    "helpfulness": 4,
    "tone": 3,
}

JUDGE_SYSTEM_PROMPT = """You are a strict evaluation judge for CRM and voice-agent LLM outputs.
Judge only from the task, model output, reference/source data, and rubric.
Do not reward plausible claims that are not supported by the reference.
Return only valid JSON matching the requested schema."""


@dataclass(frozen=True)
class EvalCase:
    id: str
    task: str
    model_output: str
    reference: str
    rubric: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class JudgeResult:
    id: str
    scores: dict[str, int]
    pass_: bool
    reasoning: str
    failures: list[str]
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        record: dict[str, Any] = {
            "id": self.id,
            "pass": self.pass_,
            "reasoning": self.reasoning,
            "failures": self.failures,
            "metadata": self.metadata,
        }
        for axis, score in self.scores.items():
            record[f"score_{axis}"] = score
        return record


class MistralJudge:
    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        thresholds: dict[str, int] | None = None,
        axes: Iterable[str] = DEFAULT_AXES,
        client: Any | None = None,
    ):
        self.api_key = api_key or settings.MISTRAL_API_KEY
        self.model = model or settings.MISTRAL_MODEL or "mistral-large-latest"
        self.axes = tuple(axes)
        self.thresholds = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
        self.client = client or (Mistral(api_key=self.api_key) if self.api_key else None)

        if not self.client:
            raise ValueError("MistralJudge requires MISTRAL_API_KEY or an injected client.")

    async def judge(self, case: EvalCase) -> JudgeResult:
        text = await self._complete_json(case)
        payload = _parse_json_response(text)
        return self._coerce_result(case, payload)

    async def judge_batch(self, cases: list[EvalCase], concurrency: int = 5) -> list[JudgeResult]:
        semaphore = asyncio.Semaphore(max(1, concurrency))

        async def run_one(case: EvalCase) -> JudgeResult:
            async with semaphore:
                return await self.judge(case)

        return await asyncio.gather(*(run_one(case) for case in cases))

    async def _complete_json(self, case: EvalCase) -> str:
        messages = [
            {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
            {"role": "user", "content": self._build_prompt(case)},
        ]

        if hasattr(self.client.chat, "complete_async"):
            response = await self.client.chat.complete_async(
                model=self.model,
                messages=messages,
                temperature=0,
                max_tokens=1200,
                response_format={"type": "json_object"},
            )
            return response.choices[0].message.content

        chunks = await self.client.chat.stream_async(
            model=self.model,
            messages=messages,
            temperature=0,
            max_tokens=1200,
        )
        text = ""
        async for chunk in chunks:
            delta = chunk.data.choices[0].delta
            if delta.content:
                text += delta.content
        return text

    def _build_prompt(self, case: EvalCase) -> str:
        axis_lines = "\n".join(
            f"- {axis}: integer 1-5. Passing threshold: {self.thresholds.get(axis, 4)}."
            for axis in self.axes
        )
        rubric = case.rubric or "Use the axis definitions. Penalize unsupported facts, missing required details, and poor user fit."
        score_shape = ", ".join(f'"{axis}": 1' for axis in self.axes)
        return f"""Evaluate this model output.

Axes:
{axis_lines}

Score meanings:
1 = unacceptable, 2 = poor, 3 = mixed, 4 = good, 5 = excellent.
For hallucination, 5 means fully grounded and 1 means severe unsupported claims.

Rubric:
{rubric}

Task:
{case.task}

Reference/source data:
{case.reference}

Model output:
{case.model_output}

Return JSON with exactly this shape:
{{
  "scores": {{{score_shape}}},
  "pass": true,
  "reasoning": "brief concrete explanation",
  "failures": ["axis names or concrete failure tags"]
}}"""

    def _coerce_result(self, case: EvalCase, payload: dict[str, Any]) -> JudgeResult:
        raw_scores = payload.get("scores") or {}
        scores: dict[str, int] = {}
        failures = list(payload.get("failures") or [])

        for axis in self.axes:
            score = _clamp_score(raw_scores.get(axis))
            scores[axis] = score
            if score < self.thresholds.get(axis, 4) and axis not in failures:
                failures.append(axis)

        passed = bool(payload.get("pass", True)) and not failures
        return JudgeResult(
            id=case.id,
            scores=scores,
            pass_=passed,
            reasoning=str(payload.get("reasoning") or ""),
            failures=failures,
            metadata=case.metadata,
        )


def load_jsonl_cases(path: str | Path) -> list[EvalCase]:
    cases: list[EvalCase] = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            cases.append(
                EvalCase(
                    id=str(row.get("id") or line_no),
                    task=str(row["task"]),
                    model_output=str(row["model_output"]),
                    reference=str(row.get("reference") or ""),
                    rubric=str(row.get("rubric") or ""),
                    metadata=dict(row.get("metadata") or {}),
                )
            )
    return cases


def write_jsonl_results(path: str | Path, results: Iterable[JudgeResult]) -> None:
    with Path(path).open("w", encoding="utf-8") as handle:
        for result in results:
            handle.write(json.dumps(result.to_record(), ensure_ascii=False) + "\n")


def write_csv_results(path: str | Path, results: Iterable[JudgeResult]) -> None:
    records = [result.to_record() for result in results]
    fieldnames = sorted({key for record in records for key in record.keys()})
    with Path(path).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)


def summarize_results(results: Iterable[JudgeResult]) -> dict[str, Any]:
    result_list = list(results)
    total = len(result_list)
    failed = [result for result in result_list if not result.pass_]
    return {
        "total": total,
        "passed": total - len(failed),
        "failed": len(failed),
        "pass_rate": (total - len(failed)) / total if total else 0,
        "failed_ids": [result.id for result in failed],
    }


def _parse_json_response(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    return json.loads(stripped)


def _clamp_score(value: Any) -> int:
    try:
        score = int(value)
    except (TypeError, ValueError):
        score = 1
    return max(1, min(5, score))

