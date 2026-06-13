"""Generic LLM-as-judge that routes to whichever provider the company has configured.

Provider priority:
1. EVAL_JUDGE_PROVIDER company setting (explicit choice)
2. Auto-detect from which API keys are present (Mistral → OpenAI → Gemini → Claude → Groq)

Model is read from EVAL_JUDGE_MODEL company setting, or a sensible default per provider.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Iterable

logger = logging.getLogger(__name__)

JUDGE_AXES = (
    "call_summary",
    "lead_qualification",
    "next_action",
    "tool_use_honesty",
    "tone_brand",
    "handoff_escalation",
)

JUDGE_THRESHOLDS: dict[str, int] = {
    "call_summary": 4,
    "lead_qualification": 4,
    "next_action": 4,
    "tool_use_honesty": 4,
    "tone_brand": 3,
    "handoff_escalation": 4,
}

PROVIDER_DEFAULTS: dict[str, str] = {
    "mistral": "mistral-large-latest",
    "openai": "gpt-4o-mini",
    "gemini": "gemini-1.5-flash",
    "claude": "claude-haiku-4-5-20251001",
    "groq": "llama-3.1-8b-instant",
}

JUDGE_SYSTEM_PROMPT = (
    "You are a strict evaluation judge for CRM and voice-agent LLM outputs. "
    "Judge only from the task, model output, reference/source data, and rubric. "
    "Do not reward plausible claims that are not supported by the reference. "
    "Return only valid JSON matching the requested schema."
)


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


def _build_prompt(case: EvalCase, axes: tuple[str, ...], thresholds: dict[str, int]) -> str:
    axis_lines = "\n".join(
        f"- {axis}: integer 1-5. Passing threshold: {thresholds.get(axis, 4)}."
        for axis in axes
    )
    rubric = case.rubric or (
        "Use the axis definitions. Penalize unsupported facts, missing required details, "
        "and poor user fit."
    )
    score_shape = ", ".join(f'"{axis}": 1' for axis in axes)
    return f"""Evaluate this model output.

Axes:
{axis_lines}

Score meanings:
1 = unacceptable, 2 = poor, 3 = mixed, 4 = good, 5 = excellent.
For tool_use_honesty, 5 = fully grounded/no hallucination; 1 = fabricated facts.

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


def _parse_json(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    return json.loads(stripped)


def _clamp(value: Any) -> int:
    try:
        return max(1, min(5, int(value)))
    except (TypeError, ValueError):
        return 1


def _coerce_result(
    case: EvalCase,
    payload: dict[str, Any],
    axes: tuple[str, ...],
    thresholds: dict[str, int],
) -> JudgeResult:
    raw_scores = payload.get("scores") or {}
    scores: dict[str, int] = {}
    failures = list(payload.get("failures") or [])
    for axis in axes:
        score = _clamp(raw_scores.get(axis))
        scores[axis] = score
        if score < thresholds.get(axis, 4) and axis not in failures:
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


# ---------------------------------------------------------------------------
# Provider implementations
# ---------------------------------------------------------------------------

async def _call_mistral(api_key: str, model: str, prompt: str, sys_prompt: str) -> str:
    from mistralai.client import Mistral
    client = Mistral(api_key=api_key)
    messages = [{"role": "system", "content": sys_prompt}, {"role": "user", "content": prompt}]
    if hasattr(client.chat, "complete_async"):
        resp = await client.chat.complete_async(
            model=model, messages=messages, temperature=0, max_tokens=1200,
            response_format={"type": "json_object"},
        )
        return resp.choices[0].message.content
    chunks = await client.chat.stream_async(model=model, messages=messages, temperature=0, max_tokens=1200)
    text = ""
    async for chunk in chunks:
        delta = chunk.data.choices[0].delta
        if delta.content:
            text += delta.content
    return text


async def _call_openai_compat(api_key: str, model: str, prompt: str, sys_prompt: str, base_url: str | None = None) -> str:
    import openai
    kwargs: dict[str, Any] = {"api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url
    client = openai.AsyncOpenAI(**kwargs)
    resp = await client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": sys_prompt}, {"role": "user", "content": prompt}],
        temperature=0,
        max_tokens=1200,
        response_format={"type": "json_object"},
    )
    return resp.choices[0].message.content


async def _call_gemini(api_key: str, model: str, prompt: str, sys_prompt: str) -> str:
    try:
        from google import genai
        client = genai.Client(api_key=api_key)
        full_prompt = f"{sys_prompt}\n\n{prompt}"
        resp = await asyncio.to_thread(
            client.models.generate_content,
            model=model,
            contents=full_prompt,
        )
        return resp.text
    except Exception:
        import google.generativeai as genai2  # type: ignore
        genai2.configure(api_key=api_key)
        m = genai2.GenerativeModel(model_name=model, system_instruction=sys_prompt)
        resp = await asyncio.to_thread(m.generate_content, prompt)
        return resp.text


async def _call_claude(api_key: str, model: str, prompt: str, sys_prompt: str) -> str:
    import anthropic
    client = anthropic.AsyncAnthropic(api_key=api_key)
    msg = await client.messages.create(
        model=model,
        max_tokens=1200,
        system=sys_prompt,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text


# ---------------------------------------------------------------------------
# Public judge class
# ---------------------------------------------------------------------------

class CallJudge:
    """Routes a single eval call to the configured LLM provider."""

    def __init__(
        self,
        provider: str,
        api_key: str,
        model: str,
        axes: tuple[str, ...] = JUDGE_AXES,
        thresholds: dict[str, int] | None = None,
        groq_base_url: str = "https://api.groq.com/openai/v1",
    ):
        self.provider = provider.lower()
        self.api_key = api_key
        self.model = model
        self.axes = axes
        self.thresholds = {**JUDGE_THRESHOLDS, **(thresholds or {})}
        self.groq_base_url = groq_base_url

    async def _complete(self, prompt: str) -> str:
        p = self.provider
        if p == "mistral":
            return await _call_mistral(self.api_key, self.model, prompt, JUDGE_SYSTEM_PROMPT)
        if p in ("openai",):
            return await _call_openai_compat(self.api_key, self.model, prompt, JUDGE_SYSTEM_PROMPT)
        if p == "groq":
            return await _call_openai_compat(self.api_key, self.model, prompt, JUDGE_SYSTEM_PROMPT, self.groq_base_url)
        if p == "gemini":
            return await _call_gemini(self.api_key, self.model, prompt, JUDGE_SYSTEM_PROMPT)
        if p == "claude":
            return await _call_claude(self.api_key, self.model, prompt, JUDGE_SYSTEM_PROMPT)
        raise ValueError(f"Unknown judge provider: {self.provider}")

    async def judge(self, case: EvalCase) -> JudgeResult:
        prompt = _build_prompt(case, self.axes, self.thresholds)
        text = await self._complete(prompt)
        payload = _parse_json(text)
        return _coerce_result(case, payload, self.axes, self.thresholds)

    async def judge_batch(self, cases: list[EvalCase], concurrency: int = 5) -> list[JudgeResult]:
        sem = asyncio.Semaphore(max(1, concurrency))

        async def run_one(c: EvalCase) -> JudgeResult:
            async with sem:
                return await self.judge(c)

        return await asyncio.gather(*(run_one(c) for c in cases))


def build_judge_from_settings(
    session: Any,
    company_id: int,
    axes: tuple[str, ...] = JUDGE_AXES,
    thresholds: dict[str, int] | None = None,
) -> CallJudge:
    """Resolve provider/model/key from company settings and build a CallJudge.

    Priority:
      1. EVAL_JUDGE_PROVIDER + EVAL_JUDGE_MODEL settings
      2. Auto-detect from whichever provider key exists
    """
    from credentials_service import get_company_setting_value

    def _s(key: str) -> str | None:
        return get_company_setting_value(session, company_id, key)

    provider = (_s("EVAL_JUDGE_PROVIDER") or "").lower().strip()
    model_override = (_s("EVAL_JUDGE_MODEL") or "").strip()

    # Key map per provider
    key_map = {
        "mistral": _s("MISTRAL_API_KEY"),
        "openai": _s("OPENAI_API_KEY"),
        "gemini": _s("GEMINI_API_KEY"),
        "claude": _s("CLAUDE_API_KEY") or _s("ANTHROPIC_API_KEY"),
        "groq": _s("GROQ_API_KEY"),
    }

    if provider and key_map.get(provider):
        api_key = key_map[provider]
        model = model_override or PROVIDER_DEFAULTS.get(provider, "")
        return CallJudge(provider=provider, api_key=api_key, model=model, axes=axes, thresholds=thresholds)

    # Auto-detect
    for prov in ("mistral", "openai", "gemini", "claude", "groq"):
        key = key_map.get(prov)
        if key:
            model = model_override or PROVIDER_DEFAULTS[prov]
            return CallJudge(provider=prov, api_key=key, model=model, axes=axes, thresholds=thresholds)

    raise ValueError(
        "No LLM API key configured for eval judge. "
        "Set EVAL_JUDGE_PROVIDER + one of MISTRAL_API_KEY / OPENAI_API_KEY / "
        "GEMINI_API_KEY / CLAUDE_API_KEY / GROQ_API_KEY in company settings."
    )


def summarize_results(results: Iterable[JudgeResult]) -> dict[str, Any]:
    result_list = list(results)
    total = len(result_list)
    failed = [r for r in result_list if not r.pass_]
    return {
        "total": total,
        "passed": total - len(failed),
        "failed": len(failed),
        "pass_rate": (total - len(failed)) / total if total else 0,
        "failed_ids": [r.id for r in failed],
    }
