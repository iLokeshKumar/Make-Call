from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.evals.mistral_judge import (  # noqa: E402
    MistralJudge,
    load_jsonl_cases,
    summarize_results,
    write_csv_results,
    write_jsonl_results,
)


def parse_thresholds(values: list[str]) -> dict[str, int]:
    thresholds: dict[str, int] = {}
    for value in values:
        if "=" not in value:
            raise argparse.ArgumentTypeError(f"Invalid threshold {value!r}; use axis=score.")
        axis, raw_score = value.split("=", 1)
        thresholds[axis.strip()] = int(raw_score)
    return thresholds


async def main() -> int:
    parser = argparse.ArgumentParser(description="Run Mistral-as-judge evals from a JSONL dataset.")
    parser.add_argument("--input", required=True, help="JSONL file with task, model_output, reference, optional rubric.")
    parser.add_argument("--output", required=True, help="Output path for judged results.")
    parser.add_argument("--format", choices=("jsonl", "csv"), default="jsonl")
    parser.add_argument("--model", default=None, help="Mistral judge model. Defaults to MISTRAL_MODEL.")
    parser.add_argument("--concurrency", type=int, default=5)
    parser.add_argument(
        "--threshold",
        action="append",
        default=[],
        help="Override pass threshold, e.g. --threshold correctness=5. Repeatable.",
    )
    args = parser.parse_args()

    cases = load_jsonl_cases(args.input)
    judge = MistralJudge(model=args.model, thresholds=parse_thresholds(args.threshold))
    results = await judge.judge_batch(cases, concurrency=args.concurrency)

    if args.format == "csv":
        write_csv_results(args.output, results)
    else:
        write_jsonl_results(args.output, results)

    summary = summarize_results(results)
    print(json.dumps(summary, indent=2))
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

