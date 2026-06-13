from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from services.evals.mistral_judge import EvalCase, MistralJudge, _parse_json_response, summarize_results


class FakeChat:
    def __init__(self, text: str):
        self.text = text
        self.calls = []

    async def complete_async(self, **kwargs):
        self.calls.append(kwargs)
        message = SimpleNamespace(content=self.text)
        choice = SimpleNamespace(message=message)
        return SimpleNamespace(choices=[choice])


class FakeClient:
    def __init__(self, text: str):
        self.chat = FakeChat(text)


@pytest.mark.asyncio
async def test_judge_scores_and_threshold_failures():
    fake_payload = {
        "scores": {"correctness": 5, "hallucination": 4, "helpfulness": 2, "tone": 3},
        "pass": True,
        "reasoning": "Answer is grounded but not useful enough.",
        "failures": [],
    }
    client = FakeClient(json.dumps(fake_payload))
    judge = MistralJudge(client=client, thresholds={"helpfulness": 4})

    result = await judge.judge(
        EvalCase(
            id="case-1",
            task="Answer a warranty question.",
            model_output="Contact support.",
            reference="Warranty lasts 12 months.",
        )
    )

    assert result.pass_ is False
    assert result.scores["helpfulness"] == 2
    assert "helpfulness" in result.failures
    assert client.chat.calls[0]["temperature"] == 0
    assert client.chat.calls[0]["response_format"] == {"type": "json_object"}
    assert "Warranty lasts 12 months." in client.chat.calls[0]["messages"][1]["content"]


def test_parse_json_response_strips_markdown_fence():
    parsed = _parse_json_response('```json\n{"pass": true, "scores": {}}\n```')
    assert parsed == {"pass": True, "scores": {}}


def test_summarize_results_counts_failures():
    results = [
        SimpleNamespace(id="a", pass_=True),
        SimpleNamespace(id="b", pass_=False),
    ]

    assert summarize_results(results) == {
        "total": 2,
        "passed": 1,
        "failed": 1,
        "pass_rate": 0.5,
        "failed_ids": ["b"],
    }
